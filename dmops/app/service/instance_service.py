"""RDS 实例列表与详情。"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.adapter.aliyun import client as client_factory
from app.adapter.aliyun import errors, rds
from app.infra import (
    cloud_account_repository as account_repo,
    cloud_credential_repository as credential_repo,
    resource_repository as resource_repo,
)
from app.util.convert import parse_cloud_time, time_to_str, to_bit
from app.util.errors import ApiError
from app.util.web import response

logger = logging.getLogger(__name__)

# 磁盘用量只用于列表展示，按当前页实例批量查详情，并缓存一小段时间，
# 避免翻页、刷新时反复调用 DescribeDBInstanceAttribute。
_TAG_DEFAULT = 'undefine'

_DISK_CACHE_TTL_SECONDS = 60
_DISK_MAX_ITEMS = 100
_DISK_WORKERS = 8
_disk_cache: dict[tuple[int, str, str], tuple[float, object, object]] = {}
_disk_cache_lock = threading.Lock()


def list_instances(account_id: int, region: str = '', keyword: str = '', status: str = '',
                   page: int = 1, page_size: int = 20) -> dict:
    """实例列表读 ops_resource，数据来自账号同步。"""
    account = _require_account(account_id)
    rows, total = resource_repo.list_resources(
        account_id=account_id,
        region=region,
        keyword=keyword,
        status=status,
        page=page,
        page_size=page_size,
    )
    return {
        'account_id': account['id'],
        'cloud_account_id': account['cloud_account_id'],
        'account_name': account['name'],
        'items': [_list_item(row) for row in rows],
        'page': page,
        'page_size': page_size,
        'total': total,
    }


def disk_usage(account_id: int, items: str) -> dict:
    """批量查询当前页实例的磁盘已用量与容量。

    DescribeDBInstances 不返回容量和磁盘用量，只能逐台调 DescribeDBInstanceAttribute，
    所以这里只接受列表当前页的实例，结果缓存一小段时间。
    返回值中 storage_gb 单位为 GB，disk_used_bytes 单位为字节。
    """
    _require_account(account_id)
    credential = _require_credential(account_id)
    if not credential.get('enabled'):
        raise ApiError(response.CODE_BAD_REQUEST, '账号认证已停用', 'credential is disabled', 400)

    pairs = _parse_disk_items(items)

    def query(pair: tuple[str, str]) -> dict:
        region, instance_id = pair
        result = {
            'region': region,
            'instance_id': instance_id,
            'storage_gb': None,
            'disk_used_bytes': None,
            'disk_usage_percent': None,
            'error': '',
        }
        cached = _disk_cache_get(account_id, region, instance_id)
        if cached is not None:
            result['storage_gb'], result['disk_used_bytes'] = cached
            result['disk_usage_percent'] = _disk_usage_percent(cached[1], cached[0])
            return result

        try:
            rds_client = client_factory.get_rds_client(account_id, credential, region)
            attribute = rds.describe_instance_attribute(rds_client, instance_id)
        except Exception as error:  # noqa: BLE001 - SDK 异常类型不统一
            result['error'] = errors.translate_sdk_error(error, 'DescribeDBInstanceAttribute').message
            return result

        if attribute is None:
            result['error'] = 'instance not found'
            return result

        # DBInstanceDiskUsed 单位是字节，DBInstanceStorage 单位是 GB。
        storage_gb = attribute.dbinstance_storage
        disk_used_bytes = attribute.dbinstance_disk_used
        result['storage_gb'] = storage_gb
        result['disk_used_bytes'] = disk_used_bytes
        result['disk_usage_percent'] = _disk_usage_percent(disk_used_bytes, storage_gb)
        _disk_cache_set(account_id, region, instance_id, storage_gb, disk_used_bytes)
        return result

    workers = max(1, min(_DISK_WORKERS, len(pairs)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(query, pairs))

    return {'account_id': account_id, 'items': results}


def get_instance_detail(account_id: int, region: str, instance_id: str) -> dict:
    """实例详情实时调用 DescribeDBInstanceAttribute，并回写资源快照。"""
    account = _require_account(account_id)
    credential = _require_credential(account_id)
    if not credential.get('enabled'):
        raise ApiError(response.CODE_BAD_REQUEST, '账号认证已停用', 'credential is disabled', 400)

    region = (region or '').strip()
    instance_id = (instance_id or '').strip()
    if not region or not instance_id:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '缺少实例地域或实例 ID',
            'region and instance_id are required',
            400,
        )

    rds_client = client_factory.get_rds_client(account_id, credential, region)
    try:
        attribute = rds.describe_instance_attribute(rds_client, instance_id)
    except Exception as error:
        raise errors.translate_sdk_error(error, 'DescribeDBInstanceAttribute') from error

    if attribute is None:
        raise ApiError(
            code=response.CODE_NOT_FOUND,
            user_message='实例不存在',
            message=f'instance not found: account={account_id} region={region} id={instance_id}',
            http_status=404,
        )

    snapshot = _resource_from_attribute(attribute)
    resource = resource_repo.get_resource(account_id, region, instance_id)
    if resource is None:
        resource_repo.upsert_resource(
            account_id, region, {'cloud_id': instance_id, **snapshot},
        )
        resource = resource_repo.get_resource(account_id, region, instance_id)
    else:
        resource_repo.update_snapshot(account_id, region, instance_id, snapshot)

    return _detail_item(account, region, attribute, resource)


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


def _list_item(row: dict) -> dict:
    return {
        'id': row['id'],
        'account_id': row['account_id'],
        'cloud_account_id': row.get('cloud_account_id') or '',
        'account_name': row.get('account_name') or '',
        'region': row.get('region') or '',
        'instance_id': row.get('cloud_id') or '',
        'instance_name': row.get('instance_name') or '',
        'engine': row.get('engine') or '',
        'engine_version': row.get('engine_version') or '',
        'instance_class': row.get('instance_class') or '',
        'category': row.get('category') or '',
        'instance_type': row.get('instance_type') or '',
        'status': row.get('status') or '',
        'pay_type': row.get('pay_type') or '',
        'network_type': row.get('network_type') or '',
        'connection_string': row.get('connection_string') or '',
        'port': row.get('port') or '',
        'zone_id': row.get('zone_id') or '',
        'owner': row.get('owner') or _TAG_DEFAULT,
        'level': row.get('level') or _TAG_DEFAULT,
        'prodline': row.get('prodline') or _TAG_DEFAULT,
        'cpu': row.get('cpu') or '',
        'memory_mb': row.get('memory_mb'),
        'storage_gb': row.get('storage_gb'),
        'disk_used_bytes': row.get('disk_used_bytes'),
        'disk_usage_percent': _disk_usage_percent(
            row.get('disk_used_bytes'), row.get('storage_gb'),
        ),
        'create_time': time_to_str(row.get('create_time')),
        'expire_time': time_to_str(row.get('expire_time')),
        'last_sync_at': time_to_str(row.get('last_sync_at')),
    }


def _detail_item(account: dict, region: str, attribute, resource: dict | None) -> dict:
    return {
        'id': resource['id'] if resource else None,
        'account_id': account['id'],
        'cloud_account_id': account['cloud_account_id'],
        'account_name': account['name'],
        'region': region,
        'instance_id': attribute.dbinstance_id or '',
        'instance_name': attribute.dbinstance_description or '',
        'engine': attribute.engine or '',
        'engine_version': attribute.engine_version or '',
        'instance_class': attribute.dbinstance_class or '',
        'category': attribute.category or '',
        'instance_type': attribute.dbinstance_type or '',
        'status': attribute.dbinstance_status or '',
        'pay_type': attribute.pay_type or '',
        'network_type': attribute.instance_network_type or '',
        'connection_string': attribute.connection_string or '',
        'port': attribute.port or '',
        'vpc_id': attribute.vpc_id or '',
        'vswitch_id': attribute.v_switch_id or '',
        'zone_id': attribute.zone_id or '',
        'owner': (resource or {}).get('owner') or _TAG_DEFAULT,
        'level': (resource or {}).get('level') or _TAG_DEFAULT,
        'prodline': (resource or {}).get('prodline') or _TAG_DEFAULT,
        'cpu': attribute.dbinstance_cpu or '',
        'memory_mb': attribute.dbinstance_memory,
        'storage_gb': attribute.dbinstance_storage,
        'disk_used_bytes': attribute.dbinstance_disk_used,
        'disk_usage_percent': _disk_usage_percent(
            attribute.dbinstance_disk_used, attribute.dbinstance_storage,
        ),
        'storage_type': attribute.dbinstance_storage_type or '',
        'lock_mode': attribute.lock_mode or '',
        'lock_reason': attribute.lock_reason or '',
        'deletion_protection': (
            bool(attribute.deletion_protection)
            if attribute.deletion_protection is not None else None
        ),
        'create_time': time_to_str(parse_cloud_time(attribute.creation_time)),
        'expire_time': time_to_str(parse_cloud_time(attribute.expire_time)),
        'master_instance_id': attribute.master_instance_id or '',
        'guard_instance_id': attribute.guard_dbinstance_id or '',
        'temp_instance_id': attribute.temp_dbinstance_id or '',
        'readonly_instance_ids': _readonly_instance_ids(attribute),
    }


def _resource_from_attribute(attribute) -> dict:
    return {
        'instance_name': attribute.dbinstance_description or '',
        'engine': attribute.engine,
        'engine_version': attribute.engine_version,
        'instance_class': attribute.dbinstance_class,
        'category': attribute.category,
        'instance_type': attribute.dbinstance_type,
        'status': attribute.dbinstance_status,
        'pay_type': attribute.pay_type,
        'network_type': attribute.instance_network_type,
        'connection_string': attribute.connection_string,
        'port': attribute.port,
        'vpc_id': attribute.vpc_id,
        'vswitch_id': attribute.v_switch_id,
        'zone_id': attribute.zone_id,
        'cpu': attribute.dbinstance_cpu,
        'memory_mb': attribute.dbinstance_memory,
        'storage_gb': attribute.dbinstance_storage,
        'storage_type': attribute.dbinstance_storage_type,
        'create_time': parse_cloud_time(attribute.creation_time),
        'expire_time': parse_cloud_time(attribute.expire_time),
        'lock_mode': attribute.lock_mode,
        'deletion_protection': to_bit(attribute.deletion_protection),
        'master_instance_id': attribute.master_instance_id,
    }


def _readonly_instance_ids(attribute) -> list[str]:
    container = attribute.read_only_dbinstance_ids
    items = container.read_only_dbinstance_id if container else None
    return [
        item.dbinstance_id
        for item in (items or [])
        if item and item.dbinstance_id
    ]


def _parse_disk_items(raw: str) -> list[tuple[str, str]]:
    """解析 region:instance_id 列表，去重并限制批量大小。"""
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for chunk in (raw or '').split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        region, sep, instance_id = chunk.partition(':')
        region = region.strip()
        instance_id = instance_id.strip()
        if not sep or not region or not instance_id:
            raise ApiError(
                response.CODE_BAD_REQUEST,
                '实例参数格式不正确',
                f'invalid instance item: {chunk!r}, expected region:instance_id',
                400,
            )
        key = (region, instance_id)
        if key in seen:
            continue
        seen.add(key)
        pairs.append(key)

    if not pairs:
        raise ApiError(response.CODE_BAD_REQUEST, '缺少实例参数', 'items is required', 400)
    if len(pairs) > _DISK_MAX_ITEMS:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            f'一次最多查询 {_DISK_MAX_ITEMS} 个实例',
            f'too many items: {len(pairs)}',
            400,
        )
    return pairs


def _disk_cache_get(account_id: int, region: str,
                    instance_id: str) -> tuple[object, object] | None:
    key = (account_id, region, instance_id)
    with _disk_cache_lock:
        entry = _disk_cache.get(key)
        if entry is None:
            return None
        if entry[0] <= time.monotonic():
            _disk_cache.pop(key, None)
            return None
    return entry[1], entry[2]


def _disk_cache_set(account_id: int, region: str, instance_id: str,
                    storage_gb, disk_used_bytes) -> None:
    with _disk_cache_lock:
        _disk_cache[(account_id, region, instance_id)] = (
            time.monotonic() + _DISK_CACHE_TTL_SECONDS, storage_gb, disk_used_bytes,
        )


def _disk_usage_percent(disk_used_bytes, storage_gb) -> int | None:
    """磁盘水位：已用字节数 / 容量（GB）。"""
    try:
        used_bytes = float(disk_used_bytes)
        storage_gb = float(storage_gb)
    except (TypeError, ValueError):
        return None
    if storage_gb <= 0:
        return None
    return int(round(used_bytes / (storage_gb * 1024 ** 3) * 100))
