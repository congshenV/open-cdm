"""备份恢复演练（一期：克隆链路）。

发起 → 参数检测 → 落 pending → worker 提交克隆 → 轮询 Running → success/failed。
数据校验与注册数据源在二期，本模块不涉及 CloudDM 的表与 syncQuery。
"""

import datetime
import json
import logging
import re
import time

from app import config
from app.adapter.aliyun import client as client_factory
from app.adapter.aliyun import errors, rds
from app.adapter.clouddm import console_client
from app.adapter.clouddm import query_client
from app.infra import backup_drill_repository as drill_repo
from app.infra import cdm_meta_repository as cdm_meta_repo
from app.infra import (
    cloud_account_repository as account_repo,
    cloud_credential_repository as credential_repo,
    config_repository as config_repo,
    resource_repository as resource_repo,
)
from app.infra.db import get_engine
from app.util.convert import clean_str, parse_cloud_time, parse_cloud_time_local, time_to_str
from app.util.errors import ApiError
from app.util.web import response
from app.util.web.request_scope import get_current_uid

logger = logging.getLogger(__name__)

# 备份集可用性：DescribeBackups 的 IsAvail，1 = 可恢复。
_BACKUP_AVAILABLE = 1


def preflight(account_id: int, region: str, instance_id: str) -> dict:
    """发起弹窗前置检查：实时取实例详情与备份集归属，组装克隆参数预览。

    返回 clone_params 预览（§2.1 A 表字段）+ 通过/未通过的一期检测项；
    数据源绑定（CloudDM dm_ds）二期加。
    """
    attribute = _describe_source_instance(account_id, region, instance_id)

    checks = _run_checks(account_id, region, instance_id, attribute)
    return {
        'account_id': account_id,
        'region': region,
        'instance_id': instance_id,
        'instance_name': attribute.dbinstance_description or '',
        'clone_params_preview': _clone_params_preview(attribute),
        # 预览号：只读推算不落库，供弹窗预填 drill-{drill_no}；发起时事务内重新取号，
        # 与预览号可能不同（并发取号时），前端提交模板原值时以事务内真号为准。
        'next_drill_no': _peek_next_drill_no(),
        'checks': checks,
        'passed': all(item['passed'] for item in checks.values()),
    }


def create_drill(body: dict) -> dict:
    """发起演练：完整参数检测通过后落 pending，返回 drill_no。

    并发约束（全局 + 同实例）在落库事务内复查，避免检测与写入窗口间插入新演练。
    """
    account_id = _body_int(body, 'account_id')
    region = clean_str(body.get('region'))
    instance_id = clean_str(body.get('instance_id'))
    backup_id = clean_str(body.get('backup_id'))

    if not account_id or not region or not instance_id or not backup_id:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '缺少 account_id / region / instance_id / backup_id',
            'missing required fields for creating drill',
            400,
        )

    _require_account(account_id)
    _require_credential(account_id)
    attribute = _describe_source_instance(account_id, region, instance_id)
    backup = _describe_backup(account_id, region, instance_id, backup_id)

    # 参数检测（§2.3 一期 4 项），任一不过直接拒绝，错误信息逐项返回。
    failures = _preflight_failures(account_id, instance_id, attribute, backup)
    if failures:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '；'.join(failures),
            f'preflight failed: {failures}',
            400,
        )

    # 一期用户可编辑项只有名称/描述，名称按模板生成（drill-{drill_no}），
    # 描述默认 {源实例名} 备份恢复演练 {backup_id}；描述若由前端传入则优先。
    triggered_by = get_current_uid() or 'unknown'
    drill = {
        'account_id': account_id,
        'region': region,
        'source_instance_id': instance_id,
        'backup_id': backup_id,
        # 备份时间存本地时间（+8）——与 _now/前端展示同口径（曾因存 UTC 与弹窗差 8 小时）。
        'backup_start_time': parse_cloud_time_local(backup.get('backup_start_time')),
        'backup_end_time': parse_cloud_time_local(backup.get('backup_end_time')),
        # drill_no 在事务内取号后补进 JSON（名称模板引用它），先占位。
        'clone_params': '',
        'target_tables': None,
        'status': drill_repo.STATUS_PENDING,
        'triggered_by': triggered_by,
        'clone_started_at': None,
    }

    user_description = clean_str(body.get('instance_description'))
    prefilled_no = clean_str(body.get('prefilled_drill_no'))
    with get_engine().begin() as conn:
        _assert_concurrency(conn, account_id, instance_id)
        drill_no = drill_repo.next_drill_no(conn)
        drill['drill_no'] = drill_no
        # 弹窗预填模板值（drill-{预览号}）原样提交时以事务内真号重新生成，
        # 避免预览号与真号不一致（并发取号窗口）；用户改过则用用户的值。
        if not user_description or user_description == f'drill-{prefilled_no}':
            description = f'drill-{drill_no}'
        else:
            description = user_description
        if not _valid_description(description):
            raise ApiError(
                response.CODE_BAD_REQUEST,
                '实例名称需字母或中文开头，2~255 字符，且不能以 http 开头',
                f'invalid dbinstance_description: {description!r}',
                400,
            )
        drill['clone_params'] = json.dumps({
            'dbinstance_description': description,
            'source_instance_name': attribute.dbinstance_description or '',
            'backup_type': backup.get('backup_type') or '',
            # 报告口径的源/克隆实例描述要素（发起时已知）。
            'source_engine': f'{attribute.engine or ""} {attribute.engine_version or ""}'.strip(),
            'clone_pay_type': _clone_pay_type_label(attribute),
            'clone_class_desc': _clone_class_desc(attribute),
        }, ensure_ascii=False)
        drill_id = drill_repo.insert_drill(conn, drill)

    logger.info(
        '[dmops] drill created id=%s drill_no=%s instance=%s backup=%s by=%s',
        drill_id, drill_no, instance_id, backup_id, triggered_by,
    )
    return {'id': drill_id, 'drill_no': drill_no}


def cancel_drill(drill_id: int) -> dict:
    """取消演练：仅 pending（克隆请求未发出）可取消。"""
    drill = drill_repo.get_drill(drill_id)
    if drill is None:
        raise ApiError(response.CODE_NOT_FOUND, '演练不存在', f'drill not found: {drill_id}', 404)
    if drill['status'] != drill_repo.STATUS_PENDING:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '克隆请求已发出，不能取消',
            f'drill {drill_id} is {drill["status"]}, cancel only allowed in pending',
            400,
        )
    if not drill_repo.cancel_drill(drill_id):
        raise ApiError(
            response.CODE_CONFLICT,
            '演练状态已变化，取消失败',
            f'drill {drill_id} status changed concurrently',
            409,
        )
    logger.info('[dmops] drill canceled id=%s by=%s', drill_id, get_current_uid() or 'unknown')
    return {'id': drill_id, 'status': drill_repo.STATUS_CANCELED}


def confirm_offline(drill_id: int) -> dict:
    """确认下线：克隆实例已人工释放。"""
    drill = drill_repo.get_drill(drill_id)
    if drill is None:
        raise ApiError(response.CODE_NOT_FOUND, '演练不存在', f'drill not found: {drill_id}', 404)
    if not drill.get('clone_instance_id'):
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '该演练未产生克隆实例，无需确认下线',
            f'drill {drill_id} has no clone instance',
            400,
        )
    if not drill_repo.confirm_offline(drill_id, get_current_uid() or 'unknown'):
        raise ApiError(
            response.CODE_CONFLICT,
            '该演练已确认过下线',
            f'drill {drill_id} offline already confirmed',
            409,
        )
    return {'id': drill_id, 'offline_status': 1}


