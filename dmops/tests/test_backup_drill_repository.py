"""drill repo 状态机与 SQL 行为单测（SQLite 替身）。

统一用 _engine() 访问（conftest 替换的是模块属性，
from-import 的本地引用不会被替换）。
"""

import datetime

import sqlalchemy

from app.infra import backup_drill_repository as drill_repo


def _engine():
    return drill_repo.get_engine()


def _insert_drill(conn, drill_no='DR261104001', status='pending', **extra):
    """插入基线记录；insert_drill 列清单之外的字段（offline/实例 ID 等）补 UPDATE。"""
    row = {
        'drill_no': drill_no,
        'account_id': 1,
        'region': 'cn-hangzhou',
        'source_instance_id': 'rm-xxx',
        'backup_id': '3222768592',
        'backup_start_time': None,
        'backup_end_time': None,
        'clone_params': '{}',
        'target_tables': None,
        'status': status,
        'triggered_by': 'tester',
        'clone_started_at': None,
    }
    drill_id = drill_repo.insert_drill(conn, row)
    update_fields = {
        key: value for key, value in extra.items() if key not in row
    }
    if update_fields:
        sets = ', '.join(f'{key} = :{key}' for key in update_fields)
        conn.execute(
            sqlalchemy.text(f'UPDATE ops_backup_drill SET {sets} WHERE id = :id'),
            {'id': drill_id, **update_fields},
        )
    return drill_id


def _conn():
    return _engine().connect()


def test_insert_and_get(sqlite_engine):
    with _engine().begin() as conn:
        drill_id = _insert_drill(conn)

    drill = drill_repo.get_drill(drill_id)
    assert drill is not None
    assert drill['drill_no'] == 'DR261104001'
    assert drill['status'] == 'pending'
    assert drill['offline_status'] == 0


def test_next_drill_no_sequence(sqlite_engine):
    with _engine().begin() as conn:
        assert drill_repo.next_drill_no(conn).startswith('DR')
        first = drill_repo.next_drill_no(conn)
        # 空表时返回当日 001。
        assert first.endswith('001')
        _insert_drill(conn, drill_no=first)
        second = drill_repo.next_drill_no(conn)
        assert second.endswith('002')


def test_next_drill_no_not_regressed_by_other_days(sqlite_engine):
    """只看当天前缀，其他日期的编号不影响当日序号。"""
    with _engine().begin() as conn:
        _insert_drill(conn, drill_no='DR269901999')
        first = drill_repo.next_drill_no(conn)
        assert first.endswith('001')


def test_claim_pending_success(sqlite_engine):
    with _engine().begin() as conn:
        drill_id = _insert_drill(conn)

    with _engine().begin() as conn:
        assert drill_repo.claim_pending(conn, drill_id) is True

    drill = drill_repo.get_drill(drill_id)
    assert drill['status'] == 'cloning'
    assert drill['clone_started_at'] is not None


def test_claim_pending_rejects_canceled(sqlite_engine):
    """取消与抢占竞争：canceled 后抢占必须失败。"""
    with _engine().begin() as conn:
        drill_id = _insert_drill(conn)
    assert drill_repo.cancel_drill(drill_id) is True

    with _engine().begin() as conn:
        assert drill_repo.claim_pending(conn, drill_id) is False


def test_cancel_only_pending(sqlite_engine):
    """cloning（克隆已发出）后取消必须失败。"""
    with _engine().begin() as conn:
        drill_id = _insert_drill(conn)
    with _engine().begin() as conn:
        drill_repo.claim_pending(conn, drill_id)

    assert drill_repo.cancel_drill(drill_id) is False
    assert drill_repo.get_drill(drill_id)['status'] == 'cloning'


def test_finish_drill_only_from_active(sqlite_engine):
    """终态记录不能再次推进（幂等保护）。"""
    with _engine().begin() as conn:
        drill_id = _insert_drill(conn)
    with _engine().begin() as conn:
        drill_repo.finish_drill(conn, drill_id, drill_repo.STATUS_FAILED, 'boom')

    # 已 failed，再来一次 success 不能覆盖。
    with _engine().begin() as conn:
        drill_repo.finish_drill(conn, drill_id, drill_repo.STATUS_SUCCESS)
    assert drill_repo.get_drill(drill_id)['status'] == 'failed'


