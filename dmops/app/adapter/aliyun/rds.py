"""RDS OpenAPI 调用封装。

只做参数组装和结果提取，异常由 service 层统一转换。
"""

import logging
from typing import Any

from alibabacloud_rds20140815 import models as rds_models
from alibabacloud_rds20140815.client import Client as RdsClient

logger = logging.getLogger(__name__)


def describe_region_infos(client: RdsClient) -> list[str]:
    """查询账号下有 RDS 服务的地域列表。"""
    request = rds_models.DescribeRegionInfosRequest()
    response = client.describe_region_infos(request)
    body = response.body
    regions = body.regions.rdsregion if body and body.regions else None
    return [
        item.region_id.strip()
        for item in (regions or [])
        if item and item.region_id and item.region_id.strip()
    ]


def describe_all_instances(client: RdsClient, region: str,
                           max_items: int) -> tuple[list[Any], bool]:
    """按 NextToken 拉取一个地域下的全部实例，最多 max_items 条。

    返回 (实例列表, 是否被截断)。被截断时调用方不能把未返回的实例标记为已释放。
    """
    items: list[Any] = []
    next_token: str | None = None

    while True:
        request = rds_models.DescribeDBInstancesRequest(
            region_id=region,
            max_results=100,
            next_token=next_token,
            instance_level=1,
        )
        response = client.describe_dbinstances(request)
        body = response.body

        page_items = body.items.dbinstance if body and body.items else None
        items.extend(page_items or [])

        next_token = body.next_token if body else None
        if not next_token:
            return items, False

        if len(items) >= max_items:
            logger.warning(
                '[dmops] rds instance sync truncated region=%s max_items=%s',
                region, max_items,
            )
            return items[:max_items], True


def describe_instance_tags(client: RdsClient, region: str) -> dict[str, dict[str, str]]:
    """按地域拉取实例标签，返回 {instance_id: {tag_key: tag_value}}。

    DescribeDBInstanceByTags 无需传 DBInstanceId，一次可以取回整个地域的标签，
    比逐台查询省调用次数。未打标签的实例不会出现在结果里，由调用方用默认值兜底。
    """
    tags_by_instance: dict[str, dict[str, str]] = {}
    page_number = 1

    while True:
        request = rds_models.DescribeDBInstanceByTagsRequest(
            region_id=region,
            page_size=100,
            page_number=page_number,
        )
        response = client.describe_dbinstance_by_tags(request)
        body = response.body
        page_items = body.items.dbinstance_tag if body and body.items else None

        for item in page_items or []:
            if not item or not item.dbinstance_id:
                continue
            tag_container = item.tags
            tag_items = tag_container.tag if tag_container else None
            tags: dict[str, str] = {}
            for tag in tag_items or []:
                if tag and tag.tag_key:
                    tags[tag.tag_key.strip().lower()] = tag.tag_value or ''
            tags_by_instance[item.dbinstance_id] = tags

        if not page_items or len(page_items) < 100:
            return tags_by_instance
        page_number += 1


def describe_instance_attribute(client: RdsClient, instance_id: str) -> Any | None:
    """查询单个实例详情。"""
    request = rds_models.DescribeDBInstanceAttributeRequest(dbinstance_id=instance_id)
    response = client.describe_dbinstance_attribute(request)
    body = response.body
    attributes = body.items.dbinstance_attribute if body and body.items else None
    return attributes[0] if attributes else None


