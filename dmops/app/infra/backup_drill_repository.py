"""备份恢复演练表访问。

表结构见 docs/backup-drill-design.md §5（DDL 由 DBA 预建）。
只做手写 SQL 与行组装，业务规则在 service 层。
"""

import datetime
import re

from sqlalchemy import bindparam, text

from app.infra.db import get_engine

# 一期状态机：pending（未提交克隆）→ cloning（克隆请求已发出）→ success | failed；
# canceled 仅 pending 可达。comparing/partial 二期引入。
STATUS_PENDING = 'pending'
STATUS_CLONING = 'cloning'
STATUS_SUCCESS = 'success'
STATUS_FAILED = 'failed'
STATUS_CANCELED = 'canceled'

# 未终态（worker 需要扫描推进的状态）与终态。
ACTIVE_STATUSES = (STATUS_PENDING, STATUS_CLONING)
TERMINAL_STATUSES = (STATUS_SUCCESS, STATUS_FAILED, STATUS_CANCELED)
_ACTIVE_LIST = '(' + ', '.join(f"'{item}'" for item in ACTIVE_STATUSES) + ')'
_TERMINAL_LIST = '(' + ', '.join(f"'{item}'" for item in TERMINAL_STATUSES) + ')'

# 主表查询列。
_DRILL_COLUMNS = '''id, drill_no, account_id, region, source_instance_id, source_ds_id,
    backup_id, backup_start_time, backup_end_time, clone_instance_id, clone_ds_id,
    clone_params, target_tables, status, error_message, triggered_by,
    clone_started_at, clone_finished_at, compare_started_at, compare_finished_at,
    finished_at, offline_status, offline_confirmed_at, offline_confirmed_by,
    created_at, updated_at'''


def next_drill_no(conn, for_update: bool = True) -> str:
    """生成下一条演练编号：DR + yyMMdd + 3 位当日序号。

    create 路径必须在与插入同一事务中调用（取号行持有 FOR UPDATE 锁到事务结束），
    罕见的跨事务并发冲突由 uk_drill_no 唯一键兜底。
    弹窗预填用的只读推算（peek_next_drill_no）传 for_update=False。
    SQLite（单测替身）不支持 FOR UPDATE，按方言降级。
    """
    prefix = f'DR{datetime.datetime.now():%y%m%d}'
    lock = '' if for_update is False or _is_sqlite(conn) else ' FOR UPDATE'
    row = conn.execute(
        text(
            'SELECT drill_no FROM ops_backup_drill WHERE drill_no LIKE :prefix '
            f'ORDER BY drill_no DESC LIMIT 1{lock}'
        ),
        {'prefix': f'{prefix}%'},
    ).first()
    if row is None or row[0] is None:
        return f'{prefix}001'
    match = re.search(r'(\d{3})$', str(row[0]))
    if match is None:
        return f'{prefix}001'
    return f'{prefix}{int(match.group(1)) + 1:03d}'


def peek_next_drill_no() -> str:
    """只读推算下一条编号（不加锁），供发起弹窗预填；真正取号在 create 事务内。"""
    with get_engine().connect() as conn:
        return next_drill_no(conn, for_update=False)


def insert_drill(conn, drill: dict) -> int:
    """插入演练主记录，返回自增 id。字段由 service 层组装并校验完毕。"""
    result = conn.execute(
        text('''
            INSERT INTO ops_backup_drill
                (drill_no, account_id, region, source_instance_id, backup_id,
                 backup_start_time, backup_end_time, clone_params, target_tables,
                 status, triggered_by, clone_started_at)
            VALUES
                (:drill_no, :account_id, :region, :source_instance_id, :backup_id,
                 :backup_start_time, :backup_end_time, :clone_params, :target_tables,
                 :status, :triggered_by, :clone_started_at)
        '''),
        drill,
    )
    return int(result.lastrowid or 0)


