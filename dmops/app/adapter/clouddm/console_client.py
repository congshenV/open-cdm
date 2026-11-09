"""console 页面接口 HTTP 客户端（JWT 透传）。

只承载 connectDs / addDs 两个数据源接口的调用，认证用调用方（演练详情页）
浏览器随请求带来的 dm_jwt_token（JwtManager 24h 有效；401 语义即登录态过期，
由上层转成"刷新页面重试"提示）。
"""

import json
import logging
import urllib.request

from app import config
from app.util.errors import ApiError

logger = logging.getLogger(__name__)

# console 返回体信封：{code, msg, data,...}，code == "1" 为成功。
_CODE_SUCCESS = '1'


def _console_url(path: str) -> str:
    base = config.Cdm.console_url.rstrip('/')
    return base + path


def _post(path: str, jwt_token: str, body: dict, timeout: int = 30) -> dict:
    """POST JSON 并解包 console 信封；HTTP/信封失败抛 ApiError。"""
    req = urllib.request.Request(
        _console_url(path),
        data=json.dumps(body).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            # console JwtService.verify 取值顺序：query dm_jwt_token → header → Cookie。
            'dm_jwt_token': jwt_token,
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        detail = ''
        try:
            detail = error.read().decode('utf-8', errors='replace')[:300]
        except Exception:  # noqa: BLE001 - 读错误体失败时忽略细节
            pass
        if error.code == 401:
            raise ApiError(
                code=-401,
                user_message='CloudDM 登录态已过期，请刷新页面后重试',
                message=f'console rejected jwt token: {detail}',
                http_status=401,
            ) from error
        raise ApiError(
            code=-500,
            user_message=f'调用 CloudDM 接口失败（HTTP {error.code}）',
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
            code=-500,
            user_message='CloudDM 接口响应异常',
            message=f'invalid json from console: {error}',
            http_status=502,
        ) from error

    if not isinstance(payload, dict):
        raise ApiError(
            code=-500,
            user_message='CloudDM 接口响应异常',
            message=f'unexpected console payload: {str(payload)[:200]}',
            http_status=502,
        )
    return payload


def _unwrap(payload: dict, action: str) -> dict | None:
    """解 console 信封：code!=1 或 HTTP 层非 200 信封失败 → ApiError。"""
    if str(payload.get('code')) != _CODE_SUCCESS:
        raise ApiError(
            code=-500,
            user_message=f'CloudDM {action} 失败：{payload.get("msg") or "未知错误"}',
            message=f'console {action} rejected: {payload}',
            http_status=502,
        )
    return payload.get('data')


def connect_ds(jwt_token: str, body: dict) -> None:
    """连接测试（connectDs）。失败时抛 ApiError（userMessage 即服务端失败原因）。"""
    payload = _post('/api/entry/datasource/connectDs', jwt_token, body)
    data = _unwrap(payload, '连接测试')
    if not isinstance(data, dict) or data.get('success') is not True:
        reason = (data or {}).get('message') if isinstance(data, dict) else ''
        raise ApiError(
            code=-500,
            user_message=f'连接测试失败：{reason or "服务端未返回原因"}',
            message=f'connectDs failed: {data}',
            http_status=502,
        )


def add_ds(jwt_token: str, body: dict) -> int:
    """录入数据源（addDs），成功返回新数据源 dsId。"""
    payload = _post('/api/entry/datasource/addDs', jwt_token, body)
    ds_id = _unwrap(payload, '录入数据源')
    if not isinstance(ds_id, int):
        raise ApiError(
            code=-500,
            user_message='CloudDM 未返回数据源 ID',
            message=f'addDs unexpected data: {ds_id!r:.200}',
            http_status=502,
        )
    return ds_id
