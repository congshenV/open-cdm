"""表数据校验（简化口径：id 主键 + MIN(id) 行对比）单测。"""

import json

import pytest

from app.infra import backup_drill_repository as drill_repo
from app.service import backup_drill_service
from app.util.errors import ApiError


@pytest.fixture()
def table_env(sqlite_engine, monkeypatch):
    """success 演练 + 双端注册 + query_client mock（按 SQL 形态分发）。"""
    import datetime

    with backup_drill_service.get_engine().begin() as conn:
        drill_id = drill_repo.insert_drill(conn, {
            'drill_no': 'DR261106101',
            'account_id': 1,
            'region': 'cn-beijing',
            'source_instance_id': 'rm-src',
            'backup_id': '3222768592',
            'backup_start_time': datetime.datetime(2026, 11, 5, 3, 0, 0),
            'backup_end_time': datetime.datetime(2026, 11, 5, 3, 13, 54),
            'clone_params': '{}',
            'target_tables': None,
            'status': drill_repo.STATUS_SUCCESS,
            'triggered_by': 'tester',
            'clone_started_at': None,
        })
        drill_repo.update_ds_id(conn, drill_id, 'source', 101)
        drill_repo.update_ds_id(conn, drill_id, 'clone', 202)

    state = {
        'id_pk': True,
        'min_id': 1,
        'clone_count': 0,
        # 点查结果：源/克隆的 id=min_id 行（等宽列表）。
        'rows': {101: ['1', 'alice'], 202: ['1', 'alice']},
        'engine': 'mysql',
    }

    def fake_env(ds_id):
        return 1

    def fake_engine(account_id, region, instance_id):
        return state['engine']

    def fake_execute(ds_id, env_id, database, sql):
        sql_l = sql.strip().lower()
        if "constraint_name = 'primary'" in sql_l or "tc.constraint_type = 'primary key'" in sql_l:
            # id 主键前置检查。
            return ['cnt'], [[1 if state['id_pk'] else 0]]
        if 'select min(' in sql_l:
            return ['min_id'], [[state['min_id']]]
        if 'select count(' in sql_l:
            # 源空时查克隆侧行数。
            return ['cnt'], [[state['clone_count']]]
        if 'select * from' in sql_l:
            key = ds_id
            return ['id', 'name'], [list(state['rows'][key])] if state['rows'][key] else []
        raise AssertionError(f'unexpected sql in mock: {sql[:120]}')

    monkeypatch.setattr(backup_drill_service, '_ds_env_id', fake_env)
    monkeypatch.setattr(backup_drill_service, '_drill_engine_type', fake_engine)
    monkeypatch.setattr(backup_drill_service.query_client, 'execute_query', fake_execute)
    monkeypatch.setattr(backup_drill_service.resource_repo, 'get_resource',
                        lambda account_id, region, cloud_id: {'engine': 'MySQL'})
    return {'drill_id': drill_id, 'state': state}


def test_min_id_row_pass(table_env):
    """两侧 MIN(id) 行全列一致 → pass。"""
    env = table_env
    result = backup_drill_service.verify_table_data(env['drill_id'], ['app_db.orders'])

    assert result['passed'] == 1
    assert result['tables'][0]['status'] == 'pass'
    steps = drill_repo.list_steps(env['drill_id'])
    assert steps[0]['layer'] == 'ROW'
    diffs = drill_repo.list_diffs(env['drill_id'], steps[0]['id'])
    assert len(diffs) == 1
    assert diffs[0]['status'] == 'pass'
    assert '全部列一致' in diffs[0]['note']


def test_min_id_row_column_diff(table_env):
    """行值不一致 → fail，note 给差异列摘要。"""
    env = table_env
    env['state']['rows'][202] = ['1', 'bob']

    result = backup_drill_service.verify_table_data(env['drill_id'], ['app_db.orders'])
    assert result['tables'][0]['status'] == 'fail'
    assert 'col#' in result['tables'][0]['note']


def test_no_id_pk_skip(table_env):
    """id 非主键 → skip，提示重选。"""
    env = table_env
    env['state']['id_pk'] = False

    result = backup_drill_service.verify_table_data(env['drill_id'], ['app_db.orders'])
    assert result['tables'][0]['status'] == 'skip'
    assert '重选' in result['tables'][0]['note']


def test_both_empty_table_pass(table_env):
    """两侧均为空表 → pass："两侧均为空表，对比一致"。"""
    env = table_env
    env['state']['min_id'] = None
    env['state']['clone_count'] = 0

    result = backup_drill_service.verify_table_data(env['drill_id'], ['app_db.orders'])
    assert result['tables'][0]['status'] == 'pass'
    assert '两侧均为空表，对比一致' in result['tables'][0]['note']


def test_source_empty_clone_has_rows_fail(table_env):
    """源空、克隆非空 → fail（可能源表备份后被清空）。"""
    env = table_env
    env['state']['min_id'] = None
    env['state']['clone_count'] = 48

    result = backup_drill_service.verify_table_data(env['drill_id'], ['app_db.orders'])
    assert result['tables'][0]['status'] == 'fail'
    assert '克隆侧有 48 行' in result['tables'][0]['note']


def test_clone_row_missing_fail(table_env):
    """克隆侧无此行 → fail。"""
    env = table_env
    env['state']['rows'][202] = []

    result = backup_drill_service.verify_table_data(env['drill_id'], ['app_db.orders'])
    assert result['tables'][0]['status'] == 'fail'
    assert '克隆侧无' in result['tables'][0]['note']