def get_drill(drill_id: int) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            text(f'SELECT {_DRILL_COLUMNS} FROM ops_backup_drill WHERE id = :id'),
            {'id': drill_id},
        ).mappings().first()
    return dict(row) if row else None


def get_drill_by_no(drill_no: str) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            text(f'SELECT {_DRILL_COLUMNS} FROM ops_backup_drill WHERE drill_no = :drill_no'),
            {'drill_no': drill_no},
        ).mappings().first()
    return dict(row) if row else None


def list_drills(account_id: int = 0, instance_id: str = '', status: str = '',
                offline: bool = False, page: int = 1, page_size: int = 20) -> tuple[list[dict], int]:
    """演练列表，按 id 倒序。offline=True 只看待下线（未确认下线且已产生克隆实例的终态记录）。"""
    conditions: list[str] = []
    params: dict = {'offset': (page - 1) * page_size, 'limit': page_size}
    if account_id:
        conditions.append('account_id = :account_id')
        params['account_id'] = account_id
    if instance_id:
        conditions.append('source_instance_id = :instance_id')
        params['instance_id'] = instance_id
    if status:
        conditions.append('status = :status')
        params['status'] = status
    if offline:
        conditions.append(f'status IN {_TERMINAL_LIST}')
        conditions.append('clone_instance_id IS NOT NULL')
        conditions.append('offline_status = 0')

    where = f'WHERE {" AND ".join(conditions)}' if conditions else ''
    with get_engine().connect() as conn:
        total = conn.execute(
            text(f'SELECT COUNT(*) FROM ops_backup_drill {where}'), params,
        ).scalar() or 0
        rows = conn.execute(
            text(f'''
                SELECT {_DRILL_COLUMNS}
                FROM ops_backup_drill {where}
                ORDER BY id DESC
                LIMIT :offset, :limit
            '''),
            params,
        ).mappings().all()
    return [dict(row) for row in rows], int(total)


def count_active(conn, exclude_id: int = 0) -> int:
    """未终态演练条数（全局并发统计）。exclude_id 用于状态推进时排除自身。"""
    sql = f'SELECT COUNT(*) FROM ops_backup_drill WHERE status IN {_ACTIVE_LIST}'
    params: dict = {}
    if exclude_id:
        sql += ' AND id <> :exclude_id'
        params['exclude_id'] = exclude_id
    return int(conn.execute(text(sql), params).scalar() or 0)


def count_active_by_instance(conn, account_id: int, instance_id: str, exclude_id: int = 0) -> int:
    """同一实例的未终态演练条数（同实例串行约束）。"""
    sql = f'''
        SELECT COUNT(*) FROM ops_backup_drill
        WHERE status IN {_ACTIVE_LIST}
          AND account_id = :account_id AND source_instance_id = :instance_id
    '''
    params: dict = {'account_id': account_id, 'instance_id': instance_id}
    if exclude_id:
        sql += ' AND id <> :exclude_id'
        params['exclude_id'] = exclude_id
    return int(conn.execute(text(sql), params).scalar() or 0)


def claim_pending(conn, drill_id: int) -> bool:
    """pending → cloning 的抢占式推进，返回是否成功。

    条件更新防并发：取消（canceled）与抢占在两条连接上竞争同一条 pending 记录，
    只有一方成功。
    """
    result = conn.execute(
        text('''
            UPDATE ops_backup_drill
            SET status = 'cloning', clone_started_at = :now, updated_at = :now
            WHERE id = :id AND status = 'pending'
        '''),
        {'id': drill_id, 'now': _now()},
    )
    return bool(result.rowcount)


def mark_clone_submitted(conn, drill_id: int, clone_instance_id: str) -> None:
    """克隆请求发出、拿到克隆实例 ID 后立即落库——后续无论成败都可追溯。"""
    conn.execute(
        text('''
            UPDATE ops_backup_drill
            SET clone_instance_id = :clone_instance_id, updated_at = :now
            WHERE id = :id
        '''),
        {'id': drill_id, 'clone_instance_id': clone_instance_id, 'now': _now()},
    )


