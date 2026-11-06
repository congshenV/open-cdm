"""drill service 参数检测与编排单测（mock 阿里云与身份）。"""

import json

import pytest

from app.infra import backup_drill_repository as drill_repo
from app.service import backup_drill_service
from app.util.errors import ApiError


class _FakeAttribute:
    """DescribeDBInstanceAttribute 返回体的最小替身。"""

    def __init__(self, category='HighAvailability', status='Running',
                 description='mydb-prod', serverless_config=None):
        self.dbinstance_id = 'rm-xxx'
        self.dbinstance_description = description
        self.category = category
        self.dbinstance_status = status
        self.zone_id = 'cn-hangzhou-b'
        self.dbinstance_class = 'mysql.x8.large.2c'
        self.dbinstance_storage = 500
        self.dbinstance_storage_type = 'cloud_essd'
        self.instance_network_type = 'VPC'
        self.vpc_id = 'vpc-1'
        self.v_switch_id = 'vsw-1'
        self.engine = 'MySQL'
        self.engine_version = '8.0'
        self.serverless_config = serverless_config


class _FakeBackupBody:
    """DescribeBackups 返回体替身。"""

    def __init__(self, items, total=None):
        class _Items:
            pass

        _Items.backup = items
        self.items = _Items
        self.total_record_count = total if total is not None else len(items)


class _FakeBackupItem:
    def __init__(self, backup_id='3222768592', is_avail=1, backup_type='FullBackup'):
        self.backup_id = backup_id
        self.is_avail = is_avail
        self.backup_type = backup_type
        self.backup_start_time = '2026-11-02T03:00:00Z'
        self.backup_end_time = '2026-11-02T03:13:54Z'


@pytest.fixture()
def mock_aliyun(monkeypatch):
    """替身：账号/凭据存在，实例与备份可查。返回可控的 attribute/backup。"""
    monkeypatch.setattr(
        backup_drill_service, '_require_account', lambda account_id: {'id': account_id},
    )
    monkeypatch.setattr(
        backup_drill_service, '_require_credential',
        lambda account_id: {'enabled': True},
    )
    state = {'attribute': _FakeAttribute(), 'backup': _FakeBackupItem()}

    def fake_describe_source(account_id, region, instance_id):
        return state['attribute']

    def fake_describe_backup(account_id, region, instance_id, backup_id):
        if str(backup_id) != str(state['backup'].backup_id):
            return None
        return {
            'backup_id': str(state['backup'].backup_id),
            'backup_type': state['backup'].backup_type,
            'is_avail': state['backup'].is_avail,
            'backup_start_time': state['backup'].backup_start_time,
            'backup_end_time': state['backup'].backup_end_time,
        }

    monkeypatch.setattr(backup_drill_service, '_describe_source_instance', fake_describe_source)
    monkeypatch.setattr(backup_drill_service, '_describe_backup', fake_describe_backup)
    monkeypatch.setattr(backup_drill_service, 'get_current_uid', lambda: 'tester')
    return state


def _create_body(**extra):
    body = {
        'account_id': 1,
        'region': 'cn-hangzhou',
        'instance_id': 'rm-xxx',
        'backup_id': '3222768592',
    }
    body.update(extra)
    return body


def test_create_drill_success(sqlite_engine, mock_aliyun):
    result = backup_drill_service.create_drill(_create_body())

    assert result['drill_no'].endswith('001')
    drill = drill_repo.get_drill(result['id'])
    assert drill['status'] == 'pending'
    params = json.loads(drill['clone_params'])
    # 名称默认模板 drill-{drill_no}（弹窗预填原样提交或留空）。
    assert params['dbinstance_description'] == f"drill-{result['drill_no']}"
    assert params['backup_type'] == 'FullBackup'


def test_create_drill_custom_description(sqlite_engine, mock_aliyun):
    """弹窗改过名称：用户值生效并做格式校验。"""
    result = backup_drill_service.create_drill(_create_body(instance_description='my-custom-name'))

    params = json.loads(drill_repo.get_drill(result['id'])['clone_params'])
    assert params['dbinstance_description'] == 'my-custom-name'


def test_create_drill_prefilled_template_regenerated(sqlite_engine, mock_aliyun):
    """预填模板原样提交：以事务内真号重新生成（预览号可能过期）。"""
    result = backup_drill_service.create_drill(
        _create_body(instance_description='drill-DR261104001', prefilled_drill_no='DR261104001'),
    )

    params = json.loads(drill_repo.get_drill(result['id'])['clone_params'])
    assert params['dbinstance_description'] == f"drill-{result['drill_no']}"


def test_create_drill_invalid_description(sqlite_engine, mock_aliyun):
    """用户改的名称非法（特殊字符）被拒。"""
    with pytest.raises(ApiError) as exc:
        backup_drill_service.create_drill(_create_body(instance_description='bad name!'))
    assert '实例名称' in exc.value.user_message


