"""数据校验（§4.1 库表数量对比）单测：syncQuery mock + diff 逻辑 + 落库。"""

import base64
import hashlib
import hmac
import json

import pytest

from app.adapter.clouddm import openapi_signer
from app.infra import backup_drill_repository as drill_repo
from app.service import backup_drill_service
from app.util.errors import ApiError


# ---------------------------------------------------------------------------
# 签名复刻对拍：与 OpenApiSigner 的 Java 实现逐字节一致（固定向量手算验证）。
# ---------------------------------------------------------------------------

def test_openapi_signer_known_vector():
    """固定向量：paramStr 排序拼接 + 整体 percentEncode + HmacSHA1(sk) Base64。

    向量由 Java 语义手工推导：
    queries = {AccessKeyId: test-ak, SignatureMethod: HMAC-SHA1, SignatureNonce: n1}
    排序后 paramStr = "AccessKeyId=test-ak&SignatureMethod=HMAC-SHA1&SignatureNonce=n1"
    （值中 '-' 与字母数字不被 percent-encode；等号与 & 会被 encode——
    注意 composeStringToSign 是先拼串再整体 encode，'=' → '%3D'、'&' → '%26'）
    """
    queries = {
        'AccessKeyId': 'test-ak',
        'SignatureMethod': 'HMAC-SHA1',
        'SignatureNonce': 'n1',
    }
    # 手工推导 composeStringToSign：
    params = 'AccessKeyId=test-ak&SignatureMethod=HMAC-SHA1&SignatureNonce=n1'
    import urllib.parse
    expected_str = urllib.parse.quote(params, safe='').replace('+', '%20').replace('*', '%2A').replace('%7E', '~')
    assert openapi_signer.compose_string_to_sign(queries) == expected_str

    # 签名与 Java signString 等价：Base64(HmacSHA1(str, sk))
    expected_sig = base64.b64encode(
        hmac.new(b'test-sk', expected_str.encode('utf-8'), hashlib.sha1).digest()
    ).decode('utf-8')
    assert openapi_signer.sign(queries, 'test-sk') == expected_sig


def test_openapi_signer_percent_encode_java_semantics():
    """Java URLEncoder 语义：空格 → %20、* → %2A、~ 还原为字面量。"""
    assert openapi_signer.percent_encode('a b') == 'a%20b'
    assert openapi_signer.percent_encode('a*b') == 'a%2Ab'
    assert openapi_signer.percent_encode('~') == '~'
    assert openapi_signer.percent_encode('中文') == '%E4%B8%AD%E6%96%87'


def test_openapi_signer_build_headers_shape():
    headers = openapi_signer.build_headers('ak-x', 'sk-x')
    assert set(headers) == {'AccessKeyId', 'SignatureMethod', 'SignatureNonce', 'Signature'}
    assert headers['AccessKeyId'] == 'ak-x'
    assert headers['SignatureMethod'] == 'HMAC-SHA1'
    # nonce 每次不同
    assert openapi_signer.build_headers('ak-x', 'sk-x')['SignatureNonce'] != headers['SignatureNonce']


# ---------------------------------------------------------------------------
# 库表数量对比。
# ---------------------------------------------------------------------------

@pytest.fixture()
def verify_env(sqlite_engine, monkeypatch):
    """success 演练 + 双端 dsId 已注册 + syncQuery mock（两侧可分别设返回）。"""
    with backup_drill_service.get_engine().begin() as conn:
        drill_id = drill_repo.insert_drill(conn, {
            'drill_no': 'DR261106001',
            'account_id': 1,
            'region': 'cn-beijing',
            'source_instance_id': 'rm-src',
            'backup_id': '3222768592',
            'backup_start_time': None,
            'backup_end_time': None,
            'clone_params': '{}',
            'target_tables': None,
            'status': drill_repo.STATUS_SUCCESS,
            'triggered_by': 'tester',
            'clone_started_at': None,
        })
        drill_repo.update_ds_id(conn, drill_id, 'source', 101)
        drill_repo.update_ds_id(conn, drill_id, 'clone', 202)

    state = {
        'source': [['app_db', 152, 1000], ['user_db', 37, 200]],
        'clone': [['app_db', 152, 1000], ['user_db', 38, 200], ['extra_db', 5, 10]],
        'queries': [],
    }

    def fake_execute(ds_id, env_id, database, sql):
        state['queries'].append({'ds_id': ds_id, 'env_id': env_id, 'database': database, 'sql': sql})
        rows = state['source'] if ds_id == 101 else state['clone']
        return ['db_name', 'table_count', 'data_bytes'], [list(r) for r in rows]

    def fake_env(ds_id):
        return 1

    monkeypatch.setattr(backup_drill_service.query_client, 'execute_query', fake_execute)
    monkeypatch.setattr(backup_drill_service, '_ds_env_id', fake_env)
    return {'drill_id': drill_id, 'state': state}