def heartbeat(conn, drill_id: int) -> None:
    """克隆轮询中的心跳；updated_at 超过心跳窗口的 cloning 记录可被重新抢占。"""
    conn.execute(
        text('UPDATE ops_backup_drill SET updated_at = :now WHERE id = :id'),
        {'id': drill_id, 'now': _now()},
    )


def finish_drill(conn, drill_id: int, status: str, error_message: str = '') -> None:
    """落终态（success/failed/canceled），补 finished_at。只允许从活动态推进。"""
    conn.execute(
        text(f'''
            UPDATE ops_backup_drill
            SET status = :status, error_message = :error_message,
                clone_finished_at = :now, finished_at = :now, updated_at = :now
            WHERE id = :id AND status IN {_ACTIVE_LIST}
        '''),
        {'id': drill_id, 'status': status, 'error_message': error_message, 'now': _now()},
    )


def cancel_drill(drill_id: int) -> bool:
    """取消演练：仅 pending 可取消（CloneDBInstance 发出前），条件更新防并发。"""
    with get_engine().begin() as conn:
        result = conn.execute(
            text('''
                UPDATE ops_backup_drill
                SET status = 'canceled', finished_at = :now, updated_at = :now
                WHERE id = :id AND status = 'pending'
            '''),
            {'id': drill_id, 'now': _now()},
        )
        return bool(result.rowcount)


def update_ds_id(conn, drill_id: int, target: str, ds_id: int) -> None:
    """注册成功后回写演练表的数据源 ID（source→source_ds_id，clone→clone_ds_id）。"""
    column = 'source_ds_id' if target == 'source' else 'clone_ds_id'
    conn.execute(
        text(f'''
            UPDATE ops_backup_drill
            SET {column} = :ds_id, updated_at = :now
            WHERE id = :id
        '''),
        {'id': drill_id, 'ds_id': ds_id, 'now': _now()},
    )


def confirm_offline(drill_id: int, operator: str) -> bool:
    """人工确认下线：克隆实例（与二期数据源）已释放。仅未确认的终态克隆记录可确认。"""
    with get_engine().begin() as conn:
        result = conn.execute(
            text(f'''
                UPDATE ops_backup_drill
                SET offline_status = 1, offline_confirmed_at = :now,
                    offline_confirmed_by = :operator, updated_at = :now
                WHERE id = :id
                  AND offline_status = 0
                  AND clone_instance_id IS NOT NULL
                  AND status IN {_TERMINAL_LIST}
            '''),
            {'id': drill_id, 'operator': operator, 'now': _now()},
        )
        return bool(result.rowcount)


# ---------------------------------------------------------------------------
# 校验步骤与差异（§5 steps/diffs 表；半自动校验按触发时间追加，历史保留）。
# ---------------------------------------------------------------------------

def insert_step(conn, step: dict) -> int:
    """插入一条校验步骤汇总（AUTO/ROW），返回自增 id。"""
    result = conn.execute(
        text('''
            INSERT INTO ops_backup_drill_step
                (drill_id, layer, target, status, summary, detail, error, cost_ms)
            VALUES
                (:drill_id, :layer, :target, :status, :summary, :detail, :error, :cost_ms)
        '''),
        step,
    )
    return int(result.lastrowid or 0)


def insert_diffs(conn, diffs: list[dict]) -> None:
    """批量插入校验差异明细。"""
    if not diffs:
        return
    conn.execute(
        text('''
            INSERT INTO ops_backup_drill_diff
                (drill_id, step_id, layer, item_type, target, attempt_no, status,
                 source_value, clone_value, note)
            VALUES
                (:drill_id, :step_id, :layer, :item_type, :target, :attempt_no, :status,
                 :source_value, :clone_value, :note)
        '''),
        diffs,
    )