def test_limit_and_format(table_env):
    """表数上限与 db.table 格式校验。"""
    env = table_env
    with pytest.raises(ApiError) as exc:
        backup_drill_service.verify_table_data(env['drill_id'], ['a.b.c'])
    assert 'db.table' in exc.value.user_message

    with pytest.raises(ApiError) as exc:
        backup_drill_service.verify_table_data(env['drill_id'], [f'db_{i}.t' for i in range(6)])
    assert '最多' in exc.value.user_message


def test_table_name_whitelist(table_env):
    """表名白名单：内部反引号/空格/分号等注入字符被拦（M5）。"""
    env = table_env
    for bad in ['a`b.orders', 'app_db.or ders', 'app_db.;--', 'app db.orders', "app_db.or'ders"]:
        with pytest.raises(ApiError) as exc:
            backup_drill_service.verify_table_data(env['drill_id'], [bad])
        assert '不支持的字符' in exc.value.user_message

    # 合法字符集放行：下划线、美元符、中文。
    result = backup_drill_service.verify_table_data(env['drill_id'], ['app_db.订单表$t'])
    assert result['total'] == 1


def test_dedup(table_env):
    """重复表名去重。"""
    env = table_env
    result = backup_drill_service.verify_table_data(env['drill_id'], ['app_db.orders', 'app_db.orders'])
    assert result['total'] == 1


def test_drill_tables_annotations(table_env, monkeypatch):
    """drill-tables：返回去重、排序、且标注三个布尔位。"""
    env = table_env

    def fake_execute(ds_id, env_id, database, sql):
        if 'information_schema.tables' in sql:
            return ['db', 'table', 'has_pk', 'has_unique', 'has_upd'], [
                ['app_db', 'orders', 1, 1, 1],
                ['app_db', 'orders', 1, 1, 1],  # 多索引 JOIN 重复行，应合并
                ['app_db', 'events', 0, 0, 0],
                ['z_db', 'audit', 1, 0, 0],
            ]
        raise AssertionError(f'unexpected: {sql[:80]}')

    monkeypatch.setattr(backup_drill_service.query_client, 'execute_query', fake_execute)
    data = backup_drill_service.drill_tables(env['drill_id'])
    assert data['total'] == 3
    keys = [f"{i['db']}.{i['table']}" for i in data['items']]
    assert keys == ['app_db.events', 'app_db.orders', 'z_db.audit']
    by_key = {f"{i['db']}.{i['table']}": i for i in data['items']}
    assert by_key['app_db.orders']['has_pk'] is True
    assert by_key['app_db.events']['has_pk'] is False


def test_drill_tables_requires_source_ds(sqlite_engine):
    """源端未注册时 drill-tables 拦截。"""
    with backup_drill_service.get_engine().begin() as conn:
        drill_id = drill_repo.insert_drill(conn, {
            'drill_no': 'DR261106102',
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
        backup_drill_service.drill_tables(drill_id)
    assert '源端' in exc.value.user_message


def test_row_batches_merged_in_history(table_env):
    """同一次触发的多张表在校验历史里合并为一个 ROW-BATCH 条目。"""
    env = table_env
    backup_drill_service.verify_table_data(
        env['drill_id'], ['app_db.orders', 'app_db.t_user_info']
    )
    data = backup_drill_service.list_verifications(env['drill_id'])
    # 仅一个条目且为 ROW-BATCH，包含两张表。
    assert len(data['items']) == 1
    batch = data['items'][0]
    assert batch['layer'] == 'ROW-BATCH'
    assert batch['total'] == 2
    assert batch['passed'] == 2
    assert [row['table'] for row in batch['tables']] == ['app_db.orders', 'app_db.t_user_info']
    # mock 环境执行极快，cost 可能为 0——只断言字段存在与非负。
    assert batch['total_ms'] is not None and batch['total_ms'] >= 0

    # 再触发一次：历史里两个批次，最新在前。
    backup_drill_service.verify_table_data(env['drill_id'], ['app_db.orders'])
    data = backup_drill_service.list_verifications(env['drill_id'])
    assert len(data['items']) == 2
    assert all(item['layer'] == 'ROW-BATCH' for item in data['items'])
    assert data['items'][0]['total'] == 1


def test_row_batch_status_worst_wins(table_env):
    """批次状态取最差：任一 fail 即 fail。"""
    env = table_env
    # orders 正常；bad_table 让克隆缺行（点查空）——需要在两张表间切换克隆数据。
    real_execute = backup_drill_service.query_client.execute_query

    def fake_execute(ds_id, env_id, database, sql):
        sql_l = sql.strip().lower()
        if 'select * from' in sql_l and '`app_db`.`bad_table`' in sql_l:
            return ['id', 'name'], []
        return real_execute(ds_id, env_id, database, sql)

    import unittest.mock as mock
    with mock.patch.object(backup_drill_service.query_client, 'execute_query', side_effect=fake_execute):
        backup_drill_service.verify_table_data(env['drill_id'], ['app_db.orders', 'app_db.bad_table'])
    data = backup_drill_service.list_verifications(env['drill_id'])
    batch = data['items'][0]
    assert batch['status'] == 'fail'
    assert batch['passed'] == 1
    assert batch['total'] == 2
