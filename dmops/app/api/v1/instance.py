"""RDS 实例列表与详情接口。"""

from flask import Blueprint

from app.service import instance_service
from app.util.web import params, response

bp = Blueprint('instance', __name__, url_prefix='/v1')


@bp.get('/instances')
def list_instances():
    account_id = params.query_int('account_id', 0, minimum=1)
    region = params.query_str('region')
    keyword = params.query_str('keyword')
    status = params.query_str('status')
    page = params.query_int('page', 1, minimum=1)
    page_size = params.query_int('page_size', 20, minimum=1, maximum=100)
    data = instance_service.list_instances(
        account_id=account_id,
        region=region,
        keyword=keyword,
        status=status,
        page=page,
        page_size=page_size,
    )
    return response.success_response(data=data)


@bp.get('/instances/disk-usage')
def instance_disk_usage():
    account_id = params.query_int('account_id', 0, minimum=1)
    items = params.query_str('items')
    data = instance_service.disk_usage(account_id, items)
    return response.success_response(data=data)


@bp.get('/instances/<instance_id>')
def get_instance_detail(instance_id: str):
    account_id = params.query_int('account_id', 0, minimum=1)
    region = params.query_str('region')
    data = instance_service.get_instance_detail(account_id, region, instance_id)
    return response.success_response(data=data)