def count_steps_by_drills(drill_ids: list[int]) -> dict[int, dict[str, int]]:
    """按演练批量统计校验步骤数（按 layer 分组）。

    列表页派生展示状态用（一次 IN 查询，避免每行单独查 steps）。
    返回 {drill_id: {'AUTO': n, 'ROW': n}}。
    """
    if not drill_ids:
        return {}
    sql = text('''
        SELECT drill_id, layer, COUNT(*) AS cnt
        FROM ops_backup_drill_step
        WHERE drill_id IN :ids
        GROUP BY drill_id, layer
    ''').bindparams(bindparam('ids', expanding=True))
    with get_engine().connect() as conn:
        rows = conn.execute(sql, {'ids': list(drill_ids)}).all()
    result: dict[int, dict[str, int]] = {}
    for drill_id, layer, cnt in rows:
        result.setdefault(int(drill_id), {})[str(layer)] = int(cnt)
    return result


def list_steps(drill_id: int) -> list[dict]:
    """校验步骤历史（新→旧），前端展示最近一次为主、历史可展开。"""
    sql = '''
        SELECT id, drill_id, layer, target, status, summary, detail, error, cost_ms, created_at
        FROM ops_backup_drill_step
        WHERE drill_id = :drill_id
        ORDER BY id DESC
    '''
    with get_engine().connect() as conn:
        rows = conn.execute(text(sql), {'drill_id': drill_id}).mappings().all()
    return [dict(row) for row in rows]


def list_diffs(drill_id: int, step_id: int = 0) -> list[dict]:
    """某次步骤的差异明细（step_id=0 取全部）。"""
    conditions = ['drill_id = :drill_id']
    params: dict = {'drill_id': drill_id}
    if step_id:
        conditions.append('step_id = :step_id')
        params['step_id'] = step_id
    sql = f'''
        SELECT id, drill_id, step_id, layer, item_type, target, attempt_no, status,
               source_value, clone_value, note, created_at
        FROM ops_backup_drill_diff
        WHERE {' AND '.join(conditions)}
        ORDER BY id
    '''
    with get_engine().connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(row) for row in rows]

def list_pending_jobs(limit: int = 10) -> list[dict]:
    """worker 扫描待提交克隆的 pending 记录。"""
    sql = f'''
        SELECT {_DRILL_COLUMNS}
        FROM ops_backup_drill
        WHERE status = 'pending'
        ORDER BY id
        LIMIT :limit
    '''
    with get_engine().connect() as conn:
        rows = conn.execute(text(sql), {'limit': limit}).mappings().all()
    return [dict(row) for row in rows]


def list_stale_cloning(heartbeat_timeout_sec: int) -> list[dict]:
    """心跳超时的 cloning 记录：进程崩溃后 worker 重新接管续跑，按最早优先。

    阈值折算成与写入同口径的本地时间字面量传参（不依赖 MySQL 的
    NOW()/TIMESTAMPDIFF），与 dmops 连接的会话时区设置无关。
    """
    deadline = _now() - datetime.timedelta(seconds=heartbeat_timeout_sec)
    sql = f'''
        SELECT {_DRILL_COLUMNS}
        FROM ops_backup_drill
        WHERE status = 'cloning'
          AND updated_at < :deadline
        ORDER BY id
        LIMIT 100
    '''
    with get_engine().connect() as conn:
        rows = conn.execute(text(sql), {'deadline': deadline}).mappings().all()
    return [dict(row) for row in rows]


def _is_sqlite(conn) -> bool:
    """单测替身是 SQLite，生产恒为 MySQL；只在这里感知方言差异。"""
    return conn.dialect.name == 'sqlite'


def _now() -> datetime.datetime:
    """与库会话时区一致的本地时间（+8）。

    MySQL DATETIME 无时区，ops_* 表的 created_at 等默认值走库会话时区（北京），
    dmops 写入的业务时间戳必须同口径，否则同一条记录两种时区混存；
    前端原样展示字符串，不做任何时区转换。
    """
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=8)
