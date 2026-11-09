"""通用类型转换。"""

import datetime


def clean_str(value) -> str:
    if value is None:
        return ''
    return str(value).strip()


def is_blank(value) -> bool:
    return value is None or str(value).strip() == ''


def to_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def to_bit(value) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0


def parse_cloud_time(value: str | None) -> datetime.datetime | None:
    """解析阿里云返回的 UTC 时间，如 2018-11-05T11:26:02Z。"""
    if not value:
        return None
    text_value = str(value).strip()
    try:
        return datetime.datetime.strptime(text_value, '%Y-%m-%dT%H:%M:%SZ')
    except ValueError:
        return None


def parse_cloud_time_local(value: str | None) -> datetime.datetime | None:
    """解析阿里云 UTC 时间并折算为本地时间（+8）。

    dmops 全链路（repo._now / created_at / 前端展示）统一北京时间口径，
    备份时间入库时用它，避免与弹窗/列表的本地时区展示差 8 小时。
    """
    parsed = parse_cloud_time(value)
    if parsed is None:
        return None
    return parsed + datetime.timedelta(hours=8)


def time_to_str(value) -> str:
    if value is None:
        return ''
    if isinstance(value, datetime.datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    return str(value)
