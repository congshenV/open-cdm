"""RDS 备份策略与备份列表。

策略、备份集、日志备份均为低频查询，直接透传阿里云 OpenAPI 结果，不做落库。
"""

import logging

from app.adapter.aliyun import client as client_factory
from app.adapter.aliyun import errors, rds
from app.infra import (
    cloud_account_repository as account_repo,
    cloud_credential_repository as credential_repo,
)
from app.util.errors import ApiError
from app.util.web import response

logger = logging.getLogger(__name__)

# DescribeBackups 的 PageSize 只允许 30/50/100，默认 30。
_BACKUP_PAGE_SIZES = (30, 50, 100)
_DEFAULT_BACKUP_PAGE_SIZE = 30
# DescribeBinlogFiles 的 PageSize 允许 30~100。
_BINLOG_PAGE_MIN = 30
_BINLOG_PAGE_MAX = 100
# 日志 / 跨地域备份默认查询最近 7 天。
_BINLOG_DEFAULT_WINDOW_DAYS = 7
# 跨地域备份列表同样走最近 7 天窗口。
_CROSS_DEFAULT_WINDOW_DAYS = 7


def get_backup_policy(account_id: int, region: str, instance_id: str) -> dict:
    """查询实例备份策略（DescribeBackupPolicy + 异地备份设置）。

    异地备份设置是单独的 OpenAPI，这里并行调用后合并返回；
    未开启跨地域备份的实例阿里云会返回 Disable / 空保留天数，前端展示为关闭。
    """
    account = _require_account(account_id)
    credential = _require_credential(account_id)
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
        policy_body = rds.describe_backup_policy(rds_client, instance_id)
    except Exception as error:
        raise errors.translate_sdk_error(error, 'DescribeBackupPolicy') from error

    # 跨地域备份设置查询失败不影响基础策略展示，默认关闭。
    cross_error = ''
    try:
        cross_body = rds.describe_instance_cross_backup_policy(rds_client, instance_id, region)
    except Exception as error:  # noqa: BLE001 - 老实例/不支持地域可能直接报错
        logger.warning(
            '[dmops] describe cross backup policy failed account=%s region=%s error=%s',
            account_id, region, error,
        )
        cross_error = errors.translate_sdk_error(error, 'DescribeInstanceCrossBackupPolicy').user_message
        cross_body = None

    item = _policy_item(policy_body)
    item['cross'] = _cross_policy_item(cross_body)
    item['cross_error'] = cross_error
    return item


def list_backups(account_id: int, region: str, instance_id: str,
                 page: int = 1, page_size: int = _DEFAULT_BACKUP_PAGE_SIZE) -> dict:
    """分页查询实例备份集列表。"""
    page_size = _normalize_backup_page_size(page_size)
    rds_client = _prepare_client(account_id, region, instance_id)
    try:
        body = rds.describe_backups(rds_client, instance_id, page, page_size)
    except Exception as error:
        raise errors.translate_sdk_error(error, 'DescribeBackups') from error

    items = body.items.backup if body and body.items else None
    total = _to_int(body.total_record_count if body else None)
    page_record_count = _to_int(body.page_record_count if body else None)
    # DescribeBackups 不返回页码上限，total 就是全量条数，可直接用于分页。
    if total is None:
        total = page_record_count or 0
    return {
        'items': [_backup_item(item) for item in (items or [])],
        'page': page,
        'page_size': page_size,
        'total': total,
    }


def list_binlog_files(account_id: int, region: str, instance_id: str,
                      start_time: str = '', end_time: str = '',
                      page: int = 1, page_size: int = _BINLOG_PAGE_MIN) -> dict:
    """分页查询实例日志备份列表，默认查最近 7 天。

    start_time / end_time 由前端传入 `yyyy-MM-ddTHH:mmZ` 形式（UTC），为空时自动补默认窗口。
    """
    page_size = _normalize_binlog_page_size(page_size)
    start_time, end_time = _normalize_binlog_window(start_time, end_time)
    rds_client = _prepare_client(account_id, region, instance_id)
    try:
        body = rds.describe_binlog_files(
            rds_client, instance_id, start_time, end_time, page, page_size,
        )
    except Exception as error:
        raise errors.translate_sdk_error(error, 'DescribeBinlogFiles') from error

    items = body.items.bin_log_file if body and body.items else None
    return {
        'items': [_binlog_item(item) for item in (items or [])],
        'page': page,
        'page_size': page_size,
        'total': _to_int(body.total_record_count if body else None) or 0,
        'start_time': start_time,
        'end_time': end_time,
    }


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
    if not credential.get('enabled'):
        raise ApiError(response.CODE_BAD_REQUEST, '账号认证已停用', 'credential is disabled', 400)
    return credential