def clone_db_instance(client: RdsClient, params: dict) -> tuple[str, str]:
    """按备份集克隆实例（CloneDBInstance）。

    params 由 service 层按 §2.1 映射表组装，这里只透传；ClientToken 做幂等键，
    同一 drill_no 重复提交不会创建两个实例。返回 (克隆实例 ID, 订单 ID)。

    Serverless 源实例时 pay_type=Serverless 且 serverless_config 透传源实例 RCU
    配置（§2.1-D3）；非 Serverless 一律 Postpaid。
    """
    request = rds_models.CloneDBInstanceRequest(
        dbinstance_id=params['dbinstance_id'],
        region_id=params['region_id'],
        zone_id=params['zone_id'],
        backup_id=params['backup_id'],
        backup_type=params['backup_type'],
        dbinstance_description=params['dbinstance_description'],
        dbinstance_storage_type=params['dbinstance_storage_type'],
        instance_network_type=params['instance_network_type'],
        vpcid=params['vpcid'],
        v_switch_id=params['v_switch_id'],
        pay_type=params.get('pay_type') or 'Postpaid',
        deletion_protection=False,
        auto_pay=True,
        client_token=params['client_token'],
    )
    serverless = params.get('serverless_config')
    if serverless:
        # 详情返回字段名 scale_min/scale_max，请求字段名 min_capacity/max_capacity。
        request.serverless_config = rds_models.CloneDBInstanceRequestServerlessConfig(
            min_capacity=serverless.get('min_capacity'),
            max_capacity=serverless.get('max_capacity'),
            auto_pause=serverless.get('auto_pause'),
            switch_force=serverless.get('switch_force'),
        )
    response = client.clone_dbinstance(request)
    body = response.body
    return (body.dbinstance_id or '', body.order_id or '')


def describe_backup_policy(client: RdsClient, instance_id: str) -> Any:
    """查询实例备份设置，包含数据备份与日志备份策略。"""
    request = rds_models.DescribeBackupPolicyRequest(dbinstance_id=instance_id)
    response = client.describe_backup_policy(request)
    return response.body


def describe_backups(client: RdsClient, instance_id: str, page_number: int,
                     page_size: int) -> Any:
    """分页查询实例备份集列表，按开始时间倒序（阿里云默认排序）。"""
    request = rds_models.DescribeBackupsRequest(
        dbinstance_id=instance_id,
        page_number=page_number,
        page_size=page_size,
    )
    response = client.describe_backups(request)
    return response.body


def describe_instance_cross_backup_policy(client: RdsClient, instance_id: str,
                                         region: str) -> Any:
    """查询实例跨地域（异地）备份设置。"""
    request = rds_models.DescribeInstanceCrossBackupPolicyRequest(
        dbinstance_id=instance_id,
        region_id=region,
    )
    response = client.describe_instance_cross_backup_policy(request)
    return response.body


def describe_cross_region_backups(client: RdsClient, instance_id: str, region: str,
                                  start_time: str, end_time: str, page_number: int,
                                  page_size: int) -> Any:
    """分页查询跨地域备份集列表。

    阿里云要求 CrossBackupId 或起止时间二选一，这里固定用起止时间。
    """
    request = rds_models.DescribeCrossRegionBackupsRequest(
        dbinstance_id=instance_id,
        region_id=region,
        start_time=start_time,
        end_time=end_time,
        page_number=page_number,
        page_size=page_size,
    )
    response = client.describe_cross_region_backups(request)
    return response.body


def describe_cross_region_log_backup_files(client: RdsClient, instance_id: str,
                                           region: str, start_time: str,
                                           end_time: str, page_number: int,
                                           page_size: int) -> Any:
    """分页查询跨地域日志备份列表。"""
    request = rds_models.DescribeCrossRegionLogBackupFilesRequest(
        dbinstance_id=instance_id,
        region_id=region,
        start_time=start_time,
        end_time=end_time,
        page_number=page_number,
        page_size=page_size,
    )
    response = client.describe_cross_region_log_backup_files(request)
    return response.body


def describe_binlog_files(client: RdsClient, instance_id: str, start_time: str,
                          end_time: str, page_number: int, page_size: int) -> Any:
    """分页查询实例日志备份（MySQL Binlog / PostgreSQL WAL）。

    阿里云要求 start/end 为必填的 UTC 时间串，由 service 层负责补默认时间窗。
    """
    request = rds_models.DescribeBinlogFilesRequest(
        dbinstance_id=instance_id,
        start_time=start_time,
        end_time=end_time,
        page_number=page_number,
        page_size=page_size,
    )
    response = client.describe_binlog_files(request)
    return response.body
