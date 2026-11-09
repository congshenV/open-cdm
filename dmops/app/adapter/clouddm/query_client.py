"""console syncQuery OpenAPI 调用（AK/SK 签名）——数据校验的 SQL 通道。

契约（对照 console QueryApi / DmApiDsQueryFO / OpenApiSessionManager 核验）：
- POST /api/open/query/syncQuery，AK/SK 签名放 header（AccessKeyId/Signature/SignatureMethod/SignatureNonce）
- 请求体：{queryString, queryType: RequestQuery, queryForce: false, levels}
- levels 为裸值三元素 [envId, dsId, database]（parseLevels：get(0)=envId、get(1)=dsId、
  get(2)=MySQL/PG 的 schema 维；不是 'ds:{id}' 前缀格式）
- 响应 ResWebData：code=="1" 成功，data = DmApiQueryResultVO{columnList, rows}
- rows 为 ResultSetRow{data: List[ResultSetValue>}，按 columnList 顺序对位
- 服务端 54s future 超时，客户端留 50s；行数截断由本层实现（服务端不保证 LIMIT）
"""

import json
import logging
import urllib.error
import urllib.request

from app import config
from app.adapter.clouddm import openapi_signer
from app.util.errors import ApiError

logger = logging.getLogger(__name__)

# QueryApi.DEFAULT_QUERY_TIMEOUT_SEC = 54，客户端留 4s 余量。
_TIMEOUT_SEC = 50

# 行数上限保护（服务端仅 SQL 重写时加 LIMIT，不保证）。
_ROW_LIMIT = 1000


def _ak_sk() -> tuple[str, str]:
    """从配置管理读 clouddm_api_key（JSON {ak, sk}）。缺失/格式异常给出可定位的错误。"""
    from app.infra import config_repository as config_repo

    row = config_repo.get_by_key('clouddm_api_key')
    value = (row or {}).get('config_value') or ''
    try:
        parsed = json.loads(value) if value else {}
    except ValueError as error:
        raise ApiError(
            code=-500,
            user_message='配置项 clouddm_api_key 值不是合法 JSON（{"ak","sk"}），请在配置管理中修正',
            message=f'clouddm_api_key invalid json: {error}',
            http_status=500,
        ) from error
    access_key = str(parsed.get('ak') or '').strip()
    secret_key = str(parsed.get('sk') or '').strip()
    if not access_key or not secret_key:
        raise ApiError(
            code=-500,
            user_message='配置管理缺少 clouddm_api_key（JSON {"ak","sk"}），请先配置',
            message='clouddm_api_key missing in ops_config',
            http_status=500,
        )
    return access_key, secret_key


def execute_query(ds_id: int, env_id: int, database: str, sql: str) -> tuple[list[str], list[list]]:
    """对指定数据源执行只读 SQL，返回 (columnList, rows)——rows 为原始值矩阵。

    抛 ApiError（签名失败/超时/SQL 错误），由调用方落校验失败记录。
    """
    ak, sk = _ak_sk()
    body = {
        'queryString': sql,
        'queryType': 'RequestQuery',
        'queryForce': False,
        'levels': [str(env_id), str(ds_id), database],
    }
    req = urllib.request.Request(
        config.Cdm.console_url.rstrip('/') + '/api/open/query/syncQuery',
        data=json.dumps(body).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            **openapi_signer.build_headers(ak, sk),
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        detail = ''
        try:
            detail = error.read().decode('utf-8', errors='replace')[:300]
        except Exception:  # noqa: BLE001
            pass
        raise ApiError(
            code=-500,
            user_message=f'syncQuery 调用失败（HTTP {error.code}）',
            message=detail or str(error),
            http_status=502,
        ) from error
    except urllib.error.URLError as error:
        raise ApiError(
            code=-500,
            user_message='无法访问 CloudDM 服务',
            message=f'console unreachable: {error.reason}',
            http_status=502,
        ) from error
    except json.JSONDecodeError as error:
        raise ApiError(
            code=-500, user_message='syncQuery 响应异常',
            message=f'invalid json: {error}', http_status=502,
        ) from error

    if str(payload.get('code')) != '1':
        raise ApiError(
            code=-500,
            user_message=f"SQL 执行失败：{payload.get('msg') or '未知错误'}",
            message=f'syncQuery rejected: {str(payload)[:300]}',
            http_status=502,
        )
    return _extract(payload.get('data'))


def _extract(result: dict) -> tuple[list[str], list[list]]:
    """DmApiQueryResultVO → (columnList, rows 值矩阵)，行数截断保护。

    queryType=RequestQuery 的正常响应必含 ResultSetMeta 消息（columnList/receiveMode）；
    columnList 为 null 说明查询没真正执行（消息流被错误打断，如 sidecar 会话池满：
    "exceed session max pool size"）。此时必须报错——静默当 0 行会把执行失败
    伪装成"无主键/未找到稳定行"这类错误结论。
    """
    if not isinstance(result, dict):
        result = {}
    if result.get('columnList') is None:
        error_text = _first_error_message(result.get('msgList'))
        if not error_text:
            error_text = '服务端未返回结果集'
        raise ApiError(
            code=-500,
            user_message=f'SQL 未执行成功：{error_text}',
            message=f'syncQuery no result meta: {str(result)[:300]}',
            http_status=502,
        )
    columns = [str(col) for col in (result.get('columnList') or [])]
    rows: list[list] = []
    raw_rows = result.get('rows') or []
    for row in raw_rows[:_ROW_LIMIT]:
        values = row.get('data') or [] if isinstance(row, dict) else []
        rows.append([_cell(value) for value in values])
    if len(raw_rows) > _ROW_LIMIT:
        logger.warning('[dmops] syncQuery rows truncated %d -> %d', len(raw_rows), _ROW_LIMIT)
    return columns, rows


def _first_error_message(msg_list) -> str:
    """msgList 里取第一条 Error 级消息文本（sidecar 真实错误，含池满/网络等）。"""
    if not isinstance(msg_list, list):
        return ''
    for msg in msg_list:
        if not isinstance(msg, dict):
            continue
        for entity in msg.get('entities') or []:
            if isinstance(entity, dict) and entity.get('level') in ('Error', 'Warn'):
                return str(entity.get('message') or '')
    return ''


def _cell(value):
    if isinstance(value, dict):
        return value.get('value')
    return value