def get_drill(drill_id: int) -> dict:
    drill = drill_repo.get_drill(drill_id)
    if drill is None:
        raise ApiError(response.CODE_NOT_FOUND, '演练不存在', f'drill not found: {drill_id}', 404)
    step_counts = drill_repo.count_steps_by_drills([drill_id]).get(drill_id, {})
    return _drill_item(drill, step_counts)


# ---------------------------------------------------------------------------
# 注册数据源（源端/克隆实例，§3.3 v8：JWT 透传调 console 接口）。
# ---------------------------------------------------------------------------

# 引擎 → dsType/端口/驱动 映射（dsType 是 console DataSourceType 枚举名，大小写敏感；
# 驱动族/版本来自插件 drivers.xml，与 silicon-db-tools/clouddm_add_ds.py 口径一致）。
_ENGINE_DS_TYPES = {
    'mysql': {
        'ds_type': 'MySQL',
        'port': '3306',
        'driver_family': 'MySQL Connector/J',
        'driver_version': '8.4.0',
    },
    'postgresql': {
        'ds_type': 'PostgreSQL',
        'port': '5432',
        'driver_family': 'PostgreSQL JDBC',
        'driver_version': '42.7.10',
    },
}


def register_ds_prefill(drill_id: int, target: str) -> dict:
    """注册弹窗预填：目标实例的连接地址/端口/引擎映射与默认描述 + 默认账号密码。

    target: 'source'（源实例，ops_resource 快照）或 'clone'（克隆实例，实时查阿里云——
    一期克隆 Running 后连接地址未落库，只能现查）。
    账号密码默认值来自配置管理 rds_default_u_p（JSON {user, passwd}，明文配置），
    与 get_config 明文回填的既有安全水位一致；配置缺失时留空由用户手填。
    """
    _require_valid_target(target)
    drill = _require_drill(drill_id)
    _assert_registerable(drill, target)

    account_id = drill['account_id']
    region = drill['region']
    if target == 'source':
        resource = resource_repo.get_resource(account_id, region, drill['source_instance_id'])
        if resource is None or not resource.get('connection_string'):
            raise ApiError(
                response.CODE_NOT_FOUND,
                '源实例连接地址缺失，请先在实例列表同步该实例',
                f'source connection_string missing for {drill["source_instance_id"]}',
                404,
            )
        host = resource['connection_string']
        # mic 命名：地区/实例等级/实例名（level 缺省回落 S1，实例名为业务名）。
        level = clean_str(resource.get('level')) or 'S1'
        instance_desc = f"{region}/{level}/{resource.get('instance_name') or drill['source_instance_id']}"
    else:
        clone_attribute = _describe_clone_instance(drill)
        host = (clone_attribute.connection_string or '').strip() if clone_attribute else ''
        if not host:
            raise ApiError(
                response.CODE_NOT_FOUND,
                '克隆实例连接地址尚未生成，请稍后重试',
                f'clone connection_string missing for {drill["clone_instance_id"]}',
                404,
            )
        # 克隆实例等级承接源实例（克隆是演练副本，等级语义跟随源）；等级未知回落 S1。
        source_resource = resource_repo.get_resource(account_id, region, drill['source_instance_id']) or {}
        level = clean_str(source_resource.get('level')) or 'S1'
        source_name = source_resource.get('instance_name') or drill['source_instance_id']
        instance_desc = f"{region}/{level}/{source_name}-drill"

    engine = ((resource or {}).get('engine') if target == 'source' else (clone_attribute.engine or '')) or ''
    ds_type = _ENGINE_DS_TYPES.get(engine.lower())
    if ds_type is None:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            f'暂不支持的引擎类型：{engine or "未知"}',
            f'unsupported engine for datasource: {engine!r}',
            400,
        )

    default_user, default_passwd = _default_rds_credentials()
    clusters = cdm_meta_repo.list_clusters()
    envs = cdm_meta_repo.list_envs()
    # 集群默认选清单第一项（现网通常只有一个默认集群）；清单为空才回落 dmops 配置。
    default_cluster = clusters[0]['id'] if clusters else config.Cdm.cluster_id
    return {
        'target': target,
        'host': host,
        'port': ds_type['port'],
        'ds_type': ds_type['ds_type'],
        'driver_family': ds_type['driver_family'],
        'driver_version': ds_type['driver_version'],
        'instance_desc': instance_desc,
        'username': default_user,
        'password': default_passwd,
        # 已存在同 host 数据源时提示复用（提交时也会以此为准，不再重复创建）。
        'existing_ds': cdm_meta_repo.find_alive_ds_by_host(host, ds_type['port']),
        # 集群/环境可编辑：选项直读 CloudDM 表（cdm_meta_repository 例外登记）。
        'clusters': clusters,
        'envs': envs,
        'cluster_id': default_cluster,
        'env_id': config.Cdm.env_id,
    }


def register_ds_test(drill_id: int, target: str, body: dict) -> dict:
    """注册弹窗的「测试连接」：connectDs 真实建连，不产生任何落库。"""
    _require_valid_target(target)
    drill = _require_drill(drill_id)
    _assert_registerable(drill, target)

    jwt_token = _current_jwt_token()
    console_client.connect_ds(jwt_token, _build_ds_config_body(drill, target, body))
    return {'tested': True}


def register_ds_submit(drill_id: int, target: str, body: dict) -> dict:
    """注册弹窗的「提交新增」：再验证一次 connectDs，查重后 addDs 或复用，dsId 回写。

    提交前重测而非信任前端"已测试"状态——表单在测试后可能被改动。
    查重：按连接地址等值查 dm_ds（cdm_meta_repository 例外登记），已存在未删除的
    数据源直接复用其 dsId，不重复创建——源实例本来就录入过 CloudDM 是常见形态。
    """
    _require_valid_target(target)
    drill = _require_drill(drill_id)
    _assert_registerable(drill, target)

    jwt_token = _current_jwt_token()
    ds_body = _build_ds_config_body(drill, target, body)
    env_id = _body_int(body, 'env_id') or config.Cdm.env_id
    instance_desc = clean_str(body.get('instance_desc')) or f"drill-{drill['drill_no']}-{target}"
    console_client.connect_ds(jwt_token, ds_body)

    existing = cdm_meta_repo.find_alive_ds_by_host(
        ds_body['configMap']['address'], ds_body['configMap']['port'],
    )
    if existing:
        ds_id = int(existing['id'])
        reused = True
        logger.info(
            '[dmops] drill %s register %s reused existing ds_id=%s (host already exists)',
            drill_id, target, ds_id,
        )
    else:
        ds_id = console_client.add_ds(jwt_token, _build_add_ds_body(instance_desc, ds_body, env_id))
        reused = False

    with get_engine().begin() as conn:
        drill_repo.update_ds_id(conn, drill_id, target, ds_id)
    logger.info(
        '[dmops] drill %s registered %s ds_id=%s reused=%s by=%s',
        drill_id, target, ds_id, reused, get_current_uid() or 'unknown',
    )
    return {'id': drill_id, 'target': target, 'ds_id': ds_id, 'reused': reused}


def _require_drill(drill_id: int) -> dict:
    drill = drill_repo.get_drill(drill_id)
    if drill is None:
        raise ApiError(response.CODE_NOT_FOUND, '演练不存在', f'drill not found: {drill_id}', 404)
    return drill


def _require_valid_target(target: str) -> None:
    if target not in ('source', 'clone'):
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '注册目标必须是 source 或 clone',
            f'invalid register target: {target!r}',
            400,
        )


# 配置管理里 RDS 默认账号密码的键（JSON {user, passwd}）。
_DEFAULT_RDS_CREDENTIAL_KEY = 'rds_default_u_p'


# ---------------------------------------------------------------------------
# 数据校验（半自动）：§4.1 库名 + 每库表数量对比。触发即追加一条 step 记录。
# ---------------------------------------------------------------------------

