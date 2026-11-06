"""配置管理表访问。"""

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.infra.db import get_engine
from app.util.errors import ApiError
from app.util.web import response


def list_configs(scope: str = '', keyword: str = '') -> list[dict]:
    """全量配置列表，配置项数量有限，不分页。"""
    conditions: list[str] = []
    params: dict = {}
    if scope:
        conditions.append('config_scope = :scope')
        params['scope'] = scope
    if keyword:
        conditions.append('(config_key LIKE :keyword OR config_name LIKE :keyword)')
        params['keyword'] = f'%{keyword}%'

    where = f'WHERE {" AND ".join(conditions)}' if conditions else ''
    sql = f'''
        SELECT * FROM ops_config
        {where}
        ORDER BY config_scope, config_key
    '''
    with get_engine().connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        return [dict(row) for row in rows]


def get_by_key(config_key: str) -> dict | None:
    """按配置键精确查询。

    config_value 与 get_config 明文回填同口径：is_encrypt=1 的行解密后返回
    （解不开时 decrypt_value 降级原文并告警）。消费方拿到的始终是明文语义值，
    否则加密保存的 clouddm_api_key 等会以密文进入 json.loads 静默失败。
    """
    with get_engine().connect() as conn:
        row = conn.execute(
            text('SELECT * FROM ops_config WHERE config_key = :key'),
            {'key': config_key},
        ).mappings().first()
    if row is None:
        return None
    item = dict(row)
    if item.get('is_encrypt') == 1:
        # 延迟导入避免 service → infra 的反向依赖。
        from app.service.config_service import decrypt_value

        item['config_value'] = decrypt_value(item.get('config_value') or '')
    return item


def get_config(config_id: int) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            text('SELECT * FROM ops_config WHERE id = :id'),
            {'id': config_id},
        ).mappings().first()
    return dict(row) if row else None


def create_config(data: dict) -> int:
    sql = text('''
        INSERT INTO ops_config
            (config_name, config_scope, config_type, config_key, config_value,
             is_encrypt, create_user, description)
        VALUES
            (:config_name, :config_scope, :config_type, :config_key, :config_value,
             :is_encrypt, :create_user, :description)
    ''')
    try:
        with get_engine().begin() as conn:
            result = conn.execute(sql, data)
            return int(result.lastrowid)
    except IntegrityError as error:
        raise ApiError(
            code=response.CODE_CONFLICT,
            user_message='该模块下配置键已存在',
            message=f'duplicate config: scope={data["config_scope"]} key={data["config_key"]}',
            http_status=409,
        ) from error


def update_config(config_id: int, fields: dict) -> None:
    """按传入字段部分更新，updated_at 由数据库维护。"""
    allowed = ('config_name', 'config_scope', 'config_type', 'config_key',
               'config_value', 'is_encrypt', 'description')
    sets: list[str] = []
    params: dict = {'id': config_id}
    for key in allowed:
        if key in fields:
            sets.append(f'{key} = :{key}')
            params[key] = fields[key]
    if not sets:
        return

    sql = text(f'UPDATE ops_config SET {", ".join(sets)} WHERE id = :id')
    try:
        with get_engine().begin() as conn:
            result = conn.execute(sql, params)
            if result.rowcount == 0:
                raise ApiError(
                    code=response.CODE_NOT_FOUND,
                    user_message='配置项不存在',
                    message=f'config id not found: {config_id}',
                    http_status=404,
                )
    except IntegrityError as error:
        raise ApiError(
            code=response.CODE_CONFLICT,
            user_message='该模块下配置键已存在',
            message=f'duplicate config: id={config_id}',
            http_status=409,
        ) from error


def delete_config(config_id: int) -> None:
    with get_engine().begin() as conn:
        result = conn.execute(
            text('DELETE FROM ops_config WHERE id = :id'),
            {'id': config_id},
        )
        if result.rowcount == 0:
            raise ApiError(
                code=response.CODE_NOT_FOUND,
                user_message='配置项不存在',
                message=f'config id not found: {config_id}',
                http_status=404,
            )
