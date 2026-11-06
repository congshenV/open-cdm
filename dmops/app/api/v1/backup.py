"""RDS 备份策略与备份列表接口。"""

from flask import Blueprint

from app.service import backup_service
from app.util.web import params, response

bp = Blueprint('backup', __name__, url_prefix='/v1')


@bp.get('/instances/<instance_id>/backup-policy')
def get_backup_policy(instance_id: str):
    account_id = params.query_int('account_id', 0, minimum=1)
    region = params.query_str('region')
    data = backup_service.get_backup_policy(account_id, region, instance_id)
    return response.success_response(data=data)


@bp.get('/instances/<instance_id>/backups')
def list_backups(instance_id: str):
    account_id = params.query_int('account_id', 0, minimum=1)
    region = params.query_str('region')
    page = params.query_int('page', 1, minimum=1)
    page_size = params.query_int('page_size', 30, minimum=1, maximum=100)
    data = backup_service.list_backups(
        account_id=account_id,
        region=region,
        instance_id=instance_id,
        page=page,
        page_size=page_size,
    )
    return response.success_response(data=data)


@bp.get('/instances/<instance_id>/binlog-files')
def list_binlog_files(instance_id: str):
    account_id = params.query_int('account_id', 0, minimum=1)
    region = params.query_str('region')
    start_time = params.query_str('start_time')
    end_time = params.query_str('end_time')
    page = params.query_int('page', 1, minimum=1)
    page_size = params.query_int('page_size', 30, minimum=1, maximum=100)
    data = backup_service.list_binlog_files(
        account_id=account_id,
        region=region,
        instance_id=instance_id,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )
    return response.success_response(data=data)


@bp.get('/instances/<instance_id>/cross-region-backups')
def list_cross_region_backups(instance_id: str):
    account_id = params.query_int('account_id', 0, minimum=1)
    region = params.query_str('region')
    start_time = params.query_str('start_time')
    end_time = params.query_str('end_time')
    page = params.query_int('page', 1, minimum=1)
    page_size = params.query_int('page_size', 30, minimum=1, maximum=100)
    data = backup_service.list_cross_region_backups(
        account_id=account_id,
        region=region,
        instance_id=instance_id,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )
    return response.success_response(data=data)


@bp.get('/instances/<instance_id>/cross-region-log-backup-files')
def list_cross_region_log_backup_files(instance_id: str):
    account_id = params.query_int('account_id', 0, minimum=1)
    region = params.query_str('region')
    start_time = params.query_str('start_time')
    end_time = params.query_str('end_time')
    page = params.query_int('page', 1, minimum=1)
    page_size = params.query_int('page_size', 30, minimum=1, maximum=100)
    data = backup_service.list_cross_region_log_backup_files(
        account_id=account_id,
        region=region,
        instance_id=instance_id,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )
    return response.success_response(data=data)