# §4.1 的元数据聚合 SQL（两侧同名执行）。
_DB_TABLE_COUNT_SQL = '''
SELECT table_schema AS db_name,
       COUNT(*) AS table_count,
       SUM(data_length + index_length) AS data_bytes
FROM information_schema.tables
WHERE table_schema NOT IN ('mysql','sys','information_schema','performance_schema','__recycle_bin__')
GROUP BY table_schema
ORDER BY table_schema
'''.strip()


def verify_db_tables(drill_id: int) -> dict:
    """库名集合 + 每库表数量对比（手动触发，结果追加进 steps/diffs）。

    前提：源端与克隆端数据源均已注册（dsId 落库）。对比走 AK/SK 的 syncQuery
    （手动触发但用服务身份——SQL 执行不依赖用户会话，且后续行级校验要进 worker）。
    """
    drill = _require_drill(drill_id)
    source_ds_id = drill.get('source_ds_id')
    clone_ds_id = drill.get('clone_ds_id')
    if not source_ds_id or not clone_ds_id:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '请先完成源端与克隆端的数据源注册',
            f'drill {drill_id} missing ds registration: source={source_ds_id} clone={clone_ds_id}',
            400,
        )

    started = time.monotonic()
    source_rows = _query_ds_meta(source_ds_id)
    clone_rows = _query_ds_meta(clone_ds_id)
    diffs = _diff_db_tables(source_rows, clone_rows)

    cost_ms = int((time.monotonic() - started) * 1000)
    source_map = {row['db_name']: row for row in source_rows}
    clone_map = {row['db_name']: row for row in clone_rows}
    status = 'pass' if not diffs else 'warn'
    summary = json.dumps({
        'source_dbs': len(source_map),
        'clone_dbs': len(clone_map),
        'diff_count': len(diffs),
        # AUTO 层 diff 只记录不判定（§4.1：备份后业务变更同样产生差异，无法区分）。
        'judge': 'record_only',
    }, ensure_ascii=False)
    # detail 保存两侧库清单（按库名字符排序），供前端展示库列表。
    detail = json.dumps({
        'source': [
            {'db': db, 'tables': source_map[db]['table_count']}
            for db in sorted(source_map)
        ],
        'clone': [
            {'db': db, 'tables': clone_map[db]['table_count']}
            for db in sorted(clone_map)
        ],
    }, ensure_ascii=False)

    with get_engine().begin() as conn:
        step_id = drill_repo.insert_step(conn, {
            'drill_id': drill_id,
            'layer': 'AUTO',
            'target': 'ALL',
            'status': status,
            'summary': summary,
            'detail': detail,
            'error': None,
            'cost_ms': cost_ms,
        })
        drill_repo.insert_diffs(conn, [
            {
                'drill_id': drill_id,
                'step_id': step_id,
                'layer': 'AUTO',
                'item_type': item['item_type'],
                'target': item['target'],
                'attempt_no': None,
                'status': 'warn',
                'source_value': item['source_value'],
                'clone_value': item['clone_value'],
                'note': item['note'],
            }
            for item in diffs
        ])

    logger.info(
        '[dmops] drill %s verify db-tables done step=%s diffs=%d cost=%dms by=%s',
        drill_id, step_id, len(diffs), cost_ms, get_current_uid() or 'unknown',
    )
    return {'step_id': step_id, 'status': status, 'diff_count': len(diffs)}


def list_verifications(drill_id: int) -> dict:
    """校验历史，最近在前。

    AUTO step 独立成条；ROW step 按批次（detail 里的 batch_id）合并为一组——
    后端逐表落库，展示层聚合为"一次触发一张汇总表"。
    """
    _require_drill(drill_id)
    steps = drill_repo.list_steps(drill_id)
    diffs = drill_repo.list_diffs(drill_id)
    diffs_by_step: dict[int, list[dict]] = {}
    for diff in diffs:
        diffs_by_step.setdefault(diff['step_id'], []).append(diff)

    items = []
    row_batches: dict[str, dict] = {}
    for step in steps:
        if step['layer'] == 'AUTO':
            items.append({
                'id': step['id'],
                'layer': 'AUTO',
                'target': step['target'],
                'status': step['status'],
                'cost_ms': step['cost_ms'],
                'created_at': time_to_str(step['created_at']),
                'summary': _safe_json(step['summary']),
                'source_dbs': _safe_json_detail_list(step['detail'], 'source'),
                'clone_dbs': _safe_json_detail_list(step['detail'], 'clone'),
                'error': step['error'] or '',
                'diffs': diffs_by_step.get(step['id'], []),
            })
            continue

        # ROW：按 batch_id 聚合（steps 已是最新在前，批次内保持触发顺序）。
        batch_id = str(step.get('detail') or step['id'])
        summary = _safe_json(step['summary'])
        tables_entry = {
            'table': step['target'],
            'status': step['status'],
            'note': summary.get('note') or '',
        }
        if batch_id in row_batches:
            batch = row_batches[batch_id]
            batch['tables'].insert(0, tables_entry)
            batch['total_ms'] = (batch['total_ms'] or 0) + (step['cost_ms'] or 0)
            batch['passed'] += 1 if step['status'] == 'pass' else 0
            batch['total'] += 1
            # 组状态取"最差"：任一 fail 即 fail，否则任一 skip 即 skip。
            if step['status'] == 'fail':
                batch['status'] = 'fail'
            elif batch['status'] != 'fail' and step['status'] == 'skip':
                batch['status'] = 'skip'
        else:
            row_batches[batch_id] = {
                'id': step['id'],
                'layer': 'ROW-BATCH',
                'status': step['status'],
                'cost_ms': None,
                'total_ms': step['cost_ms'] or 0,
                'passed': 1 if step['status'] == 'pass' else 0,
                'total': 1,
                'created_at': time_to_str(step['created_at']),
                'tables': [tables_entry],
                'summary': {},
                'error': step['error'] or '',
                'diffs': [],
            }
            items.append(row_batches[batch_id])

    # AUTO 与 ROW 批次混合时按时间重排（items 内已是最新在前，稳定排序保持批次相对序）。
    items.sort(key=lambda item: item['created_at'] or '', reverse=True)
    return {'items': items}


# ---------------------------------------------------------------------------
# 表数据校验（§4.2）：drill-tables 选表辅助 + 行级对比引擎。
# ---------------------------------------------------------------------------

# MySQL：直接查 information_schema（extra 列含 on update CURRENT_TIMESTAMP）。
_TABLE_META_SQL_MYSQL = '''
SELECT t.table_schema AS db_name,
       t.table_name AS table_name,
       CASE WHEN k.column_name IS NOT NULL THEN 1 ELSE 0 END AS has_pk,
       CASE WHEN u.index_name IS NOT NULL THEN 1 ELSE 0 END AS has_unique,
       CASE WHEN c.column_name IS NOT NULL THEN 1 ELSE 0 END AS has_auto_update
FROM information_schema.tables t
LEFT JOIN (SELECT DISTINCT table_schema, table_name, column_name
           FROM information_schema.key_column_usage WHERE constraint_name = 'PRIMARY') k
       ON k.table_schema = t.table_schema AND k.table_name = t.table_name
LEFT JOIN (SELECT DISTINCT table_schema, table_name, index_name
           FROM information_schema.statistics WHERE non_unique = 0) u
       ON u.table_schema = t.table_schema AND u.table_name = t.table_name
LEFT JOIN (SELECT DISTINCT table_schema, table_name, column_name
           FROM information_schema.columns
           WHERE extra LIKE '%on update CURRENT_TIMESTAMP%') c
       ON c.table_schema = t.table_schema AND c.table_name = t.table_name
WHERE t.table_schema NOT IN ('mysql','sys','information_schema','performance_schema','__recycle_bin__')
ORDER BY t.table_schema, t.table_name
'''.strip()