def _prepare_client(account_id: int, region: str, instance_id: str):
    """校验账号 / 凭证 / 实例参数并返回 RDS 客户端。"""
    _require_account(account_id)
    credential = _require_credential(account_id)

    region = (region or '').strip()
    instance_id = (instance_id or '').strip()
    if not region or not instance_id:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '缺少实例地域或实例 ID',
            'region and instance_id are required',
            400,
        )
    return client_factory.get_rds_client(account_id, credential, region)


def _policy_item(body) -> dict:
    """备份策略直接透传 OpenAPI 字段，空值由前端兜底展示为 '-'。"""
    if body is None:
        return {}

    data_policies = []
    container = body.advanced_data_policies
    for item in (container.advanced_data_policy if container else None) or []:
        data_policies.append({
            'strategy_id': item.strategy_id or '',
            'bak_type': item.bak_type or '',
            'retention_type': item.retention_type or '',
            'retention_value': item.retention_value,
            'filter_key': item.filter_key or '',
            'filter_value': item.filter_value or '',
            'filter_type': item.filter_type or '',
            'src_region': item.src_region or '',
            'dest_region': item.dest_region or '',
            'src_type': item.src_type or '',
            'dest_type': item.dest_type or '',
            'only_preserve_one_each_hour': _to_bool(item.only_preserve_one_each_hour),
            'only_preserve_one_each_day': _to_bool(item.only_preserve_one_each_day),
        })

    log_policies = []
    container = body.advanced_log_policies
    for item in (container.advanced_log_policy if container else None) or []:
        log_policies.append({
            'strategy_id': item.strategy_id or '',
            'enable_log_backup': _to_int(item.enable_log_backup),
            'log_retention_type': item.log_retention_type or '',
            'log_retention_value': item.log_retention_value,
            'filter_key': item.filter_key or '',
            'filter_value': item.filter_value or '',
            'src_region': item.src_region or '',
            'dest_region': item.dest_region or '',
            'src_type': item.src_type or '',
            'dest_type': item.dest_type or '',
        })

    return {
        'backup_retention_period': _to_int(body.backup_retention_period),
        'preferred_backup_period': body.preferred_backup_period or '',
        'preferred_backup_time': body.preferred_backup_time or '',
        'preferred_next_backup_time': body.preferred_next_backup_time or '',
        'backup_interval': body.backup_interval or '',
        'backup_method': body.backup_method or '',
        'backup_log': body.backup_log or '',
        'log_backup_retention_period': _to_int(body.log_backup_retention_period),
        'log_backup_frequency': body.log_backup_frequency or '',
        'compress_type': body.compress_type or '',
        'category': body.category or '',
        'archive_backup_keep_policy': body.archive_backup_keep_policy or '',
        'archive_backup_keep_count': body.archive_backup_keep_count or '',
        'archive_backup_retention_period': body.archive_backup_retention_period or '',
        'local_log_retention_hours': _to_int(body.local_log_retention_hours),
        'local_log_retention_space': body.local_log_retention_space or '',
        'log_backup_local_retention_number': _to_int(body.log_backup_local_retention_number),
        'high_space_usage_protection': body.high_space_usage_protection or '',
        'enable_pitr_protection': _to_bool(body.enable_pitr_protection),
        'pitr_retention_period': _to_int(body.pitr_retention_period),
        'inc_backup_interval': _to_int(body.inc_backup_interval),
        'released_keep_policy': body.released_keep_policy or '',
        'advanced_backup_policy_enabled': _to_bool(body.advanced_backup_policy_enabled),
        'advanced_data_policies': data_policies,
        'advanced_log_policies': log_policies,
    }


def _backup_item(item) -> dict:
    return {
        'backup_id': _to_str(item.backup_id),
        'backup_type': item.backup_type or '',
        'backup_method': item.backup_method or '',
        'backup_mode': item.backup_mode or '',
        'backup_status': item.backup_status or '',
        'backup_initiator': item.backup_initiator or '',
        'backup_start_time': item.backup_start_time or '',
        'backup_end_time': item.backup_end_time or '',
        'backup_size': item.backup_size,
        'backup_download_url': item.backup_download_url or '',
        'storage_class': item.storage_class if item.storage_class is not None else None,
        'store_status': item.store_status or '',
        'is_avail': item.is_avail if item.is_avail is not None else None,
        'meta_status': item.meta_status or '',
        'checksum': item.checksum or '',
        'host_instance_id': _to_str(item.host_instance_id),
        'expect_expire_time': item.expect_expire_time or '',
    }


