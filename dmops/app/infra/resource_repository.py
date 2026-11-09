"""云资源表（当前为 RDS 实例）访问。"""

from sqlalchemy import bindparam, text

from app.infra.db import get_engine

# 同步时需要写入的资源字段。
_RESOURCE_FIELDS = (
    'instance_name',
    'engine',
    'engine_version',
    'instance_class',
    'category',
    'instance_type',
    'status',
    'pay_type',
    'network_type',
    'connection_string',
    'port',
    'vpc_id',
    'vswitch_id',
    'zone_id',
    'owner',
    'level',
    'prodline',
    'cpu',
    'memory_mb',
    'storage_gb',
    'disk_used_bytes',
    'storage_type',
    'create_time',
    'expire_time',
    'lock_mode',
    'deletion_protection',
    'master_instance_id',
)


def list_resources(account_id: int, region: str = '', keyword: str = '', status: str = '',
                   page: int = 1, page_size: int = 20) -> tuple[list[dict], int]:
    conditions = ['r.resource_type = :resource_type', 'r.account_id = :account_id']
    params: dict = {
        'resource_type': 'RDS_INSTANCE',
        'account_id': account_id,
        'offset': (page - 1) * page_size,
        'limit': page_size,
    }
    if region:
        conditions.append('r.region = :region')
        params['region'] = region
    if keyword:
        conditions.append('(r.cloud_id LIKE :keyword OR r.instance_name LIKE :keyword)')
        params['keyword'] = f'%{keyword}%'
    if status:
        conditions.append('r.status = :status')
        params['status'] = status

    where = ' AND '.join(conditions)
    sql = f'''
        SELECT r.*, a.cloud_account_id, a.name AS account_name
        FROM ops_resource r
        JOIN ops_cloud_account a ON a.id = r.account_id
        WHERE {where}
        ORDER BY r.region, r.cloud_id
        LIMIT :offset, :limit
    '''
    count_sql = f'SELECT COUNT(*) FROM ops_resource r WHERE {where}'

    with get_engine().connect() as conn:
        total = conn.execute(text(count_sql), params).scalar() or 0
        rows = conn.execute(text(sql), params).mappings().all()

    return [dict(row) for row in rows], int(total)


def get_resource(account_id: int, region: str, cloud_id: str) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            text('''
                SELECT r.*, a.cloud_account_id, a.name AS account_name
                FROM ops_resource r
                JOIN ops_cloud_account a ON a.id = r.account_id
                WHERE r.resource_type = 'RDS_INSTANCE'
                  AND r.account_id = :account_id
                  AND r.region = :region
                  AND r.cloud_id = :cloud_id
            '''),
            {'account_id': account_id, 'region': region, 'cloud_id': cloud_id},
        ).mappings().first()
    return dict(row) if row else None


def list_regions(account_id: int) -> list[str]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text('''
                SELECT DISTINCT region
                FROM ops_resource
                WHERE resource_type = 'RDS_INSTANCE' AND account_id = :account_id
            '''),
            {'account_id': account_id},
        ).all()
    return [row[0] for row in rows if row[0]]


def list_cloud_ids(account_id: int, region: str) -> set[str]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text('''
                SELECT cloud_id
                FROM ops_resource
                WHERE resource_type = 'RDS_INSTANCE'
                  AND account_id = :account_id
                  AND region = :region
            '''),
            {'account_id': account_id, 'region': region},
        ).all()
    return {row[0] for row in rows}


def upsert_resource(account_id: int, region: str, data: dict) -> None:
    """按 (resource_type, account_id, region, cloud_id) upsert 单条资源。"""
    with get_engine().begin() as conn:
        _upsert_one(conn, account_id, region, data)


def upsert_resources(account_id: int, region: str, items: list[dict]) -> None:
    """批量 upsert 一个地域的实例，共用一个事务，避免逐条建连接。"""
    if not items:
        return
    with get_engine().begin() as conn:
        for data in items:
            _upsert_one(conn, account_id, region, data)


def _upsert_one(conn, account_id: int, region: str, data: dict) -> None:
    """只更新 data 中出现的字段，避免列表同步把详情接口回填的 storage_gb 等字段清空。"""
    fields = [field for field in _RESOURCE_FIELDS if field in data]
    if not fields:
        return
    insert_columns = ['resource_type', 'account_id', 'region', 'cloud_id', *fields]
    insert_values = [':resource_type', ':account_id', ':region', ':cloud_id']
    insert_values.extend(f':{field}' for field in fields)
    update_clause = ', '.join(f'{field} = VALUES({field})' for field in fields)
    update_clause += ', last_sync_at = NOW()'

    sql = text(f'''
        INSERT INTO ops_resource
            ({', '.join(insert_columns)}, last_sync_at)
        VALUES
            ({', '.join(insert_values)}, NOW())
        ON DUPLICATE KEY UPDATE {update_clause}
    ''')

    params = {
        'resource_type': 'RDS_INSTANCE',
        'account_id': account_id,
        'region': region,
    }
    for field in fields:
        params[field] = data.get(field)
    params['cloud_id'] = data['cloud_id']

    conn.execute(sql, params)


def mark_missing(account_id: int, region: str, seen_cloud_ids: set[str]) -> int:
    """把本次同步未返回的实例标记为 Released，保留历史记录。"""
    base_sql = '''
        UPDATE ops_resource
        SET status = 'Released', last_sync_at = NOW()
        WHERE resource_type = 'RDS_INSTANCE'
          AND account_id = :account_id
          AND region = :region
          AND status <> 'Released'
    '''
    params: dict = {'account_id': account_id, 'region': region}

    if seen_cloud_ids:
        sql = text(base_sql + ' AND cloud_id NOT IN :seen').bindparams(
            bindparam('seen', expanding=True),
        )
        params['seen'] = list(seen_cloud_ids)
    else:
        sql = text(base_sql)

    with get_engine().begin() as conn:
        result = conn.execute(sql, params)
        return int(result.rowcount or 0)


def update_snapshot(account_id: int, region: str, cloud_id: str, data: dict) -> None:
    """详情接口返回后回写资源快照。"""
    allowed = (
        'instance_name', 'engine', 'engine_version', 'instance_class', 'category',
        'instance_type', 'status', 'pay_type', 'network_type', 'connection_string',
        'port', 'vpc_id', 'vswitch_id', 'zone_id', 'cpu', 'memory_mb', 'storage_gb',
        'storage_type', 'create_time', 'expire_time', 'lock_mode', 'deletion_protection',
        'master_instance_id',
    )
    sets: list[str] = []
    params: dict = {'account_id': account_id, 'region': region, 'cloud_id': cloud_id}
    for field in allowed:
        if field in data:
            sets.append(f'{field} = :{field}')
            params[field] = data[field]
    if not sets:
        return

    sets.append('last_sync_at = NOW()')
    sql = text(f'''
        UPDATE ops_resource
        SET {', '.join(sets)}
        WHERE resource_type = 'RDS_INSTANCE'
          AND account_id = :account_id
          AND region = :region
          AND cloud_id = :cloud_id
    ''')
    with get_engine().begin() as conn:
        conn.execute(sql, params)
