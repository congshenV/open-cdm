"""演练派生展示状态单测：待数据校验 → 数据校验完成 → 演练完成。"""

import sqlalchemy

from app.infra import backup_drill_repository as drill_repo
from app.service import backup_drill_service


def _insert_drill(conn, drill_no='DR261106201', status='success', offline_status=0):
    drill_id = drill_repo.insert_drill(conn, {
        'drill_no': drill_no,
        'account_id': 1,
        'region': 'cn-beijing',
        'source_instance_id': 'rm-src',
        'backup_id': '1',
        'backup_start_time': None,
        'backup_end_time': None,
        'clone_params': '{}',
        'target_tables': None,
        'status': status,
        'triggered_by': 'tester',
        'clone_started_at': None,
    })
    if offline_status:
        conn.execute(
            sqlalchemy.text('UPDATE ops_backup_drill SET offline_status = 1 WHERE id = :id'),
            {'id': drill_id},
        )
    return drill_id


def _insert_step(conn, drill_id, layer):
    drill_repo.insert_step(conn, {
        'drill_id': drill_id,
        'layer': layer,
        'target': 'x',
        'status': 'pass',
        'summary': '{}',
        'detail': None,
        'error': None,
        'cost_ms': 1,
    })


def test_display_status_flow(sqlite_engine):
    """克隆完成 → 待数据校验 → 两类校验齐 → 数据校验完成 → 下线 → 演练完成。"""
    engine = backup_drill_service.get_engine()
    with engine.begin() as conn:
        drill_id = _insert_drill(conn)

    # 克隆完成，未校验。
    assert backup_drill_service.get_drill(drill_id)['display_status'] == 'awaiting_verify'

    # 只有库表校验，仍待数据校验（两类均完成才算）。
    with engine.begin() as conn:
        _insert_step(conn, drill_id, 'AUTO')
    assert backup_drill_service.get_drill(drill_id)['display_status'] == 'awaiting_verify'

    # 表数据校验也完成 → 数据校验完成。
    with engine.begin() as conn:
        _insert_step(conn, drill_id, 'ROW')
    assert backup_drill_service.get_drill(drill_id)['display_status'] == 'verified'

    # 人工确认下线 → 演练完成。
    with engine.begin() as conn:
        conn.execute(
            sqlalchemy.text('UPDATE ops_backup_drill SET offline_status = 1 WHERE id = :id'),
            {'id': drill_id},
        )
    assert backup_drill_service.get_drill(drill_id)['display_status'] == 'done'


def test_display_status_offline_outranks_verify(sqlite_engine):
    """未校验直接下线：下线优先 → 演练完成。"""
    engine = backup_drill_service.get_engine()
    with engine.begin() as conn:
        drill_id = _insert_drill(conn, drill_no='DR261106202', offline_status=1)

    assert backup_drill_service.get_drill(drill_id)['display_status'] == 'done'


def test_display_status_passthrough(sqlite_engine):
    """非 success 状态原样透传。"""
    engine = backup_drill_service.get_engine()
    cases = {
        'DR261106203': ('pending', 'pending'),
        'DR261106204': ('cloning', 'cloning'),
        'DR261106205': ('failed', 'failed'),
        'DR261106206': ('canceled', 'canceled'),
    }
    for drill_no, (status, _expected) in cases.items():
        with engine.begin() as conn:
            drill_id = _insert_drill(conn, drill_no=drill_no, status=status)
        assert backup_drill_service.get_drill(drill_id)['display_status'] == status


def test_list_drills_carries_display_status(sqlite_engine):
    """列表接口批量派生：一次查询带出各行的 display_status。"""
    engine = backup_drill_service.get_engine()
    with engine.begin() as conn:
        unverified = _insert_drill(conn, drill_no='DR261106207')
        verified = _insert_drill(conn, drill_no='DR261106208')
        _insert_step(conn, unverified, 'AUTO')
        _insert_step(conn, verified, 'AUTO')
        _insert_step(conn, verified, 'ROW')

    data = backup_drill_service.list_drills()
    by_no = {item['drill_no']: item for item in data['items']}
    assert by_no['DR261106207']['display_status'] == 'awaiting_verify'
    assert by_no['DR261106208']['display_status'] == 'verified'