# PostgreSQL：无 extra 列，"自动更新列"近似为带默认值的时间类型列
# （准确的 on update 语义靠触发器实现，information_schema 层不可见——降级为仅标注）。
_TABLE_META_SQL_PG = '''
SELECT t.table_schema AS db_name,
       t.table_name AS table_name,
       CASE WHEN k.column_name IS NOT NULL THEN 1 ELSE 0 END AS has_pk,
       CASE WHEN u.index_name IS NOT NULL THEN 1 ELSE 0 END AS has_unique,
       CASE WHEN c.column_name IS NOT NULL THEN 1 ELSE 0 END AS has_time_default
FROM information_schema.tables t
LEFT JOIN (SELECT DISTINCT tc.table_schema, tc.table_name, kcu.column_name
           FROM information_schema.table_constraints tc
           JOIN information_schema.key_column_usage kcu
             ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
           WHERE tc.constraint_type = 'PRIMARY KEY') k
       ON k.table_schema = t.table_schema AND k.table_name = t.table_name
LEFT JOIN (SELECT DISTINCT schemaname AS table_schema, tablename AS table_name, indexname AS index_name
           FROM pg_indexes
           WHERE indexdef LIKE '%UNIQUE%') u
       ON u.table_schema = t.table_schema AND u.table_name = t.table_name
LEFT JOIN (SELECT DISTINCT table_schema, table_name, column_name
           FROM information_schema.columns
           WHERE data_type LIKE 'timestamp%' AND column_default LIKE '%now()%') c
       ON c.table_schema = t.table_schema AND c.table_name = t.table_name
WHERE t.table_schema NOT IN ('pg_catalog','information_schema')
  AND t.table_schema NOT LIKE 'pg_temp%'
ORDER BY t.table_schema, t.table_name
'''.strip()


def drill_tables(drill_id: int) -> dict:
    """选表辅助：源端实例的全部候选表及主键/唯一索引/自动更新列标注。

    数据取源端（克隆是备份快照，schema 结构一致）。万级表全量返回——
    过滤/搜索在前端做（纯字符串匹配），接口不做关键字参数（§P3 前置说明的口径）。
    """
    drill = _require_drill(drill_id)
    source_ds_id = drill.get('source_ds_id')
    if not source_ds_id:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '请先完成源端数据源注册',
            f'drill {drill_id} missing source ds registration',
            400,
        )

    engine = _drill_engine_type(drill['account_id'], drill['region'], drill['source_instance_id'])
    sql = _TABLE_META_SQL_MYSQL if engine == 'mysql' else _TABLE_META_SQL_PG
    _columns, rows = query_client.execute_query(source_ds_id, _ds_env_id(source_ds_id), 'information_schema', sql)

    items = []
    for row in rows:
        items.append({
            'db': str(row[0]),
            'table': str(row[1]),
            'has_pk': _to_int(row[2]) == 1,
            'has_unique': _to_int(row[3]) == 1,
            'has_auto_update': _to_int(row[4]) == 1,
        })
    # 排序保证前端展示稳定；同一表可能因多索引 JOIN 出多行，按 db+table 去重（保留任一行的标注）。
    seen: dict[str, dict] = {}
    for item in items:
        key = f'{item["db"]}.{item["table"]}'
        seen.setdefault(key, item)
    items = sorted(seen.values(), key=lambda x: (x['db'], x['table']))
    return {'items': items, 'total': len(items)}


def _drill_engine_type(account_id: int, region: str, instance_id: str) -> str:
    """演练源实例的引擎类型（小写），决定元数据 SQL 方言。"""
    resource = resource_repo.get_resource(account_id, region, instance_id)
    engine = ((resource or {}).get('engine') or '').lower()
    if engine not in ('mysql', 'postgresql'):
        raise ApiError(
            response.CODE_BAD_REQUEST,
            f'暂不支持的引擎类型：{engine or "未知"}',
            f'unsupported engine for table verification: {engine!r}',
            400,
        )
    return engine


def _query_ds_meta(ds_id: int) -> list[dict]:
    """对一个数据源执行 §4.1 元数据 SQL，返回 [{db_name, table_count, data_bytes}]。

    envId 取自 dm_ds.ds_env_id（注册时用户选择的环境已落库）——AK 账号需有
    数据源全局查询授权（checkDsAuth 链路，见设计文档 §3.3）。
    """
    env_id = _ds_env_id(ds_id)
    _columns, rows = query_client.execute_query(ds_id, env_id, 'information_schema', _DB_TABLE_COUNT_SQL)
    result = []
    for row in rows:
        result.append({
            'db_name': str(row[0]),
            'table_count': _to_int(row[1]),
            'data_bytes': _to_int(row[2]),
        })
    return result


def _ds_env_id(ds_id: int) -> int:
    """数据源的环境 ID（dm_ds.ds_env_id，同库直读）。"""
    from sqlalchemy import text as sql_text

    with get_engine().connect() as conn:
        row = conn.execute(
            sql_text('SELECT ds_env_id FROM dm_ds WHERE id = :id'),
            {'id': ds_id},
        ).first()
    if row is None or row[0] is None:
        raise ApiError(
            response.CODE_NOT_FOUND,
            f'数据源 {ds_id} 不存在或未配置环境',
            f'dm_ds {ds_id} missing ds_env_id',
            404,
        )
    return int(row[0])


def _diff_db_tables(source_rows: list[dict], clone_rows: list[dict]) -> list[dict]:
    """集合 diff：缺失库 / 多余库 / 表数量不等。差异 note 标注可能为备份后变更。"""
    source_map = {row['db_name']: row for row in source_rows}
    clone_map = {row['db_name']: row for row in clone_rows}
    diffs: list[dict] = []

    for db in sorted(source_map.keys() - clone_map.keys()):
        diffs.append({
            'item_type': 'db_missing',
            'target': db,
            'source_value': f"{source_map[db]['table_count']} tables",
            'clone_value': '-',
            'note': '克隆侧缺失该库（可能为备份后源端新建）',
        })
    for db in sorted(clone_map.keys() - source_map.keys()):
        diffs.append({
            'item_type': 'db_extra',
            'target': db,
            'source_value': '-',
            'clone_value': f"{clone_map[db]['table_count']} tables",
            'note': '源侧缺失该库（可能为备份后源端删除）',
        })
    for db in sorted(source_map.keys() & clone_map.keys()):
        source_count = source_map[db]['table_count']
        clone_count = clone_map[db]['table_count']
        if source_count != clone_count:
            diffs.append({
                'item_type': 'db_table_count',
                'target': db,
                'source_value': str(source_count),
                'clone_value': str(clone_count),
                'note': '表数量不一致（可能为备份后业务变更）',
            })
    return diffs


def verify_table_data(drill_id: int, target_tables: list[str]) -> dict:
    """表数据校验（§4.2，手动触发、同步执行）：逐表稳定行采样 + 两侧点查逐列对比。

    target_tables 形如 ["db.table"]；单次上限 DMOPS_DRILL_MAX_TABLES。
    每表一个 ROW step；每次尝试落一条 diff（row_attempt）。表结果：
    pass / fail（十次全失败）/ skip（无主键/无更新列/无稳定行记 warn-skip）。
    """
    drill = _require_drill(drill_id)
    source_ds_id = drill.get('source_ds_id')
    clone_ds_id = drill.get('clone_ds_id')
    if not source_ds_id or not clone_ds_id:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '请先完成源端与克隆端的数据源注册',
            f'drill {drill_id} missing ds registration',
            400,
        )

    tables = _parse_target_tables(target_tables)
    if not tables:
        raise ApiError(response.CODE_BAD_REQUEST, '请先选定要校验的表', 'target_tables is empty', 400)
    if len(tables) > config.Drill.max_tables:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            f'单次最多校验 {config.Drill.max_tables} 张表',
            f'too many target tables: {len(tables)}',
            400,
        )

    backup_start = drill.get('backup_start_time')
    # 批次号：同一次触发的所有表共用（step.detail 保存，展示层合并为一组）。
    # 毫秒时间戳 + 随机后缀：快速连续触发（同毫秒）不得并批。
    import uuid

    batch_id = f'{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}'
    results = {}
    for name in tables:
        results[name] = _verify_single_table(
            drill, source_ds_id, clone_ds_id, name, backup_start, batch_id,
        )

    passed = sum(1 for item in results.values() if item['status'] == 'pass')
    return {
        'tables': [
            {'table': name, 'status': results[name]['status'], 'note': results[name]['note']}
            for name in tables
        ],
        'passed': passed,
        'total': len(tables),
    }


