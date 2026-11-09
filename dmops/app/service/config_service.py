"""配置管理业务。

配置值语义参考 dms 的 dms_common_config：按 config_type 做类型校验，
is_encrypt=true 的项 AES-256-CBC 加密存储（密文 base64(iv+cipher)，与 dms 对齐）。
列表脱敏返回，详情解密返回明文供编辑回填。
"""

import base64
import json
import logging
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app import config
from app.infra import config_repository as config_repo
from app.util.convert import (
    clean_str as _clean_str,
    is_blank as _is_blank,
    time_to_str as _time_to_str,
    to_bool as _to_bool,
)
from app.util.errors import ApiError
from app.util.web import request_scope, response

logger = logging.getLogger(__name__)

# 模块作用域。当前只分这三类，后续有需要在接口语义不变的前提下扩充。
CONFIG_SCOPES = ('base', 'rds', 'redis')

# 配置值支持的数据类型。
CONFIG_TYPES = ('str', 'int', 'float', 'bool', 'str_list', 'int_list', 'json', 'json_list')

# 列表里加密项的展示占位，前端原样展示，编辑时用详情接口取明文。
MASKED_VALUE = '******'

# AES-256-CBC 的块大小（字节），密钥要求 32 字节。
_AES_BLOCK_SIZE = 16
_AES_KEY_SIZE = 32


def _load_encrypt_key() -> bytes:
    """读取加密密钥。密钥未配置或长度不对属于部署错误，直接 500 暴露出来。"""
    secret = config.Config.encrypt_secret
    if _is_blank(secret):
        raise ApiError(
            code=response.CODE_INTERNAL_ERROR,
            user_message='服务端未配置加密密钥，不能操作加密配置',
            message='DMOPS_CONFIG_ENCRYPT_SECRET is empty',
            http_status=500,
        )
    key = secret.encode('utf-8')
    if len(key) != _AES_KEY_SIZE:
        raise ApiError(
            code=response.CODE_INTERNAL_ERROR,
            user_message='服务端加密密钥长度不正确',
            message='DMOPS_CONFIG_ENCRYPT_SECRET must be 32 bytes',
            http_status=500,
        )
    return key


def encrypt_value(plain: str) -> str:
    """AES-256-CBC 加密，密文格式 base64(iv + cipher)，与 dms 的 crypt.py 对齐。"""
    iv = os.urandom(_AES_BLOCK_SIZE)
    pad_len = _AES_BLOCK_SIZE - len(plain.encode('utf-8')) % _AES_BLOCK_SIZE
    padded = plain.encode('utf-8') + bytes([pad_len]) * pad_len
    encryptor = Cipher(algorithms.AES(_load_encrypt_key()), modes.CBC(iv)).encryptor()
    cipher_bytes = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + cipher_bytes).decode('utf-8')


def decrypt_value(encrypted: str) -> str:
    """解密 base64(iv + cipher)。密钥轮换等原因解不开时降级返回原文，不阻塞列表。"""
    try:
        raw = base64.b64decode(encrypted)
        iv = raw[:_AES_BLOCK_SIZE]
        cipher_bytes = raw[_AES_BLOCK_SIZE:]
        decryptor = Cipher(algorithms.AES(_load_encrypt_key()), modes.CBC(iv)).decryptor()
        padded = decryptor.update(cipher_bytes) + decryptor.finalize()
        pad_len = padded[-1]
        if not 1 <= pad_len <= _AES_BLOCK_SIZE:
            return encrypted
        return padded[:-pad_len].decode('utf-8')
    except Exception as error:
        logger.warning('[dmops] 配置解密失败，按原文返回: %s', error)
        return encrypted


def _normalize_value(config_type: str, value: str) -> str:
    """按类型校验配置值并规范化存储文本，类型不支持或值非法都抛 400。"""
    if config_type == 'str':
        return value
    if config_type in ('int', 'float', 'bool'):
        try:
            if config_type == 'int':
                return str(int(value.strip()))
            if config_type == 'float':
                return str(float(value.strip()))
            lowered = value.strip().lower()
            if lowered not in ('true', 'false', '1', '0', 'yes', 'no'):
                raise ValueError(value)
            return 'true' if lowered in ('true', '1', 'yes') else 'false'
        except ValueError as error:
            raise _invalid_value_error(config_type) from error
    return _normalize_json_value(config_type, value)


def _normalize_json_value(config_type: str, value: str) -> str:
    try:
        parsed = json.loads(value)
    except ValueError as error:
        raise _invalid_value_error(config_type) from error

    if config_type == 'json':
        if isinstance(parsed, list):
            raise _invalid_value_error(config_type)
        return json.dumps(parsed, ensure_ascii=False)
    if config_type == 'json_list':
        if not isinstance(parsed, list):
            raise _invalid_value_error(config_type)
        return json.dumps(parsed, ensure_ascii=False)
    if config_type == 'str_list':
        if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
            raise _invalid_value_error(config_type)
        return json.dumps(parsed, ensure_ascii=False)
    if config_type == 'int_list':
        if not isinstance(parsed, list) or any(not isinstance(item, int) or isinstance(item, bool) for item in parsed):
            raise _invalid_value_error(config_type)
        return json.dumps(parsed)
    raise ApiError(
        response.CODE_BAD_REQUEST,
        f'不支持的配置类型: {config_type}',
        f'unsupported config_type: {config_type}',
        400,
    )


