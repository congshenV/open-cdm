"""注册数据源（源端/克隆）单测：mock console 接口与 JWT 上下文。"""

import pytest

from app.infra import backup_drill_repository as drill_repo
from app.service import backup_drill_service
from app.util.errors import ApiError


@pytest.fixture()
def register_env(sqlite_engine, monkeypatch):
    """一条 success 演练 + 原/克隆实例资源 + console 调用捕获。"""
    with backup_drill_service.get_engine().begin() as conn:
        drill_id = drill_repo.insert_drill(conn, {
            'drill_no': 'DR261105001',
            'account_id': 1,
            'region': 'cn-hangzhou',
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
        drill_repo.mark_clone_submitted(conn, drill_id, 'pgm-clone')

    calls = {'connect': [], 'add': []}

    def fake_connect(jwt_token, body):
        calls['connect'].append({'jwt': jwt_token, 'body': body})
        if body['configMap'].get('password') == 'bad':
            raise ApiError(-500, '连接测试失败：密码错误', 'bad password', 502)

    def fake_add(jwt_token, body):
        calls['add'].append({'jwt': jwt_token, 'body': body})
        return 4321

    monkeypatch.setattr(backup_drill_service.console_client, 'connect_ds', fake_connect)
    monkeypatch.setattr(backup_drill_service.console_client, 'add_ds', fake_add)
    monkeypatch.setattr(backup_drill_service, '_current_jwt_token', lambda: 'fake-jwt')
    monkeypatch.setattr(
        backup_drill_service.cdm_meta_repo, 'list_clusters',
        lambda: [{'id': 1, 'cluster_desc': 'Default Cluster'}, {'id': 2, 'cluster_desc': 'Backup'}],
    )
    monkeypatch.setattr(
        backup_drill_service.cdm_meta_repo, 'list_envs',
        lambda: [{'id': 1, 'env_name': 'Local'}, {'id': 2, 'env_name': 'ali-beijing'}],
    )
    # 查重走真实 dm_ds 表（conftest 已建）：register_env 插入的演练无历史数据源，
    # 复用/创建两个分支由用例自行插行控制。
    return {'drill_id': drill_id, 'calls': calls}


def test_register_prefill_default_credentials(sqlite_engine, monkeypatch):
    """预填：账号密码来自配置管理 rds_default_u_p；配置缺失时留空。"""
    with backup_drill_service.get_engine().begin() as conn:
        drill_id = drill_repo.insert_drill(conn, {
            'drill_no': 'DR261105009',
            'account_id': 1,
            'region': 'cn-hangzhou',
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

    monkeypatch.setattr(
        backup_drill_service.resource_repo, 'get_resource',
        lambda account_id, region, cloud_id: {
            'connection_string': 'rm-src.mysql.rds.aliyuncs.com',
            'engine': 'MySQL',
            'instance_name': 'infra-platform-dbtest',
            'level': 'S2',
        },
    )
    monkeypatch.setattr(
        backup_drill_service.config_repo, 'get_by_key',
        lambda key: {'config_value': '{"user": "admin", "passwd": "secret"}'} if key == 'rds_default_u_p' else None,
    )

    monkeypatch.setattr(
        backup_drill_service.cdm_meta_repo, 'list_clusters',
        lambda: [{'id': 9, 'cluster_desc': 'First Cluster'}, {'id': 1, 'cluster_desc': 'Default Cluster'}],
    )
    monkeypatch.setattr(
        backup_drill_service.cdm_meta_repo, 'list_envs',
        lambda: [{'id': 1, 'env_name': 'Local'}, {'id': 2, 'env_name': 'ali-beijing'}],
    )
    monkeypatch.setattr(backup_drill_service.cdm_meta_repo, 'find_alive_ds_by_host', lambda host, port: None)
    from app import config as config_module
    original_env = config_module.Cdm.env_id
    original_cluster = config_module.Cdm.cluster_id
    config_module.Cdm.env_id = 2
    config_module.Cdm.cluster_id = 1
    try:
        data = backup_drill_service.register_ds_prefill(drill_id, 'source')
    finally:
        config_module.Cdm.env_id = original_env
        config_module.Cdm.cluster_id = original_cluster
    assert data['username'] == 'admin'
    assert data['password'] == 'secret'
    assert data['host'] == 'rm-src.mysql.rds.aliyuncs.com'
    assert data['ds_type'] == 'MySQL'
    # mic 命名：地区/实例等级/实例名。
    assert data['instance_desc'] == 'cn-hangzhou/S2/infra-platform-dbtest'
    # 集群选项 + 默认取清单第一项（id=9，非配置值 1）；环境默认仍取 dmops 配置。
    assert data['clusters'] == [{'id': 9, 'cluster_desc': 'First Cluster'}, {'id': 1, 'cluster_desc': 'Default Cluster'}]
    assert data['envs'] == [{'id': 1, 'env_name': 'Local'}, {'id': 2, 'env_name': 'ali-beijing'}]
    assert data['cluster_id'] == 9
    assert data['env_id'] == 2


def test_register_prefill_no_config(sqlite_engine, monkeypatch):
    """配置管理无 rds_default_u_p：账号密码留空，不报错。"""
    with backup_drill_service.get_engine().begin() as conn:
        drill_id = drill_repo.insert_drill(conn, {
            'drill_no': 'DR261105010',
            'account_id': 1,
            'region': 'cn-hangzhou',
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
    monkeypatch.setattr(
        backup_drill_service.resource_repo, 'get_resource',
        lambda account_id, region, cloud_id: {
            'connection_string': 'rm-src.mysql.rds.aliyuncs.com',
            'engine': 'MySQL',
            'instance_name': 'infra-platform-dbtest',
            'level': '',  # 等级缺失回落 S1
        },
    )
    monkeypatch.setattr(
        backup_drill_service.config_repo, 'get_by_key', lambda key: None,
    )
    monkeypatch.setattr(
        backup_drill_service.cdm_meta_repo, 'list_clusters', lambda: [],
    )
    monkeypatch.setattr(
        backup_drill_service.cdm_meta_repo, 'list_envs', lambda: [],
    )
    monkeypatch.setattr(backup_drill_service.cdm_meta_repo, 'find_alive_ds_by_host', lambda host, port: None)

    data = backup_drill_service.register_ds_prefill(drill_id, 'source')
    assert data['username'] == ''
    assert data['password'] == ''
    assert data['instance_desc'] == 'cn-hangzhou/S1/infra-platform-dbtest'
    # 集群/环境清单为空时选项为空列表（弹窗回落配置默认值）。
    assert data['clusters'] == []
    assert data['envs'] == []


def insert_ds_row(env, ds_id, host, desc='test'):
    """向测试库 dm_ds 插一行存活数据源（record id 存 last_id 供断言）。"""
    from sqlalchemy import text

    with backup_drill_service.get_engine().begin() as conn:
        result = conn.execute(text('''
            INSERT INTO dm_ds (id, gmt_create, gmt_modified, host, instance_desc, life_cycle_state)
            VALUES (:id, '2026-11-06 10:00:00', '2026-11-06 10:00:00', :host, :desc, 'CREATED')
        '''), {'id': ds_id, 'host': host, 'desc': desc})
        if ds_id is None:
            insert_ds_row.last_id = int(result.lastrowid or 0)


def _body(**extra):
    body = {
        'host': 'pgm-src.pg.rds.aliyuncs.com',
        'port': '5432',
        'engine': 'PostgreSQL',
        'username': 'admin',
        'password': 'secret',
        'instance_desc': '',
    }
    body.update(extra)
    return body


def test_register_submit_success(register_env):
    """提交：connectDs → addDs → dsId 回写 clone_ds_id；集群/环境用用户选择值。"""
    env = register_env
    result = backup_drill_service.register_ds_submit(
        env['drill_id'], 'clone', _body(cluster_id=2, env_id=2),
    )

    assert result['ds_id'] == 4321
    assert len(env['calls']['connect']) == 1
    assert len(env['calls']['add']) == 1
    # addDs body 口径：dsId null + 用户选择的 envId/clusterId + configMap 完整。
    add_body = env['calls']['add'][0]['body']
    assert add_body['dsId'] is None
    assert add_body['dsType'] == 'PostgreSQL'
    assert add_body['envId'] == 2
    # connectDs 的 clusterId 同步用户选择。
    connect_body = env['calls']['connect'][0]['body']
    assert connect_body['clusterId'] == 2
    assert add_body['configMap']['address'] == 'pgm-src.pg.rds.aliyuncs.com'
    # console 消费驼峰键 userName（Java 字段名），非下划线 username。
    assert add_body['configMap']['userName'] == 'admin'
    assert 'username' not in add_body['configMap']
    # dsId 落库。
    drill = drill_repo.get_drill(env['drill_id'])
    assert drill['clone_ds_id'] == 4321
    assert drill['source_ds_id'] is None


def test_register_submit_source_writes_source_column(register_env):
    env = register_env
    backup_drill_service.register_ds_submit(env['drill_id'], 'source', _body())
    drill = drill_repo.get_drill(env['drill_id'])
    assert drill['source_ds_id'] == 4321
    assert drill['clone_ds_id'] is None


def test_register_test_no_write(register_env):
    """测试连接：不调 addDs、不落库。"""
    env = register_env
    result = backup_drill_service.register_ds_test(env['drill_id'], 'clone', _body())
    assert result['tested'] is True
    assert len(env['calls']['connect']) == 1
    assert len(env['calls']['add']) == 0
    assert drill_repo.get_drill(env['drill_id'])['clone_ds_id'] is None


def test_register_connect_failure_aborts_submit(register_env):
    """connectDs 失败（密码错）：提交中断，不调 addDs、不回写。"""
    env = register_env
    with pytest.raises(ApiError) as exc:
        backup_drill_service.register_ds_submit(env['drill_id'], 'clone', _body(password='bad'))
    assert '密码错误' in exc.value.user_message
    assert len(env['calls']['add']) == 0
    assert drill_repo.get_drill(env['drill_id'])['clone_ds_id'] is None


def test_register_missing_fields(register_env):
    env = register_env
    with pytest.raises(ApiError) as exc:
        backup_drill_service.register_ds_submit(env['drill_id'], 'clone', _body(password=''))
    assert '必填' in exc.value.user_message


def test_register_invalid_target(register_env):
    env = register_env
    with pytest.raises(ApiError) as exc:
        backup_drill_service.register_ds_submit(env['drill_id'], 'other', _body())
    assert 'source 或 clone' in exc.value.user_message


def test_register_requires_success_status(register_env):
    """克隆未完成的演练不可注册。"""
    env = register_env
    with backup_drill_service.get_engine().begin() as conn:
        # 造一条 cloning 状态的记录验证。
        drill_id2 = drill_repo.insert_drill(conn, {
            'drill_no': 'DR261105002',
            'account_id': 1,
            'region': 'cn-hangzhou',
            'source_instance_id': 'rm-src',
            'backup_id': '1',
            'backup_start_time': None,
            'backup_end_time': None,
            'clone_params': '{}',
            'target_tables': None,
            'status': drill_repo.STATUS_CLONING,
            'triggered_by': 'tester',
            'clone_started_at': None,
        })
    with pytest.raises(ApiError) as exc:
        backup_drill_service.register_ds_test(drill_id2, 'clone', _body())
    assert '克隆完成' in exc.value.user_message


def test_register_mysql_engine_mapping(register_env):
    """MySQL 引擎映射：dsType/端口/驱动族与 drivers.xml 口径一致。"""
    env = register_env
    backup_drill_service.register_ds_submit(env['drill_id'], 'clone', _body(engine='MySQL'))
    add_body = env['calls']['add'][0]['body']
    assert add_body['dsType'] == 'MySQL'
    assert add_body['configMap']['port'] == '5432'  # 用户提供值优先于引擎默认
    connect_body = env['calls']['connect'][0]['body']
    # driver 未传时回落 MySQL 默认驱动。
    assert connect_body['configMap']['driverFamily'] == 'MySQL Connector/J'


def test_register_unsupported_engine(register_env):
    env = register_env
    with pytest.raises(ApiError) as exc:
        backup_drill_service.register_ds_submit(env['drill_id'], 'clone', _body(engine='Oracle'))
    assert '暂不支持' in exc.value.user_message


def test_register_submit_reuses_existing_ds(register_env):
    """提交时同 host 已有数据源（console 存储 host 含端口）：复用 dsId 不再创建。

    历史 bug：查重传不带端口的 host，与库里 'address:port' 形态等值永不匹配，
    曾导致重复建源——此用例走真实 SQL（不 mock 查重函数）防止口径回归。
    """
    env = register_env
    host_full = 'pgm-src.pg.rds.aliyuncs.com:5432'
    insert_ds_row(env, ds_id=None, host=host_full, desc='已存在数据源')

    result = backup_drill_service.register_ds_submit(env['drill_id'], 'source', _body())

    assert result['ds_id'] == insert_ds_row.last_id
    # 服务端显式返回复用标志（前端据此提示"实例已存在，复用该实例"）。
    assert result['reused'] is True
    # 未创建新数据源。
    assert len(env['calls']['add']) == 0
    # connectDs 仍执行（复用前照常验证连通）。
    assert len(env['calls']['connect']) == 1
    # 演练表回写的是已有 dsId。
    assert drill_repo.get_drill(env['drill_id'])['source_ds_id'] == insert_ds_row.last_id


def test_register_submit_reuses_host_without_port(register_env):
    """库里存不带端口的形态（历史口径）：前缀兜底同样复用。"""
    env = register_env
    insert_ds_row(env, ds_id=None, host='pgm-src.pg.rds.aliyuncs.com', desc='旧形态')

    result = backup_drill_service.register_ds_submit(env['drill_id'], 'source', _body())
    assert result['ds_id'] == insert_ds_row.last_id
    assert result['reused'] is True
    assert len(env['calls']['add']) == 0


def test_register_submit_creates_when_absent(register_env):
    """无同 host 数据源：正常走 addDs 创建。"""
    env = register_env
    result = backup_drill_service.register_ds_submit(env['drill_id'], 'source', _body())
    assert result['ds_id'] == 4321
    assert result['reused'] is False
    assert len(env['calls']['add']) == 1


def test_register_prefill_carries_existing_ds(sqlite_engine, monkeypatch):
    """prefill 下发 existing_ds：弹窗可提前提示复用。"""
    with backup_drill_service.get_engine().begin() as conn:
        drill_id = drill_repo.insert_drill(conn, {
            'drill_no': 'DR261106111',
            'account_id': 1,
            'region': 'cn-hangzhou',
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
    monkeypatch.setattr(
        backup_drill_service.resource_repo, 'get_resource',
        lambda account_id, region, cloud_id: {
            'connection_string': 'rm-src.mysql.rds.aliyuncs.com',
            'engine': 'MySQL', 'instance_name': 'src', 'level': 'S1',
        },
    )
    monkeypatch.setattr(backup_drill_service.config_repo, 'get_by_key', lambda key: None)
    monkeypatch.setattr(backup_drill_service.cdm_meta_repo, 'list_clusters', lambda: [])
    monkeypatch.setattr(backup_drill_service.cdm_meta_repo, 'list_envs', lambda: [])
    monkeypatch.setattr(
        backup_drill_service.cdm_meta_repo, 'find_alive_ds_by_host',
        lambda host, port: {'id': 77, 'host': host, 'instance_desc': 'old'},
    )
    data = backup_drill_service.register_ds_prefill(drill_id, 'source')
    assert data['existing_ds'] == {'id': 77, 'host': 'rm-src.mysql.rds.aliyuncs.com', 'instance_desc': 'old'}
