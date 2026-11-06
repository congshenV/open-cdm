"""阿里云 RDS OpenAPI 客户端工厂。

客户端按 (account_id, credential version, region) 缓存；
不同账号、不同地域不能复用同一个客户端。
"""

import logging
import threading

from alibabacloud_rds20140815.client import Client as RdsClient
from alibabacloud_tea_openapi import models as open_api_models

from app import config
from app.adapter.aliyun import credentials

logger = logging.getLogger(__name__)

_cache: dict[tuple[int, int, str], RdsClient] = {}
_lock = threading.Lock()


def get_rds_client(account_id: int, credential: dict, region: str) -> RdsClient:
    region = (region or 'cn-hangzhou').strip()
    version = int(credential.get('version') or 0)
    key = (account_id, version, region)

    with _lock:
        client = _cache.get(key)
    if client is not None:
        return client

    credential_client = credentials.get_credential_client(account_id, credential)
    openapi_config = open_api_models.Config(
        credential=credential_client,
        endpoint=f'rds.{region}.aliyuncs.com',
        read_timeout=config.Aliyun.read_timeout_ms,
        connect_timeout=config.Aliyun.connect_timeout_ms,
    )
    openapi_config.region_id = region

    client = RdsClient(openapi_config)
    with _lock:
        # 清理该账号旧凭据版本留下的客户端，避免缓存无限增长。
        for old_key in [item for item in _cache if item[0] == account_id and item[1] != version]:
            _cache.pop(old_key, None)
        _cache[key] = client
    logger.info(
        '[dmops] aliyun rds client ready account=%s region=%s credential_version=%s',
        account_id, region, version,
    )
    return client


def invalidate_account(account_id: int) -> None:
    with _lock:
        for key in [key for key in _cache if key[0] == account_id]:
            _cache.pop(key, None)