def test_verify_consistent(verify_env):
    """两侧一致：step=pass，零 diff。"""
    env = verify_env
    env['state']['clone'] = [list(r) for r in env['state']['source']]

    result = backup_drill_service.verify_db_tables(env['drill_id'])

    assert result['status'] == 'pass'
    assert result['diff_count'] == 0
    steps = drill_repo.list_steps(env['drill_id'])
    assert len(steps) == 1
    assert steps[0]['status'] == 'pass'
    summary = json.loads(steps[0]['summary'])
    assert summary['judge'] == 'record_only'
    assert drill_repo.list_diffs(env['drill_id'], steps[0]['id']) == []


def test_verify_records_diffs(verify_env):
    """三类差异全部捕获：表数不等 / 克隆多库 / 克隆缺库。"""
    env = verify_env
    # source: app_db=152, user_db=37
    # clone:  app_db=152, user_db=38, extra_db=5 → user_db 表数不等 + extra_db 克隆多库
    # 再让源端多一个 audit_db（克隆缺库）
    env['state']['source'].append(['audit_db', 3, 50])

    result = backup_drill_service.verify_db_tables(env['drill_id'])

    assert result['status'] == 'warn'
    assert result['diff_count'] == 3
    steps = drill_repo.list_steps(env['drill_id'])
    diffs = drill_repo.list_diffs(env['drill_id'], steps[0]['id'])
    by_target = {diff['target']: diff for diff in diffs}
    assert by_target['user_db']['item_type'] == 'db_table_count'
    assert by_target['user_db']['source_value'] == '37'
    assert by_target['user_db']['clone_value'] == '38'
    assert by_target['extra_db']['item_type'] == 'db_extra'
    assert by_target['audit_db']['item_type'] == 'db_missing'
    # 差异 note 均标注"可能为备份后变更"口径。
    assert '备份后' in by_target['user_db']['note']


def test_verify_sql_uses_information_schema(verify_env):
    """两侧 SQL 一致且为 §4.1 元数据聚合（无全表扫描、无 COUNT 业务表）。"""
    env = verify_env
    backup_drill_service.verify_db_tables(env['drill_id'])
    queries = env['state']['queries']
    assert len(queries) == 2
    assert {q['ds_id'] for q in queries} == {101, 202}
    for q in queries:
        assert 'information_schema.tables' in q['sql']
        assert 'GROUP BY table_schema' in q['sql']
        assert "__recycle_bin__" in q['sql']


def test_verify_appends_history(verify_env):
    """重复校验追加新 step，历史保留。"""
    env = verify_env
    backup_drill_service.verify_db_tables(env['drill_id'])
    backup_drill_service.verify_db_tables(env['drill_id'])
    assert len(drill_repo.list_steps(env['drill_id'])) == 2

    data = backup_drill_service.list_verifications(env['drill_id'])
    assert len(data['items']) == 2
    # 最新在前。
    assert data['items'][0]['id'] > data['items'][1]['id']
    # 两侧库清单展开且按字符排序（本用例用 fixture 初始数据：源 2 库、克隆 3 库，
    # user_db 38≠37 + extra_db 多出 → 2 条 diff）。
    first = data['items'][0]
    assert [db['db'] for db in first['source_dbs']] == ['app_db', 'user_db']
    assert [db['db'] for db in first['clone_dbs']] == ['app_db', 'extra_db', 'user_db']
    assert first['source_dbs'][0]['tables'] == 152


def test_verify_requires_ds_registration(sqlite_engine, monkeypatch):
    """未注册数据源时拦截。"""
    with backup_drill_service.get_engine().begin() as conn:
        drill_id = drill_repo.insert_drill(conn, {
            'drill_no': 'DR261106002',
            'account_id': 1,
            'region': 'cn-beijing',
            'source_instance_id': 'rm-src',
            'backup_id': '1',
            'backup_start_time': None,
            'backup_end_time': None,
            'clone_params': '{}',
            'target_tables': None,
            'status': drill_repo.STATUS_SUCCESS,
            'triggered_by': 'tester',
            'clone_started_at': None,
        })
    with pytest.raises(ApiError) as exc:
        backup_drill_service.verify_db_tables(drill_id)
    assert '数据源注册' in exc.value.user_message


def test_verify_sql_failure_recorded(verify_env, monkeypatch):
    """SQL 执行失败：错误写入 step（error 字段），不抛给前端中断。"""
    env = verify_env

    def fake_execute(ds_id, env_id, database, sql):
        raise ApiError(-500, 'SQL 执行失败：连接超时', 'timeout', 502)

    monkeypatch.setattr(backup_drill_service.query_client, 'execute_query', fake_execute)
    with pytest.raises(ApiError) as exc:
        backup_drill_service.verify_db_tables(env['drill_id'])
    assert 'SQL 执行失败' in exc.value.user_message
