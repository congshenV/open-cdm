"""阿里云账号认证表访问。"""

from sqlalchemy import text

from app.infra.db import get_engine

# 认证表的全部可写字段。secret 字段当前明文存储，后续再统一加密。
_COLUMNS = (
    'credential_type',
    'access_key_id',
    'access_key_secret',
    'security_token',
    'role_arn',
    'role_session_name',
    'role_session_expiration',
    'external_id',
    'sts_endpoint',
    'oidc_provider_arn',
    'oidc_token_file_path',
    'credentials_uri',
    'profile_name',
    'enabled',
)


def get_credential(account_id: int) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            text('SELECT * FROM ops_cloud_credential WHERE account_id = :account_id'),
            {'account_id': account_id},
        ).mappings().first()
    return dict(row) if row else None


def upsert_credential(account_id: int, data: dict) -> None:
    """新增或覆盖账号认证配置，version 自增。

    调用方需保证 data 已包含全部字段（更新时未填写的 secret 由 service 层沿用旧值）。
    """
    insert_columns = ['account_id', *_COLUMNS, 'version']
    insert_values = [f':{column}' for column in insert_columns]
    update_clause = ', '.join(f'{column} = VALUES({column})' for column in _COLUMNS)
    update_clause += ', version = version + 1'

    sql = text(f'''
        INSERT INTO ops_cloud_credential ({', '.join(insert_columns)})
        VALUES ({', '.join(insert_values)})
        ON DUPLICATE KEY UPDATE {update_clause}
    ''')

    params = {'account_id': account_id, 'version': 1}
    for column in _COLUMNS:
        params[column] = data.get(column)

    with get_engine().begin() as conn:
        conn.execute(sql, params)


def delete_credential(account_id: int) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text('DELETE FROM ops_cloud_credential WHERE account_id = :account_id'),
            {'account_id': account_id},
        )


def update_verify_result(account_id: int, error: str = '') -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text('''
                UPDATE ops_cloud_credential
                SET last_verified_at = NOW(), last_verify_error = :error
                WHERE account_id = :account_id
            '''),
            {'account_id': account_id, 'error': error[:1024]},
        )