def _parse_target_tables(target_tables) -> list[str]:
    """db.table 语法校验 + 去重（保持传入顺序）。

    白名单字符集（字母/数字/下划线/美元符/中文）：表名下方直接 f-string 内联进
    反引号标识符，内部反引号等特殊字符会闭合标识符形成注入面——虽然正常路径
    表名来自选表弹窗（服务端返回的真名），该 API 走 console 代理对登录用户开放，
    直调可构造任意输入，必须在边界拦截。
    """
    if not isinstance(target_tables, list):
        return []
    seen: list[str] = []
    for raw in target_tables:
        name = str(raw or '').strip().strip('`')
        if not name:
            continue
        if name.count('.') != 1:
            raise ApiError(
                response.CODE_BAD_REQUEST,
                f'表名格式应为 db.table：{name!r}',
                f'invalid table name: {name!r}',
                400,
            )
        db_name, table_name = name.split('.', 1)
        if not _is_safe_identifier(db_name) or not _is_safe_identifier(table_name):
            raise ApiError(
                response.CODE_BAD_REQUEST,
                f'表名含不支持的字符（仅允许字母、数字、下划线、$、中文）：{name!r}',
                f'unsafe table name: {name!r}',
                400,
            )
        if name not in seen:
            seen.append(name)
    return seen


def _is_safe_identifier(value: str) -> bool:
    return re.fullmatch(r'[A-Za-z0-9_$\u4e00-\u9fa5]+', value) is not None


def _verify_single_table(drill: dict, source_ds_id: int, clone_ds_id: int, name: str, backup_start,
                         batch_id: str) -> dict:
    """单表校验（简化口径）：id 为主键 → MIN(id) 行两侧对比；结果落 ROW step。

    batch_id 标记同一次触发（展示层按批次合并为一张汇总表）。
    """
    db_name, table_name = name.split('.', 1)
    started = time.monotonic()
    status = 'pass'
    note = ''

    try:
        engine = _drill_engine_type(drill['account_id'], drill['region'], drill['source_instance_id'])
        # 前置：id 列存在且为主键（不满足直接提示重选，不进对比）。
        if not _has_id_primary_key(engine, source_ds_id, db_name, table_name):
            status = 'skip'
            note = 'id 列不存在或不是主键，请重选表'
        else:
            status, note = _compare_min_id_row(
                source_ds_id, clone_ds_id, db_name, table_name,
            )
    except ApiError as error:
        status = 'fail'
        note = error.user_message

    cost_ms = int((time.monotonic() - started) * 1000)
    diff_rows = [{
        'drill_id': drill['id'],
        'step_id': 0,  # insert_step 后回填
        'layer': 'ROW',
        'item_type': 'row_attempt',
        'target': name,
        'attempt_no': 1,
        'status': status,
        'source_value': None,
        'clone_value': None,
        'note': note,
    }]

    summary = json.dumps({
        'status': status,
        'note': note,
        'mode': 'min_id_row',
        'batch_id': batch_id,
    }, ensure_ascii=False)
    with get_engine().begin() as conn:
        step_id = drill_repo.insert_step(conn, {
            'drill_id': drill['id'],
            'layer': 'ROW',
            'target': name,
            'status': status,
            'summary': summary,
            'detail': batch_id,
            'error': None,
            'cost_ms': cost_ms,
        })
        for row in diff_rows:
            row['step_id'] = step_id
        drill_repo.insert_diffs(conn, diff_rows)

    return {'status': status, 'note': note}


def _has_id_primary_key(engine: str, ds_id: int, db: str, table: str) -> bool:
    """简化口径前置：表存在 id 列且 id 为主键。"""
    if engine == 'mysql':
        sql = (
            'SELECT COUNT(*) FROM information_schema.key_column_usage '
            "WHERE table_schema = '{db}' AND table_name = '{table}' "
            "AND constraint_name = 'PRIMARY' AND column_name = 'id'"
        ).format(db=db, table=table)
    else:
        sql = (
            'SELECT COUNT(*) FROM information_schema.table_constraints tc '
            'JOIN information_schema.key_column_usage kcu '
            '  ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema '
            "WHERE tc.table_schema = '{db}' AND tc.table_name = '{table}' "
            "AND tc.constraint_type = 'PRIMARY KEY' AND kcu.column_name = 'id'"
        ).format(db=db, table=table)
    _c, rows = query_client.execute_query(ds_id, _ds_env_id(ds_id), 'information_schema', sql)
    return bool(rows) and _to_int(rows[0][0]) == 1


def _compare_min_id_row(source_ds_id: int, clone_ds_id: int, db: str, table: str) -> tuple[str, str]:
    """MIN(id) 行两侧对比：源侧取 MIN(id)，两侧各按该 id 点查全列，逐列比较。

    返回 (status, note)：pass=全列一致（含两侧均为空表）；fail=有差异列/一侧无此行/
    源空克隆非空（可能源表在备份后被清空）。
    """
    min_sql = f'SELECT MIN(`id`) FROM `{db}`.`{table}`'
    _c, min_rows = query_client.execute_query(
        source_ds_id, _ds_env_id(source_ds_id), db, min_sql)
    min_id = min_rows[0][0] if min_rows else None
    if min_id is None:
        # 源侧空表：多查一步克隆侧 COUNT 区分"两侧均空（一致）"与"源被清空（差异）"。
        count_sql = f'SELECT COUNT(*) FROM `{db}`.`{table}`'
        _c, clone_count_rows = query_client.execute_query(
            clone_ds_id, _ds_env_id(clone_ds_id), db, count_sql)
        clone_count = _to_int(clone_count_rows[0][0]) if clone_count_rows else 0
        if clone_count:
            return 'fail', f'源侧表为空，但克隆侧有 {clone_count} 行（可能源表在备份后被清空）'
        return 'pass', '两侧均为空表，对比一致'

    row_sql = f'SELECT * FROM `{db}`.`{table}` WHERE `id` = {_sql_value(min_id)}'
    _c, source_rows = query_client.execute_query(
        source_ds_id, _ds_env_id(source_ds_id), db, row_sql)
    _c, clone_rows = query_client.execute_query(
        clone_ds_id, _ds_env_id(clone_ds_id), db, row_sql)
    if not source_rows:
        return 'fail', '源侧 MIN(id) 行点查无结果'
    if not clone_rows:
        return 'fail', f'克隆侧无 id={min_id} 的行'

    diff_cols = _diff_columns(source_rows[0], clone_rows[0])
    if not diff_cols:
        return 'pass', f'id={min_id} 行对比：全部列一致'
    return 'fail', f'id={min_id} 行存在差异列（脱敏摘要）：{", ".join(diff_cols)}'


def _sql_value(value) -> str:
    """PK 值的内联转义（syncQuery 不支持参数绑定；PK 值来自 information_schema 查询结果，
    非用户输入，转义引号后内联）。"""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def _diff_columns(source_row: list, clone_row: list) -> list[str]:
    """逐列对比（值均来自 JSON 序列化通道，按字符串严格比较；None 与空串视为不等，保留原样）。"""
    length = min(len(source_row), len(clone_row))
    return [f'col#{i}' for i in range(length) if str(source_row[i]) != str(clone_row[i])]