def _binlog_item(item) -> dict:
    return {
        'log_file_name': item.log_file_name or '',
        'log_begin_time': item.log_begin_time or '',
        'log_end_time': item.log_end_time or '',
        'file_size': item.file_size,
        'checksum': item.checksum or '',
        'remote_status': item.remote_status or '',
        'download_link': item.download_link or '',
        'intranet_download_link': item.intranet_download_link or '',
        'link_expired_time': item.link_expired_time or '',
        'host_instance_id': _to_str(item.host_instance_id),
    }


def list_cross_region_backups(account_id: int, region: str, instance_id: str,
                              start_time: str = '', end_time: str = '',
                              page: int = 1,
                              page_size: int = _DEFAULT_BACKUP_PAGE_SIZE) -> dict:
    """分页查询跨地域（异地）备份集列表。

    跨地域接口必须传起止时间（或 CrossBackupId），这里用时间窗方式，
    默认最近 7 天，时间格式为 `yyyy-MM-ddTHH:mm:ssZ`（UTC，带秒）。
    """
    page_size = _normalize_backup_page_size(page_size)
    start_value, end_value = _normalize_cross_window(start_time, end_time)
    rds_client = _prepare_client(account_id, region, instance_id)
    try:
        body = rds.describe_cross_region_backups(
            rds_client, instance_id, region, start_value, end_value, page, page_size,
        )
    except Exception as error:
        raise errors.translate_sdk_error(error, 'DescribeCrossRegionBackups') from error

    items = body.items.item if body and body.items else None
    return {
        'items': [_cross_backup_item(item) for item in (items or [])],
        'page': page,
        'page_size': page_size,
        'total': _to_int(body.total_record_count if body else None) or 0,
        'start_time': start_value,
        'end_time': end_value,
    }


def list_cross_region_log_backup_files(account_id: int, region: str, instance_id: str,
                                       start_time: str = '', end_time: str = '',
                                       page: int = 1,
                                       page_size: int = _DEFAULT_BACKUP_PAGE_SIZE) -> dict:
    """分页查询跨地域（异地）日志备份列表，默认最近 7 天。"""
    page_size = _normalize_backup_page_size(page_size)
    start_value, end_value = _normalize_cross_window(start_time, end_time)
    rds_client = _prepare_client(account_id, region, instance_id)
    try:
        body = rds.describe_cross_region_log_backup_files(
            rds_client, instance_id, region, start_value, end_value, page, page_size,
        )
    except Exception as error:
        raise errors.translate_sdk_error(error, 'DescribeCrossRegionLogBackupFiles') from error

    items = body.items.item if body and body.items else None
    return {
        'items': [_cross_log_item(item) for item in (items or [])],
        'page': page,
        'page_size': page_size,
        'total': _to_int(body.total_record_count if body else None) or 0,
        'start_time': start_value,
        'end_time': end_value,
    }


def _normalize_cross_window(start_time: str, end_time: str) -> tuple[str, str]:
    """跨地域接口时间参数带秒，默认窗口最近 7 天。"""
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    default_start = now - datetime.timedelta(days=_CROSS_DEFAULT_WINDOW_DAYS)

    start = _parse_cloud_second(start_time)
    end = _parse_cloud_second(end_time)
    if start is None:
        start = default_start
    if end is None:
        end = now
    if end <= start:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '查询结束时间必须晚于开始时间',
            f'end_time must be greater than start_time: {start_time!r} ~ {end_time!r}',
            400,
        )
    return start.strftime('%Y-%m-%dT%H:%M:%SZ'), end.strftime('%Y-%m-%dT%H:%M:%SZ')


def _parse_cloud_second(value: str):
    """解析 `yyyy-MM-ddTHH:mm:ssZ` UTC 时间串，兼容不带秒的写法。"""
    if not value:
        return None
    import datetime

    text_value = str(value).strip()
    for pattern in ('%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%MZ'):
        try:
            return datetime.datetime.strptime(text_value, pattern).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    raise ApiError(
        response.CODE_BAD_REQUEST,
        '时间参数格式不正确，应为 yyyy-MM-ddTHH:mm:ssZ',
        f'invalid time param: {text_value!r}',
        400,
    )


