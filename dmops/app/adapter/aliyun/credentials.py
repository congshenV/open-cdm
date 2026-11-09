"""阿里云凭据客户端。

每个账号根据自己的认证配置构建独立的 ``CredentialClient``，并在进程内缓存。
认证方式来自 ``ops_cloud_credential`` 表，dmops 只读取，不在环境变量里配置
账号级凭据。
"""

import logging
import threading

from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_credentials.models import Config as CredentialConfig
from alibabacloud_credentials.provider import (
    CLIProfileCredentialsProvider,
    DefaultCredentialsProvider,
    RamRoleArnCredentialsProvider,
)

from app import config
from app.util.errors import ApiError
from app.util.web import response

logger = logging.getLogger(__name__)

SUPPORTED_CREDENTIAL_TYPES = {
    'access_key',
    'sts',
    'ram_role_arn',
    'assume_role',
    'credentials_uri',
    'oidc_role_arn',
    'profile',
    'default',
}

# account_id -> (credential version, client)
_cache: dict[int, tuple[int, CredentialClient]] = {}
_lock = threading.Lock()


def get_credential_client(account_id: int, credential: dict) -> CredentialClient:
    """按账号获取凭据客户端，credential.version 变化时重建。"""
    version = int(credential.get('version') or 0)
    with _lock:
        cached = _cache.get(account_id)
    if cached is not None and cached[0] == version:
        return cached[1]

    client = _build(account_id, credential)
    with _lock:
        _cache[account_id] = (version, client)
    logger.info(
        '[dmops] aliyun credential client ready account=%s type=%s version=%s',
        account_id, credential.get('credential_type'), version,
    )
    return client


def invalidate(account_id: int) -> None:
    with _lock:
        _cache.pop(account_id, None)


def _build(account_id: int, credential: dict) -> CredentialClient:
    cred_type = (credential.get('credential_type') or '').strip()
    if cred_type not in SUPPORTED_CREDENTIAL_TYPES:
        raise _bad_config(account_id, f'unsupported credential_type: {cred_type}')

    if cred_type == 'access_key':
        return CredentialClient(CredentialConfig(
            type='access_key',
            access_key_id=_required(account_id, credential, 'access_key_id'),
            access_key_secret=_required(account_id, credential, 'access_key_secret'),
        ))

    if cred_type == 'sts':
        return CredentialClient(CredentialConfig(
            type='sts',
            access_key_id=_required(account_id, credential, 'access_key_id'),
            access_key_secret=_required(account_id, credential, 'access_key_secret'),
            security_token=_required(account_id, credential, 'security_token'),
        ))

    if cred_type == 'ram_role_arn':
        return CredentialClient(CredentialConfig(
            type='ram_role_arn',
            access_key_id=_required(account_id, credential, 'access_key_id'),
            access_key_secret=_required(account_id, credential, 'access_key_secret'),
            security_token=_optional(credential, 'security_token'),
            role_arn=_required(account_id, credential, 'role_arn'),
            role_session_name=_optional(credential, 'role_session_name') or _session_name(),
            role_session_expiration=_session_expiration(account_id, credential),
            external_id=_optional(credential, 'external_id'),
            sts_endpoint=_optional(credential, 'sts_endpoint'),
        ))

    if cred_type == 'assume_role':
        # 基础身份走默认凭据链：ACK 下是 RRSA，本地测试可配合 profile 使用。
        base_provider = DefaultCredentialsProvider()
        provider = RamRoleArnCredentialsProvider(
            credentials_provider=base_provider,
            role_arn=_required(account_id, credential, 'role_arn'),
            role_session_name=_optional(credential, 'role_session_name') or _session_name(),
            duration_seconds=_session_expiration(account_id, credential),
            external_id=_optional(credential, 'external_id'),
            sts_endpoint=_optional(credential, 'sts_endpoint'),
        )
        return CredentialClient(provider=provider)

    if cred_type == 'credentials_uri':
        return CredentialClient(CredentialConfig(
            type='credentials_uri',
            credentials_uri=_required(account_id, credential, 'credentials_uri'),
        ))

    if cred_type == 'oidc_role_arn':
        return CredentialClient(CredentialConfig(
            type='oidc_role_arn',
            role_arn=_required(account_id, credential, 'role_arn'),
            oidc_provider_arn=_required(account_id, credential, 'oidc_provider_arn'),
            oidc_token_file_path=_required(account_id, credential, 'oidc_token_file_path'),
            role_session_name=_optional(credential, 'role_session_name') or _session_name(),
            role_session_expiration=_session_expiration(account_id, credential),
            sts_endpoint=_optional(credential, 'sts_endpoint'),
        ))

    if cred_type == 'profile':
        return CredentialClient(provider=CLIProfileCredentialsProvider(
            profile_name=_required(account_id, credential, 'profile_name'),
        ))

    # default：使用官方默认凭据链。多账号场景下只应给 dmops 自身所在账号使用。
    return CredentialClient()


def _required(account_id: int, credential: dict, field: str) -> str:
    value = credential.get(field)
    if value is None or str(value).strip() == '':
        raise _bad_config(
            account_id,
            f'credential_type={credential.get("credential_type")} requires field: {field}',
        )
    return str(value).strip()


def _optional(credential: dict, field: str) -> str | None:
    value = credential.get(field)
    if value is None or str(value).strip() == '':
        return None
    return str(value).strip()


def _session_expiration(account_id: int, credential: dict) -> int:
    value = credential.get('role_session_expiration')
    if value is None:
        return 3600
    try:
        expiration = int(value)
    except (TypeError, ValueError) as error:
        raise _bad_config(account_id, f'invalid role_session_expiration: {value}') from error
    if expiration < 900 or expiration > 3600:
        raise _bad_config(
            account_id,
            f'role_session_expiration must be in range 900-3600, got {expiration}',
        )
    return expiration


def _session_name() -> str:
    return f'dmops-{config.Hostname}'[:64]


def _bad_config(account_id: int, message: str) -> ApiError:
    logger.error('[dmops] aliyun credential config invalid account=%s: %s', account_id, message)
    return ApiError(
        code=response.CODE_BAD_REQUEST,
        user_message='账号认证配置不完整',
        message=message,
        http_status=400,
    )