def test_create_drill_allows_serverless(sqlite_engine, mock_aliyun):
    """Serverless 实例不再拦截（§2.1-D3 修订：克隆原生支持，透传 RCU 配置）。"""
    mock_aliyun['attribute'] = _FakeAttribute(category='serverless_standard')

    result = backup_drill_service.create_drill(_create_body())
    assert result['drill_no'].endswith('001')
    assert drill_repo.get_drill(result['id'])['status'] == 'pending'


def test_create_drill_rejects_unavailable_backup(sqlite_engine, mock_aliyun):
    mock_aliyun['backup'] = _FakeBackupItem(is_avail=0)

    with pytest.raises(ApiError) as exc:
        backup_drill_service.create_drill(_create_body())
    assert '不可用' in exc.value.user_message


def test_create_drill_rejects_missing_backup(sqlite_engine, mock_aliyun):
    with pytest.raises(ApiError) as exc:
        backup_drill_service.create_drill(_create_body(backup_id='404'))
    assert '备份集不存在' in exc.value.user_message


def test_create_drill_global_concurrency(sqlite_engine, mock_aliyun):
    backup_drill_service.create_drill(_create_body())

    # 第二条（不同实例）也会被全局并发=1 拦下。
    with pytest.raises(ApiError) as exc:
        backup_drill_service.create_drill(_create_body(instance_id='rm-yyy'))
    assert '并发' in exc.value.user_message


def test_create_drill_same_instance_blocked(sqlite_engine, mock_aliyun):
    """全局并发放宽后，同实例串行约束仍生效。"""
    from app import config
    original = config.Drill.max_concurrency
    config.Drill.max_concurrency = 5
    try:
        backup_drill_service.create_drill(_create_body())
        with pytest.raises(ApiError) as exc:
            backup_drill_service.create_drill(_create_body())
        assert '该实例' in exc.value.user_message
    finally:
        config.Drill.max_concurrency = original


def test_cancel_then_create_allowed(sqlite_engine, mock_aliyun):
    """pending 取消后不占用并发槽，可再次发起。"""
    first = backup_drill_service.create_drill(_create_body())
    backup_drill_service.cancel_drill(first['id'])

    second = backup_drill_service.create_drill(_create_body())
    assert second['id'] != first['id']


def test_cancel_after_cloning_rejected(sqlite_engine, mock_aliyun):
    drill_id = backup_drill_service.create_drill(_create_body())['id']
    with backup_drill_service.get_engine().begin() as conn:
        drill_repo.claim_pending(conn, drill_id)

    with pytest.raises(ApiError) as exc:
        backup_drill_service.cancel_drill(drill_id)
    assert '不能取消' in exc.value.user_message


def test_confirm_offline_requires_clone(sqlite_engine, mock_aliyun):
    drill_id = backup_drill_service.create_drill(_create_body())['id']

    with pytest.raises(ApiError) as exc:
        backup_drill_service.confirm_offline(drill_id)
    assert '未产生克隆实例' in exc.value.user_message


def test_run_clone_stage_submit_and_running(sqlite_engine, mock_aliyun, monkeypatch):
    """编排冒烟：提交克隆 → 落 instance_id → 轮询一次即 Running → success。"""
    drill_id = backup_drill_service.create_drill(_create_body())['id']
    with backup_drill_service.get_engine().begin() as conn:
        drill_repo.claim_pending(conn, drill_id)
    drill = drill_repo.get_drill(drill_id)

    calls = {'clone': 0, 'poll': 0}

    class _FakeClient:
        pass

    monkeypatch.setattr(
        backup_drill_service.credential_repo, 'get_credential',
        lambda account_id: {'enabled': True},
    )
    monkeypatch.setattr(
        backup_drill_service.credential_repo, 'get_credential',
        lambda account_id: {'enabled': True},
    )
    monkeypatch.setattr(
        backup_drill_service.client_factory, 'get_rds_client',
        lambda account_id, credential, region: _FakeClient(),
    )

    def fake_clone(client, params):
        calls['clone'] += 1
        assert params['client_token'] == f"drill-{drill['drill_no']}"
        assert params['backup_id'] == '3222768592'
        assert params['dbinstance_description'] == f"drill-{drill['drill_no']}"
        return 'rm-clone-1', 'order-1'

    def fake_poll(client, instance_id):
        calls['poll'] += 1
        return _FakeAttribute(description='clone', status='Running')

    monkeypatch.setattr(backup_drill_service.rds, 'clone_db_instance', fake_clone)
    monkeypatch.setattr(backup_drill_service.rds, 'describe_instance_attribute', fake_poll)
    # 轮询间隔不真实等待。
    monkeypatch.setattr('app.service.backup_drill_service.time.sleep', lambda sec: None)

    backup_drill_service.run_clone_stage(drill)

    assert calls['clone'] == 1
    assert calls['poll'] == 1
    finished = drill_repo.get_drill(drill_id)
    assert finished['status'] == 'success'
    assert finished['clone_instance_id'] == 'rm-clone-1'