def _safe_json(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _safe_json_detail_list(value: str | None, key: str) -> list[dict]:
    """detail JSON 里取 key 对应的列表（[{db, tables}]），异常/缺失返回空列表。"""
    if not value:
        return []
    try:
        parsed = json.loads(value)
        items = parsed.get(key) if isinstance(parsed, dict) else None
        return items if isinstance(items, list) else []
    except (TypeError, ValueError):
        return []


def _to_int(value):
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _default_rds_credentials() -> tuple[str, str]:
    """从配置管理读 RDS 默认账号密码。

    配置缺失返回空串（用户手填，非错误）；已配置但值不是合法 JSON（如加密存了但
    解密失败拿到密文）时显式报错——静默空白会让用户误以为没配置过。
    """
    row = config_repo.get_by_key(_DEFAULT_RDS_CREDENTIAL_KEY)
    if row is None:
        return '', ''
    value = row.get('config_value') or ''
    if not value:
        return '', ''
    try:
        parsed = json.loads(value)
    except ValueError as error:
        raise ApiError(
            code=-500,
            user_message=f'配置项 {_DEFAULT_RDS_CREDENTIAL_KEY} 值不是合法 JSON（{{"user","passwd"}}），请在配置管理中修正',
            message=f'{_DEFAULT_RDS_CREDENTIAL_KEY} invalid json: {error}',
            http_status=500,
        ) from error
    return clean_str(parsed.get('user')), clean_str(parsed.get('passwd'))


def _assert_registerable(drill: dict, target: str) -> None:
    """注册前提：克隆已完成（克隆端）；未确认下线（实例还活着才有注册意义）。"""
    if drill['status'] != drill_repo.STATUS_SUCCESS:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '克隆完成后才能注册数据源',
            f'drill {drill["id"]} is {drill["status"]}, register requires success',
            400,
        )
    if target == 'clone' and not drill.get('clone_instance_id'):
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '该演练没有克隆实例',
            f'drill {drill["id"]} has no clone instance',
            400,
        )
    if drill.get('offline_status') == 1:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '该演练已确认下线，无需再注册数据源',
            f'drill {drill["id"]} already offline',
            400,
        )


def _current_jwt_token() -> str:
    """从当前请求 Cookie 提取 CloudDM JWT（仅内存传递，不落库不打印）。"""
    from flask import request

    token = request.cookies.get('dm_jwt_token', '')
    if not token:
        raise ApiError(
            code=-401,
            user_message='CloudDM 登录态已过期，请刷新页面后重试',
            message='dm_jwt_token cookie missing',
            http_status=401,
        )
    return token


def _build_ds_config_body(drill: dict, target: str, body: dict) -> dict:
    """connectDs / addDs 共用的 configMap + 顶层字段组装。

    密码等敏感字段仅存在于本次请求内存，不落库。
    集群/环境由弹窗选择传入（prefill 时下发了选项与默认值），为空回落配置默认。
    """
    host = clean_str(body.get('host'))
    port = clean_str(body.get('port'))
    username = clean_str(body.get('username'))
    password = clean_str(body.get('password'))
    driver_family = clean_str(body.get('driver_family'))
    driver_version = clean_str(body.get('driver_version'))
    if not host or not port or not username or not password:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '连接地址、端口、账号、密码均为必填',
            f'missing ds fields for register {target}',
            400,
        )

    engine = clean_str(body.get('engine')).lower()
    ds_type = _ENGINE_DS_TYPES.get(engine)
    if ds_type is None:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            f'暂不支持的引擎类型：{engine or "未知"}',
            f'unsupported engine: {engine!r}',
            400,
        )

    # 驱动项允许前端微调（预填默认值来自 drivers.xml），为空回落引擎默认。
    driver_family = driver_family or ds_type['driver_family']
    driver_version = driver_version or ds_type['driver_version']

    config_map = {
        'address': host,
        'port': port,
        'driverFamily': driver_family,
        'driverVersion': driver_version,
        'securityType': 'USER_PASSWD',
        # console 消费的键名是 Java 字段名 userName（Fields 为
        # @FieldNameConstants 常量），不是 username——写错会被静默忽略，
        # JDBC 用户名为空时回落 sidecar 进程的 OS 用户（曾表现为 'cong'@'x.x.x.x'）。
        'userName': username,
        'password': password,
    }
    cluster_id = _body_int(body, 'cluster_id') or config.Cdm.cluster_id
    return {
        'dsType': ds_type['ds_type'],
        'clusterId': cluster_id,
        'configMap': config_map,
    }


def _build_add_ds_body(instance_desc: str, ds_config_body: dict, env_id: int) -> dict:
    """addDs 请求体：dsId=null（新增），描述默认带 drill_no 便于追溯。"""
    return {
        'dsId': None,
        'dsType': ds_config_body['dsType'],
        'clusterId': ds_config_body['clusterId'],
        'envId': env_id,
        'instanceDesc': instance_desc,
        'configMap': ds_config_body['configMap'],
    }


def _describe_clone_instance(drill: dict):
    """实时查克隆实例详情（注册预填用连接地址与引擎）。"""
    credential = credential_repo.get_credential(drill['account_id'])
    if credential is None or not credential.get('enabled'):
        raise ApiError(response.CODE_BAD_REQUEST, '账号认证缺失或已停用', 'credential missing', 400)
    rds_client = client_factory.get_rds_client(drill['account_id'], credential, drill['region'])
    try:
        return rds.describe_instance_attribute(rds_client, drill['clone_instance_id'])
    except Exception as error:
        raise errors.translate_sdk_error(error, 'DescribeDBInstanceAttribute') from error


def list_drills(account_id: int = 0, instance_id: str = '', status: str = '',
                offline: bool = False, page: int = 1, page_size: int = 20) -> dict:
    rows, total = drill_repo.list_drills(
        account_id=account_id, instance_id=instance_id, status=status,
        offline=offline, page=page, page_size=page_size,
    )
    counts_by_drill = drill_repo.count_steps_by_drills([row['id'] for row in rows])
    return {
        'items': [_drill_item(row, counts_by_drill.get(row['id'])) for row in rows],
        'page': page,
        'page_size': page_size,
        'total': total,
    }


# ---------------------------------------------------------------------------
# worker 编排：克隆提交与轮询。worker 模块调用，请求链路不使用。
# ---------------------------------------------------------------------------

def run_clone_stage(drill: dict) -> None:
    """执行 cloning 阶段：提交克隆（如尚未提交）→ 轮询到 Running / 超时 / 硬错误。

    幂等：clone_instance_id 已落库则跳过提交直接轮询（断点续跑）；
    ClientToken 相同的重复提交由阿里云幂等去重。
    """
    drill_id = drill['id']
    account_id = drill['account_id']
    region = drill['region']

    credential = credential_repo.get_credential(account_id)
    if credential is None or not credential.get('enabled'):
        _finish_failed(drill_id, '账号认证缺失或已停用')
        return
    rds_client = client_factory.get_rds_client(account_id, credential, region)

    if not drill.get('clone_instance_id'):
        clone_instance_id = _submit_clone(rds_client, drill)
        if clone_instance_id is None:
            return  # 提交失败已落终态
        drill['clone_instance_id'] = clone_instance_id
    else:
        clone_instance_id = drill['clone_instance_id']

    _poll_until_running(rds_client, drill, clone_instance_id)


