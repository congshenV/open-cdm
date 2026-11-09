"""账号、认证、地域与实例同步业务。

"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor

from app import config
from app.adapter.aliyun import client as client_factory
from app.adapter.aliyun import credentials, errors, rds
from app.infra import (
    cloud_account_repository as account_repo,
    cloud_credential_repository as credential_repo,
    resource_repository as resource_repo,
)
from app.util.convert import (
    clean_str as _clean_str,
    is_blank as _is_blank,
    parse_cloud_time as _parse_cloud_time,
    time_to_str as _time_to_str,
    to_bit as _to_bit,
    to_bool as _to_bool,
)
from app.util.errors import ApiError
from app.util.web import response

logger = logging.getLogger(__name__)

_ACCOUNT_ID_PATTERN = re.compile(r'^\d{6,32}$')

_CREDENTIAL_TYPES = credentials.SUPPORTED_CREDENTIAL_TYPES

# 每种认证方式实际需要保存的字段。切换类型时会清空旧类型字段，避免残留。
_CREDENTIAL_FIELDS: dict[str, tuple[str, ...]] = {
    'access_key': ('access_key_id', 'access_key_secret'),
    'sts': ('access_key_id', 'access_key_secret', 'security_token'),
    'ram_role_arn': (
        'access_key_id', 'access_key_secret', 'security_token',
        'role_arn', 'role_session_name', 'role_session_expiration',
        'external_id', 'sts_endpoint',
    ),
    'assume_role': (
        'role_arn', 'role_session_name', 'role_session_expiration',
        'external_id', 'sts_endpoint',
    ),
    'credentials_uri': ('credentials_uri',),
    'oidc_role_arn': (
        'role_arn', 'role_session_name', 'role_session_expiration',
        'oidc_provider_arn', 'oidc_token_file_path', 'sts_endpoint',
    ),
    'profile': ('profile_name',),
    'default': (),
}

_SECRET_FIELDS = ('access_key_secret', 'security_token')

# 实例标签里约定用于展示的键，缺失时统一记为 undefine。
_TAG_DEFAULT = 'undefine'
_TAG_KEYS = ('owner', 'level', 'prodline')

# 同步时逐台查详情（磁盘容量/已用量）的并发数。
_DISK_WORKERS = 8

_ALL_CREDENTIAL_FIELDS = (
    'access_key_id', 'access_key_secret', 'security_token',
    'role_arn', 'role_session_name', 'role_session_expiration', 'external_id',
    'sts_endpoint', 'oidc_provider_arn', 'oidc_token_file_path',
    'credentials_uri', 'profile_name',
)


# ---------------------------------------------------------------------------
# 账号
# ---------------------------------------------------------------------------

def list_accounts(keyword: str = '', enabled: bool | None = None,
                  page: int = 1, page_size: int = 20) -> dict:
    rows, total = account_repo.list_accounts(keyword, enabled, page, page_size)
    return {
        'items': [_account_item(row) for row in rows],
        'page': page,
        'page_size': page_size,
        'total': total,
    }


def get_account(account_id: int) -> dict:
    account = _require_account(account_id)
    credential = credential_repo.get_credential(account_id)
    item = _account_item(account)
    if credential:
        item['credential_type'] = credential.get('credential_type') or ''
        item['credential_configured'] = True
        item['credential_enabled'] = bool(credential.get('enabled'))
    item['credential'] = _credential_item(credential) if credential else {'configured': False}
    return item


def create_account(payload: dict) -> dict:
    cloud_account_id = _clean_str(payload.get('cloud_account_id'))
    if not _ACCOUNT_ID_PATTERN.match(cloud_account_id):
        raise ApiError(
            code=response.CODE_BAD_REQUEST,
            user_message='阿里云账号 ID 格式不正确',
            message='cloud_account_id must be 6-32 digits',
            http_status=400,
        )

    name = _clean_str(payload.get('name'))
    if not name:
        raise ApiError(response.CODE_BAD_REQUEST, '账号名称不能为空', 'name is required', 400)

    data = {
        'cloud_account_id': cloud_account_id,
        'name': name[:128],
        'description': _clean_str(payload.get('description'))[:512],
        'default_region': _clean_str(payload.get('default_region')) or 'cn-hangzhou',
        'enabled': 1 if _to_bool(payload.get('enabled'), default=True) else 0,
    }
    account_id = account_repo.create_account(data)
    return get_account(account_id)


def update_account(account_id: int, payload: dict) -> dict:
    _require_account(account_id)
    fields: dict = {}
    if 'name' in payload:
        name = _clean_str(payload.get('name'))
        if not name:
            raise ApiError(response.CODE_BAD_REQUEST, '账号名称不能为空', 'name is required', 400)
        fields['name'] = name[:128]
    if 'description' in payload:
        fields['description'] = _clean_str(payload.get('description'))[:512]
    if 'default_region' in payload:
        fields['default_region'] = _clean_str(payload.get('default_region')) or 'cn-hangzhou'
    if 'enabled' in payload:
        fields['enabled'] = 1 if _to_bool(payload.get('enabled'), default=True) else 0

    account_repo.update_account(account_id, fields)
    return get_account(account_id)


def delete_account(account_id: int) -> None:
    account_repo.delete_account(account_id)
    credentials.invalidate(account_id)
    client_factory.invalidate_account(account_id)


# ---------------------------------------------------------------------------
# 认证
# ---------------------------------------------------------------------------

def get_credential(account_id: int) -> dict:
    _require_account(account_id)
    credential = credential_repo.get_credential(account_id)
    if credential is None:
        return {'configured': False}
    return _credential_item(credential)


def upsert_credential(account_id: int, payload: dict) -> dict:
    _require_account(account_id)

    credential_type = _clean_str(payload.get('credential_type'))
    if credential_type not in _CREDENTIAL_TYPES:
        raise ApiError(
            code=response.CODE_BAD_REQUEST,
            user_message='不支持的认证方式',
            message=f'unsupported credential_type: {credential_type}',
            http_status=400,
        )

    existing = credential_repo.get_credential(account_id) or {}
    data: dict = {'credential_type': credential_type}
    for field in _ALL_CREDENTIAL_FIELDS:
        if field in _CREDENTIAL_FIELDS[credential_type]:
            value = payload[field] if field in payload else existing.get(field)
            if field in _SECRET_FIELDS and _is_blank(value):
                # 更新时 secret 留空表示保持原值，避免前端回显导致误清空。
                value = existing.get(field)
            data[field] = _clean_str(value) or None
        else:
            data[field] = None

    if credential_type in ('ram_role_arn', 'assume_role', 'oidc_role_arn'):
        data['role_session_expiration'] = _validate_session_expiration(
            data.get('role_session_expiration'),
        )

    _validate_credential_required(credential_type, data)

    if 'enabled' in payload:
        data['enabled'] = 1 if _to_bool(payload.get('enabled'), default=True) else 0
    else:
        data['enabled'] = int(existing.get('enabled') if existing else 1)

    credential_repo.upsert_credential(account_id, data)
    credentials.invalidate(account_id)
    client_factory.invalidate_account(account_id)

    credential = credential_repo.get_credential(account_id)
    return _credential_item(credential)


def delete_credential(account_id: int) -> None:
    _require_account(account_id)
    credential_repo.delete_credential(account_id)
    credentials.invalidate(account_id)
    client_factory.invalidate_account(account_id)


def _validate_credential_required(credential_type: str, data: dict) -> None:
    required: dict[str, tuple[str, ...]] = {
        'access_key': ('access_key_id', 'access_key_secret'),
        'sts': ('access_key_id', 'access_key_secret', 'security_token'),
        'ram_role_arn': ('access_key_id', 'access_key_secret', 'role_arn'),
        'assume_role': ('role_arn',),
        'credentials_uri': ('credentials_uri',),
        'oidc_role_arn': ('role_arn', 'oidc_provider_arn', 'oidc_token_file_path'),
        'profile': ('profile_name',),
        'default': (),
    }
    missing = [field for field in required[credential_type] if _is_blank(data.get(field))]
    if missing:
        raise ApiError(
            code=response.CODE_BAD_REQUEST,
            user_message='认证配置不完整',
            message=f'credential_type={credential_type} missing fields: {", ".join(missing)}',
            http_status=400,
        )


def _validate_session_expiration(value) -> int:
    if _is_blank(value):
        return 3600
    try:
        expiration = int(value)
    except (TypeError, ValueError) as error:
        raise ApiError(
            response.CODE_BAD_REQUEST, '会话时长不合法', f'invalid role_session_expiration: {value}', 400,
        ) from error
    if expiration < 900 or expiration > 3600:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '会话时长不合法',
            f'role_session_expiration must be in range 900-3600, got {expiration}',
            400,
        )
    return expiration


# ---------------------------------------------------------------------------
# 地域与同步
# ---------------------------------------------------------------------------

def list_regions(account_id: int) -> dict:
    account = _require_account(account_id)
    credential = _require_credential(account_id)

    region = account.get('default_region') or 'cn-hangzhou'
    cloud_regions: list[str] = []
    cloud_error = ''
    try:
        rds_client = client_factory.get_rds_client(account_id, credential, region)
        cloud_regions = rds.describe_region_infos(rds_client)
    except ApiError:
        # 认证配置错误属于账号自身问题，直接让调用方看到明确提示。
        raise
    except Exception as error:  # noqa: BLE001 - SDK 异常类型不统一
        translated = errors.translate_sdk_error(error, 'DescribeRegionInfos')
        cloud_error = translated.message
        logger.warning('[dmops] describe regions failed account=%s: %s', account_id, translated.message)

    regions = set(cloud_regions)
    regions.update(resource_repo.list_regions(account_id))
    if not regions:
        # 云上接口失败且本地没有同步记录时，至少让调用方有一个默认地域可用。
        regions.add(region)

    return {
        'account_id': account_id,
        'regions': sorted(regions),
        'error': cloud_error,
    }


def sync_instances(account_id: int) -> dict:
    account = _require_account(account_id)
    if not account.get('enabled'):
        raise ApiError(response.CODE_BAD_REQUEST, '账号已停用', 'account is disabled', 400)

    credential = _require_credential(account_id)
    if not credential.get('enabled'):
        raise ApiError(response.CODE_BAD_REQUEST, '账号认证已停用', 'credential is disabled', 400)

    regions = list_regions(account_id)['regions']
    if not regions:
        raise ApiError(response.CODE_BAD_REQUEST, '没有可同步的地域', 'no regions to sync', 400)

    def sync_region(region: str) -> dict:
        try:
            rds_client = client_factory.get_rds_client(account_id, credential, region)
            instances, truncated = rds.describe_all_instances(
                rds_client, region, config.Aliyun.max_instances_per_region,
            )

            # 标签是附加信息，接口失败时保留上一次同步的标签，不用默认值覆盖。
            tags: dict[str, dict[str, str]] | None
            try:
                tags = rds.describe_instance_tags(rds_client, region)
            except Exception as error:  # noqa: BLE001 - SDK 异常类型不统一
                tags = None
                translated = errors.translate_sdk_error(error, 'DescribeDBInstanceByTags')
                logger.warning(
                    '[dmops] describe instance tags failed account=%s region=%s: %s',
                    account_id, region, translated.message,
                )

            # 磁盘容量和已用量只有详情接口返回，同步时顺带取回来落库，
            # 列表就不用再逐台查详情。个别实例查询失败时保留库里上一次的值。
            attributes, attribute_failed, attribute_error = _describe_attributes(
                rds_client, instances,
            )
            if attribute_failed:
                logger.warning(
                    '[dmops] describe instance attribute failed account=%s region=%s failed=%s first_error=%s',
                    account_id, region, attribute_failed, attribute_error,
                )

            existing_ids = resource_repo.list_cloud_ids(account_id, region)

            created = 0
            updated = 0
            seen: set[str] = set()
            mapped: list[dict] = []
            for instance in instances:
                cloud_id = getattr(instance, 'dbinstance_id', '') or ''
                if not cloud_id:
                    continue
                seen.add(cloud_id)
                mapped.append(_resource_from_instance(
                    region, instance, tags, attributes.get(cloud_id),
                ))
                if cloud_id in existing_ids:
                    updated += 1
                else:
                    created += 1

            resource_repo.upsert_resources(account_id, region, mapped)

            # 实例被截断时不能判断哪些实例已经不存在，跳过 Released 标记。
            missing = 0 if truncated else resource_repo.mark_missing(account_id, region, seen)
            return {
                'region': region,
                'total': len(seen),
                'created': created,
                'updated': updated,
                'missing': missing,
                'truncated': truncated,
                'error': '',
            }
        except ApiError as error:
            logger.warning('[dmops] sync region failed account=%s region=%s: %s', account_id, region, error.message)
            return {
                'region': region,
                'total': 0,
                'created': 0,
                'updated': 0,
                'missing': 0,
                'truncated': False,
                'error': error.message,
            }
        except Exception as error:  # noqa: BLE001
            translated = errors.translate_sdk_error(error, f'DescribeDBInstances({region})')
            return {
                'region': region,
                'total': 0,
                'created': 0,
                'updated': 0,
                'missing': 0,
                'truncated': False,
                'error': translated.message,
            }

    with ThreadPoolExecutor(max_workers=max(1, config.Aliyun.sync_workers)) as pool:
        region_results = list(pool.map(sync_region, regions))

    failed = [item for item in region_results if item['error']]
    if not failed:
        status = 'SUCCESS'
    elif len(failed) == len(region_results):
        status = 'FAILED'
    else:
        status = 'PARTIAL'
    account_repo.update_sync_status(account_id, status)
    if failed:
        logger.warning(
            '[dmops] sync finished account=%s status=%s regions=%s failed=%s first_error=%s',
            account_id, status, len(region_results), len(failed), failed[0]['error'],
        )
    else:
        logger.info('[dmops] sync finished account=%s status=%s regions=%s', account_id, status, len(region_results))

    return {
        'account_id': account_id,
        'status': status,
        'regions': region_results,
        'created': sum(item['created'] for item in region_results),
        'updated': sum(item['updated'] for item in region_results),
        'missing': sum(item['missing'] for item in region_results),
    }


def _describe_attributes(client, instances) -> tuple[dict[str, object], int, str]:
    """并发查询实例详情，返回 (实例ID -> attribute, 失败数, 首个错误信息)。"""
    targets = [
        instance for instance in instances
        if getattr(instance, 'dbinstance_id', '')
    ]
    if not targets:
        return {}, 0, ''

    def query(instance):
        instance_id = instance.dbinstance_id
        try:
            attribute = rds.describe_instance_attribute(client, instance_id)
            return instance_id, attribute, ''
        except Exception as error:  # noqa: BLE001 - SDK 异常类型不统一
            translated = errors.translate_sdk_error(error, 'DescribeDBInstanceAttribute')
            return instance_id, None, translated.message

    attributes: dict[str, object] = {}
    failed = 0
    first_error = ''
    workers = max(1, min(_DISK_WORKERS, len(targets)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for instance_id, attribute, error in pool.map(query, targets):
            if attribute is None:
                failed += 1
                if not first_error:
                    first_error = error or 'instance not found'
                continue
            attributes[instance_id] = attribute
    return attributes, failed, first_error


def _resource_from_instance(region: str, instance,
                            tags: dict[str, dict[str, str]] | None,
                            attribute=None) -> dict:
    """把 DescribeDBInstances / DescribeDBInstanceAttribute 返回项转换为 ops_resource 字段。

    tags 为 None 表示本次标签接口调用失败，不写入标签字段，避免覆盖已有值；
    attribute 为 None 表示该实例详情查询失败，同样不写磁盘字段。
    """
    data = {
        'region': region,
        'cloud_id': instance.dbinstance_id,
        'instance_name': (instance.dbinstance_description or '')[:config.Aliyun.instance_name_max_len],
        'engine': instance.engine,
        'engine_version': instance.engine_version,
        'instance_class': instance.dbinstance_class,
        'category': instance.category,
        'instance_type': instance.dbinstance_type,
        'status': instance.dbinstance_status,
        'pay_type': instance.pay_type,
        'network_type': instance.instance_network_type,
        'connection_string': instance.connection_string,
        'vpc_id': instance.vpc_id,
        'vswitch_id': instance.v_switch_id,
        'zone_id': instance.zone_id,
        'cpu': instance.dbinstance_cpu,
        'memory_mb': instance.dbinstance_memory,
        # DescribeDBInstances 不返回端口、存储容量和磁盘已用量，
        # 容量与已用量由详情接口补充，port 仍由详情/磁盘接口回填。
        'storage_type': instance.dbinstance_storage_type,
        'create_time': _parse_cloud_time(instance.create_time),
        'expire_time': _parse_cloud_time(instance.expire_time),
        'lock_mode': instance.lock_mode,
        'deletion_protection': _to_bit(instance.deletion_protection),
        'master_instance_id': instance.master_instance_id,
    }
    if attribute is not None:
        if attribute.dbinstance_storage is not None:
            data['storage_gb'] = attribute.dbinstance_storage
        if attribute.dbinstance_disk_used is not None:
            data['disk_used_bytes'] = attribute.dbinstance_disk_used
    if tags is not None:
        instance_tags = tags.get(instance.dbinstance_id) or {}
        for key in _TAG_KEYS:
            data[key] = _tag_value(instance_tags, key)
    return data


def _tag_value(tags: dict[str, str], key: str) -> str:
    value = _clean_str(tags.get(key))
    if value:
        return value
    return _TAG_DEFAULT


# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------

def _require_account(account_id: int) -> dict:
    account = account_repo.get_account(account_id)
    if account is None:
        raise ApiError(
            code=response.CODE_NOT_FOUND,
            user_message='账号不存在',
            message=f'account id not found: {account_id}',
            http_status=404,
        )
    return account


def _require_credential(account_id: int) -> dict:
    credential = credential_repo.get_credential(account_id)
    if credential is None:
        raise ApiError(
            code=response.CODE_BAD_REQUEST,
            user_message='账号未配置认证信息',
            message=f'credential not found for account: {account_id}',
            http_status=400,
        )
    return credential


def _account_item(row: dict) -> dict:
    return {
        'id': row['id'],
        'cloud_account_id': row['cloud_account_id'],
        'name': row['name'],
        'description': row.get('description') or '',
        'default_region': row.get('default_region') or '',
        'enabled': bool(row.get('enabled')),
        'credential_type': row.get('credential_type') or '',
        'credential_configured': bool(row.get('credential_type')),
        'credential_enabled': bool(row.get('credential_enabled')) if row.get('credential_type') else False,
        'last_sync_at': _time_to_str(row.get('last_sync_at')),
        'last_sync_status': row.get('last_sync_status') or '',
        'created_at': _time_to_str(row.get('created_at')),
        'updated_at': _time_to_str(row.get('updated_at')),
    }


def _credential_item(row: dict | None) -> dict:
    if row is None:
        return {'configured': False}
    return {
        'configured': True,
        'credential_type': row.get('credential_type') or '',
        'access_key_id_masked': _mask(row.get('access_key_id')),
        'access_key_secret_set': not _is_blank(row.get('access_key_secret')),
        'security_token_set': not _is_blank(row.get('security_token')),
        'role_arn': row.get('role_arn') or '',
        'role_session_name': row.get('role_session_name') or '',
        'role_session_expiration': row.get('role_session_expiration') or 0,
        'external_id': row.get('external_id') or '',
        'sts_endpoint': row.get('sts_endpoint') or '',
        'oidc_provider_arn': row.get('oidc_provider_arn') or '',
        'oidc_token_file_path': row.get('oidc_token_file_path') or '',
        'credentials_uri': row.get('credentials_uri') or '',
        'profile_name': row.get('profile_name') or '',
        'enabled': bool(row.get('enabled')),
        'version': row.get('version') or 0,
        'last_verified_at': _time_to_str(row.get('last_verified_at')),
        'last_verify_error': row.get('last_verify_error') or '',
        'updated_at': _time_to_str(row.get('updated_at')),
    }


def _mask(value: str | None) -> str:
    if not value:
        return ''
    value = str(value)
    if len(value) <= 8:
        return value[:2] + '****'
    return value[:4] + '****' + value[-4:]