def _invalid_value_error(config_type: str) -> ApiError:
    return ApiError(
        response.CODE_BAD_REQUEST,
        f'配置值不符合类型 {config_type} 的格式',
        f'config value not valid for type {config_type}',
        400,
    )


def _item(row: dict, mask_value: bool) -> dict:
    """DB 行转接口对象。mask_value=true 时加密项的值脱敏为占位符。"""
    is_encrypt = bool(row.get('is_encrypt'))
    config_value = row.get('config_value') or ''
    if is_encrypt:
        config_value = MASKED_VALUE if mask_value else decrypt_value(config_value)
    return {
        'id': row['id'],
        'config_name': row.get('config_name') or '',
        'config_scope': row.get('config_scope') or '',
        'config_type': row.get('config_type') or '',
        'config_key': row.get('config_key') or '',
        'config_value': config_value,
        'is_encrypt': is_encrypt,
        'create_user': row.get('create_user') or '',
        'description': row.get('description') or '',
        'created_at': _time_to_str(row.get('created_at')),
        'updated_at': _time_to_str(row.get('updated_at')),
    }


def _validate_common_fields(payload: dict) -> None:
    """create/update 共用的字段校验，表单始终全量提交，语义与 dms 一致。"""
    scope = _clean_str(payload.get('config_scope'))
    if scope not in CONFIG_SCOPES:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            f'模块必须是 {"/".join(CONFIG_SCOPES)} 之一',
            f'invalid config_scope: {scope}',
            400,
        )
    config_type = _clean_str(payload.get('config_type'))
    if config_type not in CONFIG_TYPES:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            f'数据类型必须是 {"/".join(CONFIG_TYPES)} 之一',
            f'invalid config_type: {config_type}',
            400,
        )
    if _is_blank(payload.get('config_name')):
        raise ApiError(response.CODE_BAD_REQUEST, '配置名不能为空', 'config_name is required', 400)
    if _is_blank(payload.get('config_key')):
        raise ApiError(response.CODE_BAD_REQUEST, '配置键不能为空', 'config_key is required', 400)
    if _is_blank(payload.get('config_value')):
        raise ApiError(response.CODE_BAD_REQUEST, '配置值不能为空', 'config_value is required', 400)


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

def list_configs(scope: str = '', keyword: str = '') -> list[dict]:
    """全量列表，无分页。加密项的值脱敏。"""
    rows = config_repo.list_configs(scope=scope, keyword=keyword)
    return [_item(row, mask_value=True) for row in rows]


def get_config(config_id: int) -> dict:
    """详情返回解密后的明文，供编辑表单回填。"""
    row = config_repo.get_config(config_id)
    if row is None:
        raise ApiError(
            response.CODE_NOT_FOUND,
            '配置项不存在',
            f'config id not found: {config_id}',
            404,
        )
    return _item(row, mask_value=False)


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------

def create_config(payload: dict) -> dict:
    _validate_common_fields(payload)
    is_encrypt = 1 if _to_bool(payload.get('is_encrypt')) else 0
    stored_value = _normalize_value(_clean_str(payload.get('config_type')), _clean_str(payload.get('config_value')))
    if is_encrypt:
        stored_value = encrypt_value(stored_value)

    data = {
        'config_name': _clean_str(payload.get('config_name'))[:255],
        'config_scope': _clean_str(payload.get('config_scope')),
        'config_type': _clean_str(payload.get('config_type')),
        'config_key': _clean_str(payload.get('config_key'))[:255],
        'config_value': stored_value,
        'is_encrypt': is_encrypt,
        'create_user': request_scope.get_current_uid(),
        'description': _clean_str(payload.get('description'))[:512],
    }
    config_id = config_repo.create_config(data)
    return get_config(config_id)


def update_config(config_id: int, payload: dict) -> dict:
    """全量更新，与编辑表单的全量提交及 dms 的 update 语义一致。"""
    _validate_common_fields(payload)
    if config_repo.get_config(config_id) is None:
        raise ApiError(
            response.CODE_NOT_FOUND,
            '配置项不存在',
            f'config id not found: {config_id}',
            404,
        )

    is_encrypt = 1 if _to_bool(payload.get('is_encrypt')) else 0
    stored_value = _normalize_value(_clean_str(payload.get('config_type')), _clean_str(payload.get('config_value')))
    if is_encrypt:
        stored_value = encrypt_value(stored_value)

    fields = {
        'config_name': _clean_str(payload.get('config_name'))[:255],
        'config_scope': _clean_str(payload.get('config_scope')),
        'config_type': _clean_str(payload.get('config_type')),
        'config_key': _clean_str(payload.get('config_key'))[:255],
        'config_value': stored_value,
        'is_encrypt': is_encrypt,
        'description': _clean_str(payload.get('description'))[:512],
    }
    config_repo.update_config(config_id, fields)
    return get_config(config_id)


def delete_config(config_id: int) -> None:
    config_repo.delete_config(config_id)