def _submit_clone(rds_client, drill: dict) -> str | None:
    """提交 CloneDBInstance；成功则先落 clone_instance_id 再轮询。失败落终态返回 None。

    源实例规格字段在提交前实时查详情组装（§2.1 A 表），不取发起时的快照——
    避免 pending 排队期间源实例规格变化时带上旧值。
    """
    drill_id = drill['id']
    user_input = json.loads(drill.get('clone_params') or '{}')

    try:
        attribute = _describe_source_instance(
            drill['account_id'], drill['region'], drill['source_instance_id'],
        )
    except ApiError as error:
        _finish_failed(drill_id, f'克隆前查询源实例失败：{error.user_message}')
        return None

    params = {
        'dbinstance_id': drill['source_instance_id'],
        'region_id': drill['region'],
        'zone_id': attribute.zone_id or '',
        'backup_id': drill['backup_id'],
        'backup_type': user_input.get('backup_type') or '',
        'dbinstance_description': user_input.get('dbinstance_description') or '',
        'dbinstance_storage_type': attribute.dbinstance_storage_type or '',
        'instance_network_type': attribute.instance_network_type or '',
        'vpcid': attribute.vpc_id or '',
        'v_switch_id': attribute.v_switch_id or '',
        'client_token': f"drill-{drill['drill_no']}",
        # Serverless 源实例时改为 Serverless 付费并透传 RCU 配置（§2.1-D3）。
        'pay_type': 'Postpaid',
        'serverless_config': None,
    }
    category = (attribute.category or '').lower()
    if category.startswith('serverless'):
        params['pay_type'] = 'Serverless'
        config_value = attribute.serverless_config
        if config_value is not None:
            params['serverless_config'] = {
                # 详情字段 scale_min/scale_max → 请求字段 min_capacity/max_capacity。
                'min_capacity': config_value.scale_min,
                'max_capacity': config_value.scale_max,
                'auto_pause': config_value.auto_pause,
                'switch_force': config_value.switch_force,
            }

    try:
        clone_instance_id, order_id = rds.clone_db_instance(rds_client, params)
    except Exception as error:
        api_error = errors.translate_sdk_error(error, 'CloneDBInstance')
        _finish_failed(drill_id, f'克隆提交失败：{api_error.user_message}')
        return None
    if not clone_instance_id:
        _finish_failed(drill_id, '克隆提交失败：阿里云未返回实例 ID')
        return None

    # 关键顺序：拿到实例 ID 立即落库，之后的失败也能追溯到实例（§2.2）。
    with get_engine().begin() as conn:
        drill_repo.mark_clone_submitted(conn, drill_id, clone_instance_id)
    logger.info(
        '[dmops] drill %s clone submitted instance=%s order=%s',
        drill_id, clone_instance_id, order_id,
    )
    return clone_instance_id


def _poll_until_running(rds_client, drill: dict, clone_instance_id: str) -> None:
    """轮询克隆实例状态至 Running，带心跳与硬错误宽容。"""
    drill_id = drill['id']
    poll_interval = config.Drill.poll_interval_sec
    heartbeat_every = config.Drill.heartbeat_sec
    hard_error_limit = config.Drill.poll_hard_error_limit
    timeout_at = time.monotonic() + config.Drill.clone_timeout_min * 60

    hard_errors = 0
    error_text = ''
    last_heartbeat = 0.0

    while True:
        try:
            attribute = rds.describe_instance_attribute(rds_client, clone_instance_id)
        except Exception as error:
            api_error = errors.translate_sdk_error(error, 'DescribeDBInstanceAttribute')
            hard_errors += 1
            error_text = api_error.user_message
            if hard_errors >= hard_error_limit:
                _finish_failed(
                    drill_id,
                    f'克隆实例状态查询连续失败：{api_error.user_message}',
                )
                return
        else:
            hard_errors = 0
            status = (attribute.dbinstance_status or '').strip() if attribute else ''
            if status == 'Running':
                with get_engine().begin() as conn:
                    drill_repo.finish_drill(conn, drill_id, drill_repo.STATUS_SUCCESS)
                logger.info('[dmops] drill %s clone running instance=%s', drill_id, clone_instance_id)
                return
            logger.info(
                '[dmops] drill %s clone polling instance=%s status=%s hard_errors=%s',
                drill_id, clone_instance_id, status or 'None', hard_errors,
            )

        if time.monotonic() >= timeout_at:
            _finish_failed(
                drill_id,
                f'克隆超时（{config.Drill.clone_timeout_min} 分钟），实例 {clone_instance_id} '
                '可能仍在创建，请在阿里云控制台确认后释放',
            )
            return

        # 心跳节流落库：updated_at 保持新鲜，崩溃后可被重新接管。
        now = time.monotonic()
        if now - last_heartbeat >= heartbeat_every:
            with get_engine().begin() as conn:
                drill_repo.heartbeat(conn, drill_id)
            last_heartbeat = now
        time.sleep(poll_interval)


def _finish_failed(drill_id: int, user_message: str) -> None:
    with get_engine().begin() as conn:
        drill_repo.finish_drill(conn, drill_id, drill_repo.STATUS_FAILED, user_message)
    logger.warning('[dmops] drill %s failed: %s', drill_id, user_message)


# ---------------------------------------------------------------------------
# 检测与参数组装辅助。
# ---------------------------------------------------------------------------

def _run_checks(account_id: int, region: str, instance_id: str, attribute) -> dict:
    """一期 4 项检测，返回 {key: {passed, message}}（preflight 展示用）。"""
    result = {}
    active_global, active_instance = _active_counts(account_id, instance_id)
    concurrency_ok = active_global < config.Drill.max_concurrency and active_instance == 0
    result['concurrency'] = {
        'passed': concurrency_ok,
        'message': '' if concurrency_ok else '已存在进行中的演练（全局或该实例）',
    }
    return result


def _preflight_failures(account_id: int, instance_id: str, attribute, backup: dict) -> list[str]:
    """创建前的一期检测，返回失败项文案列表。

    Serverless 不再拦截（§2.1-D3 修订：CloneDBInstance 原生支持
    PayType=Serverless + ServerlessConfig 透传）。
    """
    failures: list[str] = []

    backup_id = backup.get('backup_id') if backup else None
    is_avail = backup.get('is_avail') if backup else None
    if backup is None or not backup_id:
        failures.append('备份集不存在')
    elif is_avail != _BACKUP_AVAILABLE:
        failures.append('该备份集不可用（IsAvail != 1）')

    active_global, active_instance = _active_counts(account_id, instance_id)
    if active_global >= config.Drill.max_concurrency:
        failures.append('已存在进行中的演练，全局并发已占满')
    if active_instance > 0:
        failures.append('该实例已存在进行中的演练')

    return failures


def _active_counts(account_id: int, instance_id: str) -> tuple[int, int]:
    from app.infra.db import get_engine
    with get_engine().connect() as conn:
        active_global = drill_repo.count_active(conn)
        active_instance = drill_repo.count_active_by_instance(conn, account_id, instance_id)
    return active_global, active_instance


def _assert_concurrency(conn, account_id: int, instance_id: str) -> None:
    """落库事务内复查并发约束，检测通过但写入前被抢先的兜底。"""
    if drill_repo.count_active(conn) >= config.Drill.max_concurrency:
        raise ApiError(
            response.CODE_CONFLICT,
            '已存在进行中的演练，全局并发已占满',
            'drill concurrency limit reached',
            409,
        )
    if drill_repo.count_active_by_instance(conn, account_id, instance_id) > 0:
        raise ApiError(
            response.CODE_CONFLICT,
            '该实例已存在进行中的演练',
            'instance already has an active drill',
            409,
        )


def _describe_source_instance(account_id: int, region: str, instance_id: str):
    """实时查源实例详情（克隆参数来源），失败转统一 ApiError。"""
    _require_account(account_id)
    credential = _require_credential(account_id)
    rds_client = client_factory.get_rds_client(account_id, credential, region)
    try:
        attribute = rds.describe_instance_attribute(rds_client, instance_id)
    except Exception as error:
        raise errors.translate_sdk_error(error, 'DescribeDBInstanceAttribute') from error
    if attribute is None:
        raise ApiError(
            response.CODE_NOT_FOUND,
            '实例不存在',
            f'instance not found: {instance_id}',
            404,
        )
    return attribute