def test_run_clone_stage_submit_failure_marks_failed(sqlite_engine, mock_aliyun, monkeypatch):
    drill_id = backup_drill_service.create_drill(_create_body())['id']
    with backup_drill_service.get_engine().begin() as conn:
        drill_repo.claim_pending(conn, drill_id)
    drill = drill_repo.get_drill(drill_id)

    class _FakeClient:
        pass

    monkeypatch.setattr(
        backup_drill_service.credential_repo, 'get_credential',
        lambda account_id: {'enabled': True},
    )
    monkeypatch.setattr(
        backup_drill_service.client_factory, 'get_rds_client',
        lambda account_id, credential, region: _FakeClient(),
    )

    def fake_clone(client, params):
        raise RuntimeError('InvalidBackupId.NotFound')

    monkeypatch.setattr(backup_drill_service.rds, 'clone_db_instance', fake_clone)
    monkeypatch.setattr('app.service.backup_drill_service.time.sleep', lambda sec: None)

    backup_drill_service.run_clone_stage(drill)

    finished = drill_repo.get_drill(drill_id)
    assert finished['status'] == 'failed'
    assert '克隆提交失败' in finished['error_message']
    # 提交失败没有实例 ID，不进待下线清单。
    assert finished['clone_instance_id'] is None


def test_run_clone_stage_resume_skips_submit(sqlite_engine, mock_aliyun, monkeypatch):
    """断点续跑：clone_instance_id 已落库时不再提交，直接轮询。"""
    drill_id = backup_drill_service.create_drill(_create_body())['id']
    with backup_drill_service.get_engine().begin() as conn:
        drill_repo.claim_pending(conn, drill_id)
        drill_repo.mark_clone_submitted(conn, drill_id, 'rm-clone-1')
    drill = drill_repo.get_drill(drill_id)

    class _FakeClient:
        pass

    monkeypatch.setattr(
        backup_drill_service.credential_repo, 'get_credential',
        lambda account_id: {'enabled': True},
    )
    monkeypatch.setattr(
        backup_drill_service.client_factory, 'get_rds_client',
        lambda account_id, credential, region: _FakeClient(),
    )

    def fake_clone(client, params):
        raise AssertionError('resume must not submit clone again')

    def fake_poll(client, instance_id):
        assert instance_id == 'rm-clone-1'
        return _FakeAttribute(status='Running')

    monkeypatch.setattr(backup_drill_service.rds, 'clone_db_instance', fake_clone)
    monkeypatch.setattr(backup_drill_service.rds, 'describe_instance_attribute', fake_poll)
    monkeypatch.setattr('app.service.backup_drill_service.time.sleep', lambda sec: None)

    backup_drill_service.run_clone_stage(drill)
    assert drill_repo.get_drill(drill_id)['status'] == 'success'


def test_run_clone_stage_serverless_params(sqlite_engine, mock_aliyun, monkeypatch):
    """Serverless 源实例：PayType=Serverless + RCU 透传（scale_* → *_capacity 映射）。"""
    class _FakeServerlessConfig:
        auto_pause = False
        scale_min = 0.5
        scale_max = 4
        switch_force = False

    mock_aliyun['attribute'] = _FakeAttribute(
        category='serverless_standard', serverless_config=_FakeServerlessConfig(),
    )
    drill_id = backup_drill_service.create_drill(_create_body())['id']
    with backup_drill_service.get_engine().begin() as conn:
        drill_repo.claim_pending(conn, drill_id)
    drill = drill_repo.get_drill(drill_id)

    class _FakeClient:
        pass

    monkeypatch.setattr(
        backup_drill_service.credential_repo, 'get_credential',
        lambda account_id: {'enabled': True},
    )
    monkeypatch.setattr(
        backup_drill_service.client_factory, 'get_rds_client',
        lambda account_id, credential, region: _FakeClient(),
    )

    captured = {}

    def fake_clone(client, params):
        captured.update(params)
        return 'rm-clone-1', 'order-1'

    def fake_poll(client, instance_id):
        return _FakeAttribute(status='Running')

    monkeypatch.setattr(backup_drill_service.rds, 'clone_db_instance', fake_clone)
    monkeypatch.setattr(backup_drill_service.rds, 'describe_instance_attribute', fake_poll)
    monkeypatch.setattr('app.service.backup_drill_service.time.sleep', lambda sec: None)

    backup_drill_service.run_clone_stage(drill)

    assert captured['pay_type'] == 'Serverless'
    assert captured['serverless_config'] == {
        'min_capacity': 0.5,
        'max_capacity': 4,
        'auto_pause': False,
        'switch_force': False,
    }
    # 报告口径字段：付费类型与 RCU 范围描述。
    stored = json.loads(drill_repo.get_drill(drill_id)['clone_params'])
    assert stored['clone_pay_type'] == 'Serverless（按 RCU 计费）'
    assert stored['clone_class_desc'] == 'RCU 0.5 ~ 4'
    assert drill_repo.get_drill(drill_id)['status'] == 'success'