def test_mark_clone_submitted(sqlite_engine):
    with _engine().begin() as conn:
        drill_id = _insert_drill(conn)
    with _engine().begin() as conn:
        drill_repo.mark_clone_submitted(conn, drill_id, 'rm-clone-1')

    drill = drill_repo.get_drill(drill_id)
    assert drill['clone_instance_id'] == 'rm-clone-1'


def test_confirm_offline_requires_clone_instance(sqlite_engine):
    """未产生克隆实例的（canceled）记录不能确认下线。"""
    with _engine().begin() as conn:
        drill_id = _insert_drill(conn)
    assert drill_repo.cancel_drill(drill_id) is True

    assert drill_repo.confirm_offline(drill_id, 'ops') is False


def test_confirm_offline_success_and_idempotent(sqlite_engine):
    with _engine().begin() as conn:
        drill_id = _insert_drill(conn, status='success', clone_instance_id='rm-clone-1',
                                 finished_at='2026-11-04 10:00:00')

    assert drill_repo.confirm_offline(drill_id, 'ops') is True
    drill = drill_repo.get_drill(drill_id)
    assert drill['offline_status'] == 1
    assert drill['offline_confirmed_by'] == 'ops'

    # 重复确认失败。
    assert drill_repo.confirm_offline(drill_id, 'ops2') is False


def test_list_drills_offline_filter(sqlite_engine):
    """offline 过滤：未确认下线的终态克隆记录才出现。"""
    with _engine().begin() as conn:
        done_unconfirmed = _insert_drill(
            conn, drill_no='DR261104001', status='success', clone_instance_id='rm-clone-1',
            finished_at='2026-11-04 10:00:00',
        )
        _insert_drill(
            conn, drill_no='DR261104002', status='success', clone_instance_id='rm-clone-2',
            offline_status=1, finished_at='2026-11-04 11:00:00',
        )
        _insert_drill(conn, drill_no='DR261104003', status='canceled',
                      finished_at='2026-11-04 12:00:00')

    rows, total = drill_repo.list_drills(offline=True)
    assert total == 1
    assert rows[0]['id'] == done_unconfirmed


def test_count_active_filters(sqlite_engine):
    with _engine().begin() as conn:
        _insert_drill(conn, drill_no='DR261104001', status='pending')
        _insert_drill(conn, drill_no='DR261104002', status='cloning', account_id=1)
        _insert_drill(conn, drill_no='DR261104003', status='success',
                      source_instance_id='rm-other', finished_at='2026-11-04 10:00:00')

    with _engine().connect() as conn:
        assert drill_repo.count_active(conn) == 2
        assert drill_repo.count_active_by_instance(conn, 1, 'rm-xxx') == 2
        assert drill_repo.count_active_by_instance(conn, 1, 'rm-other') == 0


def test_list_stale_cloning(sqlite_engine):
    """心跳超时的 cloning 记录才能被接管（阈值折算为 updated_at < deadline）。"""
    import datetime

    # 心跳时间戳与 repo 写入口径一致（_now 为本地时间 +8），相对偏移构造两态。
    now = drill_repo._now()
    stale_at = now - datetime.timedelta(minutes=30)
    fresh_at = now + datetime.timedelta(minutes=30)

    with _engine().begin() as conn:
        _insert_drill(conn, drill_no='DR261104001', status='cloning',
                      clone_started_at='2026-11-04 09:00:00')
        _insert_drill(conn, drill_no='DR261104002', status='cloning',
                      clone_started_at='2026-11-04 09:10:00')
        # 001 心跳已超时，002 刚心跳过。
        conn.execute(sqlalchemy.text(
            "UPDATE ops_backup_drill SET updated_at = :ts WHERE drill_no = 'DR261104001'"
        ), {'ts': stale_at.strftime('%Y-%m-%d %H:%M:%S')})
        conn.execute(sqlalchemy.text(
            "UPDATE ops_backup_drill SET updated_at = :ts WHERE drill_no = 'DR261104002'"
        ), {'ts': fresh_at.strftime('%Y-%m-%d %H:%M:%S')})

    stale = drill_repo.list_stale_cloning(heartbeat_timeout_sec=600)
    assert [row['drill_no'] for row in stale] == ['DR261104001']
