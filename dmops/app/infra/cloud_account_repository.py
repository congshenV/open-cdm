"""阿里云账号表访问。"""

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.infra.db import get_engine
from app.util.errors import ApiError
from app.util.web import response


def list_accounts(keyword: str = '', enabled: bool | None = None,
                  page: int = 1, page_size: int = 20) -> tuple[list[dict], int]:
    """账号列表，附带认证类型摘要。"""
    conditions: list[str] = []
    params: dict = {
        'offset': (page - 1) * page_size,
        'limit': page_size,
    }
    if keyword:
        conditions.append('(a.cloud_account_id LIKE :keyword OR a.name LIKE :keyword)')
        params['keyword'] = f'%{keyword}%'
    if enabled is not None:
        conditions.append('a.enabled = :enabled')
        params['enabled'] = 1 if enabled else 0

    where = f'WHERE {" AND ".join(conditions)}' if conditions else ''
    sql = f'''
        SELECT a.*, c.credential_type, c.enabled AS credential_enabled
        FROM ops_cloud_account a
        LEFT JOIN ops_cloud_credential c ON c.account_id = a.id
        {where}
        ORDER BY a.id DESC
        LIMIT :offset, :limit
    '''
    count_sql = f'SELECT COUNT(*) FROM ops_cloud_account a {where}'

    with get_engine().connect() as conn:
        total = conn.execute(text(count_sql), params).scalar() or 0
        rows = conn.execute(text(sql), params).mappings().all()

    return [dict(row) for row in rows], int(total)


def get_account(account_id: int) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            text('SELECT * FROM ops_cloud_account WHERE id = :id'),
            {'id': account_id},
        ).mappings().first()
    return dict(row) if row else None


def create_account(data: dict) -> int:
    sql = text('''
        INSERT INTO ops_cloud_account
            (cloud_account_id, name, description, default_region, enabled)
        VALUES
            (:cloud_account_id, :name, :description, :default_region, :enabled)
    ''')
    try:
        with get_engine().begin() as conn:
            result = conn.execute(sql, data)
            return int(result.lastrowid)
    except IntegrityError as error:
        raise ApiError(
            code=response.CODE_CONFLICT,
            user_message='账号已存在',
            message=f'duplicate cloud_account_id: {data["cloud_account_id"]}',
            http_status=409,
        ) from error


def update_account(account_id: int, fields: dict) -> None:
    """更新账号基础信息，并自增 config_version 使缓存失效。"""
    allowed = ('name', 'description', 'default_region', 'enabled')
    sets: list[str] = []
    params: dict = {'id': account_id}
    for key in allowed:
        if key in fields:
            sets.append(f'{key} = :{key}')
            params[key] = fields[key]
    if not sets:
        return

    sets.append('config_version = config_version + 1')
    sql = text(f'UPDATE ops_cloud_account SET {", ".join(sets)} WHERE id = :id')
    with get_engine().begin() as conn:
        result = conn.execute(sql, params)
        if result.rowcount == 0:
            raise ApiError(
                code=response.CODE_NOT_FOUND,
                user_message='账号不存在',
                message=f'account id not found: {account_id}',
                http_status=404,
            )


def delete_account(account_id: int) -> None:
    """删除账号。账号下仍有资源时拒绝删除。"""
    with get_engine().begin() as conn:
        resource_count = conn.execute(
            text('SELECT COUNT(*) FROM ops_resource WHERE account_id = :id'),
            {'id': account_id},
        ).scalar() or 0
        if resource_count > 0:
            raise ApiError(
                code=response.CODE_CONFLICT,
                user_message='账号下存在资源，不能删除',
                message=f'account {account_id} still has {resource_count} resources',
                http_status=409,
            )

        conn.execute(
            text('DELETE FROM ops_cloud_credential WHERE account_id = :id'),
            {'id': account_id},
        )
        result = conn.execute(
            text('DELETE FROM ops_cloud_account WHERE id = :id'),
            {'id': account_id},
        )
        if result.rowcount == 0:
            raise ApiError(
                code=response.CODE_NOT_FOUND,
                user_message='账号不存在',
                message=f'account id not found: {account_id}',
                http_status=404,
            )


def update_sync_status(account_id: int, status: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text('''
                UPDATE ops_cloud_account
                SET last_sync_at = NOW(), last_sync_status = :status
                WHERE id = :id
            '''),
            {'id': account_id, 'status': status},
        )