def _cross_policy_item(body) -> dict:
    """跨地域备份设置；body 为 None（查询失败）时按关闭处理。"""
    if body is None:
        return {
            'backup_enabled': False,
            'log_backup_enabled': False,
            'cross_backup_region': '',
            'retention_days': None,
            'cross_backup_type': '',
        }
    return {
        'backup_enabled': str(body.backup_enabled or '').strip().lower() == 'enable',
        'log_backup_enabled': str(body.log_backup_enabled or '').strip().lower() == 'enable',
        'cross_backup_region': body.cross_backup_region or '',
        'retention_days': _to_int(body.retention),
        'cross_backup_type': _to_str(body.cross_backup_type),
    }


def _cross_backup_item(item) -> dict:
    restore_regions = []
    container = item.restore_regions
    regions = container.restore_region if container else None
    for region in regions or []:
        if region:
            restore_regions.append(str(region))
    return {
        'cross_backup_id': _to_str(item.cross_backup_id),
        'backup_type': item.backup_type or '',
        'backup_method': item.backup_method or '',
        'backup_start_time': item.backup_start_time or '',
        'backup_end_time': item.backup_end_time or '',
        'backup_set_status': item.backup_set_status if item.backup_set_status is not None else None,
        'cross_backup_region': item.cross_backup_region or '',
        'cross_backup_set_file': item.cross_backup_set_file or '',
        'cross_backup_set_size': item.cross_backup_set_size,
        'cross_backup_download_link': item.cross_backup_download_link or '',
        'instance_id': _to_str(item.instance_id),
        'restore_regions': restore_regions,
    }


def _cross_log_item(item) -> dict:
    return {
        'cross_log_backup_id': _to_str(item.cross_log_backup_id),
        'log_file_name': item.log_file_name or '',
        'log_begin_time': item.log_begin_time or '',
        'log_end_time': item.log_end_time or '',
        'file_size': item.cross_log_backup_size,
        'cross_backup_region': item.cross_backup_region or '',
        'download_link': item.cross_download_link or '',
        'intranet_download_link': item.cross_intranet_download_link or '',
        'link_expired_time': item.link_expired_time or '',
        'instance_id': _to_str(item.instance_id),
    }


def _normalize_backup_page_size(page_size: int) -> int:
    """DescribeBackups 的 PageSize 只接受 30/50/100，30 为默认值。"""
    return page_size if page_size in _BACKUP_PAGE_SIZES else _DEFAULT_BACKUP_PAGE_SIZE


def _normalize_binlog_page_size(page_size: int) -> int:
    """DescribeBinlogFiles 的 PageSize 允许 30~100，超出范围就近收敛，不足 30 取 30。"""
    return max(_BINLOG_PAGE_MIN, min(_BINLOG_PAGE_MAX, page_size))


def _normalize_binlog_window(start_time: str, end_time: str) -> tuple[str, str]:
    """补默认时间窗（最近 7 天），有 end 无 start 时同样回退默认。

    返回 `yyyy-MM-ddTHH:mmZ`（UTC）字符串对。
    """
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    default_start = now - datetime.timedelta(days=_BINLOG_DEFAULT_WINDOW_DAYS)

    start = _parse_cloud_minute(start_time)
    end = _parse_cloud_minute(end_time)
    if start is None:
        start = default_start
    if end is None:
        end = now
    if end <= start:
        raise ApiError(
            response.CODE_BAD_REQUEST,
            '查询结束时间必须晚于开始时间',
            f'end_time must be greater than start_time: {start_time!r} ~ {end_time!r}',
            400,
        )
    return _format_cloud_minute(start), _format_cloud_minute(end)


def _parse_cloud_minute(value: str):
    """解析 `yyyy-MM-ddTHH:mmZ` / `yyyy-MM-ddTHH:mm:ssZ` 两种 UTC 时间串。"""
    if not value:
        return None
    import datetime

    text_value = str(value).strip()
    for pattern in ('%Y-%m-%dT%H:%MZ', '%Y-%m-%dT%H:%M:%SZ'):
        try:
            return datetime.datetime.strptime(text_value, pattern).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    raise ApiError(
        response.CODE_BAD_REQUEST,
        '时间参数格式不正确，应为 yyyy-MM-ddTHH:mmZ',
        f'invalid time param: {text_value!r}',
        400,
    )


def _format_cloud_minute(value) -> str:
    return value.strftime('%Y-%m-%dT%H:%MZ')


def _to_int(value):
    """阿里云同一字段可能返回字符串或整数，这里统一成 int，无法解析返回 None。"""
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text_value = str(value).strip().lower()
    if text_value in ('1', 'true', 'yes', 'on'):
        return True
    if text_value in ('0', 'false', 'no', 'off'):
        return False
    return None


def _to_str(value) -> str:
    return '' if value is None else str(value)