def _describe_backup(account_id: int, region: str, instance_id: str, backup_id: str) -> dict | None:
    """在备份集列表中定位目标备份集（校验归属与可用性），找不到返回 None。"""
    _require_account(account_id)
    credential = _require_credential(account_id)
    rds_client = client_factory.get_rds_client(account_id, credential, region)
    for page_number in range(1, 20):
        try:
            body = rds.describe_backups(rds_client, instance_id, page_number, 100)
        except Exception as error:
            raise errors.translate_sdk_error(error, 'DescribeBackups') from error
        items = body.items.backup if body and body.items else None
        for item in items or []:
            if str(item.backup_id) == str(backup_id):
                return {
                    'backup_id': str(item.backup_id),
                    'backup_type': item.backup_type or '',
                    'is_avail': item.is_avail,
                    'backup_start_time': item.backup_start_time or '',
                    'backup_end_time': item.backup_end_time or '',
                }
        total = int(body.total_record_count or 0) if body else 0
        if page_number * 100 >= total or not items:
            break
    return None


def _clone_params_preview(attribute) -> dict:
    """弹窗预览的克隆参数（§2.1 A 表）。规格类字段只读展示“同源实例”。"""
    if attribute is None:
        return {}

    preview = {
        'zone_id': attribute.zone_id or '',
        'instance_class': attribute.dbinstance_class or '',
        'storage_gb': attribute.dbinstance_storage,
        'storage_type': attribute.dbinstance_storage_type or '',
        'network_type': attribute.instance_network_type or '',
        'vpc_id': attribute.vpc_id or '',
        'vswitch_id': attribute.v_switch_id or '',
        'category': attribute.category or '',
    }

    # Serverless 源实例：付费类型与 RCU 范围是克隆实例的成本决定因素，预览必须可见。
    category = (attribute.category or '').lower()
    if category.startswith('serverless'):
        preview['pay_type'] = 'Serverless'
        config_value = attribute.serverless_config
        if config_value is not None:
            preview['serverless_min_capacity'] = config_value.scale_min
            preview['serverless_max_capacity'] = config_value.scale_max
    else:
        preview['pay_type'] = 'Postpaid'
    return preview


def _peek_next_drill_no() -> str:
    """推算下一条演练编号（只读，不落库），供弹窗预填。"""
    return drill_repo.peek_next_drill_no()


def _clone_pay_type_label(attribute) -> str:
    """克隆实例付费类型描述：Serverless 源注明按 RCU 计费，其余按量付费。"""
    category = (attribute.category or '').lower() if attribute else ''
    if category.startswith('serverless'):
        return 'Serverless（按 RCU 计费）'
    return '按量付费'


def _clone_class_desc(attribute) -> str:
    """克隆实例规格口径描述：Serverless 显示 RCU 范围，其余显示同规格。"""
    if attribute is None:
        return '同规格'
    category = (attribute.category or '').lower()
    if category.startswith('serverless'):
        config_value = attribute.serverless_config
        if config_value is not None and config_value.scale_min is not None:
            return f'RCU {config_value.scale_min} ~ {config_value.scale_max}'
    instance_class = attribute.dbinstance_class or ''
    return f'同规格（{instance_class}）' if instance_class else '同规格'


def _valid_description(value: str) -> bool:
    """DBInstanceDescription 校验：字母或中文开头、2~255 字符、排除 http 前缀。

    字符集按阿里云规则限定：中文、英文字母、数字、下划线、短横线。
    """
    if not value or len(value) < 2 or len(value) > 255:
        return False
    if value.lower().startswith('http'):
        return False
    return re.fullmatch(r'[A-Za-z一-龥][A-Za-z0-9一-龥_\-]*', value) is not None


def _body_int(body: dict, name: str) -> int:
    value = body.get(name)
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError) as error:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            f'参数 {name} 必须是整数',
            f'invalid int field {name}={value!r}',
            400,
        ) from error


def _require_account(account_id: int) -> dict:
    account = account_repo.get_account(account_id)
    if account is None:
        raise ApiError(
            response.CODE_NOT_FOUND, '账号不存在',
            f'account id not found: {account_id}', 404,
        )
    return account


def _require_credential(account_id: int) -> dict:
    credential = credential_repo.get_credential(account_id)
    if credential is None:
        raise ApiError(
            response.CODE_BAD_REQUEST, '账号未配置认证信息',
            f'credential not found for account: {account_id}', 400,
        )
    if not credential.get('enabled'):
        raise ApiError(response.CODE_BAD_REQUEST, '账号认证已停用', 'credential is disabled', 400)
    return credential


def _display_status(row: dict, step_counts: dict[str, int] | None) -> str:
    """演练展示状态（派生，不改数据库 status 枚举）。

    pending/cloning/failed/canceled 原样；success 之后按阶段推进：
    已确认下线 → done（演练完成）；
    库表校验（AUTO）与表数据校验（ROW）均执行过 → verified（数据校验完成）；
    否则 → awaiting_verify（待数据校验）。
    """
    status = row['status']
    if status != 'success':
        return status
    if row.get('offline_status') == 1:
        return 'done'
    counts = step_counts or {}
    if counts.get('AUTO', 0) > 0 and counts.get('ROW', 0) > 0:
        return 'verified'
    return 'awaiting_verify'


def _drill_item(row: dict, step_counts: dict[str, int] | None = None) -> dict:
    """行转接口响应；时间字段统一字符串。报告口径字段从 clone_params JSON 展开。"""
    import datetime

    from app.util.convert import time_to_str
    user_input: dict = {}
    try:
        user_input = json.loads(row.get('clone_params') or '{}')
    except (TypeError, ValueError):
        pass

    created_at = row.get('created_at')
    finished_at = row.get('finished_at')
    total_minutes = None
    if isinstance(created_at, datetime.datetime) and isinstance(finished_at, datetime.datetime):
        total_minutes = round((finished_at - created_at).total_seconds() / 60)

    return {
        'id': row['id'],
        'drill_no': row['drill_no'],
        # 派生展示状态：克隆完成 → 待数据校验 → 数据校验完成 → 演练完成。
        'display_status': _display_status(row, step_counts),
        'account_id': row['account_id'],
        'region': row['region'],
        'status': row['status'],
        'error_message': row['error_message'] or '',
        'triggered_by': row['triggered_by'],
        # 源实例
        'source_instance_id': row['source_instance_id'],
        'source_instance_name': user_input.get('source_instance_name') or '',
        'source_engine': user_input.get('source_engine') or '',
        # 备份集
        'backup_id': row['backup_id'],
        'backup_type': user_input.get('backup_type') or '',
        'backup_start_time': time_to_str(row.get('backup_start_time')),
        'backup_end_time': time_to_str(row.get('backup_end_time')),
        # 克隆实例
        'clone_instance_id': row['clone_instance_id'] or '',
        'clone_instance_name': user_input.get('dbinstance_description') or '',
        'clone_pay_type': user_input.get('clone_pay_type') or '',
        'clone_class_desc': user_input.get('clone_class_desc') or '',
        # 数据源注册状态（半自动注册：dsId 为空即未注册）
        'source_ds_id': row.get('source_ds_id'),
        'clone_ds_id': row.get('clone_ds_id'),
        # 时间线
        'clone_started_at': time_to_str(row['clone_started_at']),
        'clone_finished_at': time_to_str(row['clone_finished_at']),
        'compare_started_at': time_to_str(row.get('compare_started_at')),
        'compare_finished_at': time_to_str(row.get('compare_finished_at')),
        'finished_at': time_to_str(finished_at),
        'total_minutes': total_minutes,
        'created_at': time_to_str(created_at),
        # 下线
        'offline_status': row['offline_status'],
        'offline_confirmed_by': row['offline_confirmed_by'] or '',
    }
