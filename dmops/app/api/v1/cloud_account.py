"""阿里云账号、认证、地域与同步接口。"""

from flask import Blueprint

from app.service import cloud_account_service
from app.util.convert import to_bool
from app.util.web import params, response

bp = Blueprint('cloud_account', __name__, url_prefix='/v1/cloud')


@bp.get('/accounts')
def list_accounts():
    keyword = params.query_str('keyword')
    enabled_raw = params.query_str('enabled')
    enabled = None if enabled_raw == '' else to_bool(enabled_raw)
    page = params.query_int('page', 1, minimum=1)
    page_size = params.query_int('page_size', 20, minimum=1, maximum=100)
    data = cloud_account_service.list_accounts(keyword, enabled, page, page_size)
    return response.success_response(data=data)


@bp.post('/accounts')
def create_account():
    data = cloud_account_service.create_account(params.json_body())
    return response.success_response(data=data)


@bp.get('/accounts/<int:account_id>')
def get_account(account_id: int):
    data = cloud_account_service.get_account(account_id)
    return response.success_response(data=data)


@bp.put('/accounts/<int:account_id>')
def update_account(account_id: int):
    data = cloud_account_service.update_account(account_id, params.json_body())
    return response.success_response(data=data)


@bp.delete('/accounts/<int:account_id>')
def delete_account(account_id: int):
    cloud_account_service.delete_account(account_id)
    return response.success_response(data={'deleted': True, 'account_id': account_id})


@bp.get('/accounts/<int:account_id>/regions')
def list_regions(account_id: int):
    data = cloud_account_service.list_regions(account_id)
    return response.success_response(data=data)


@bp.post('/accounts/<int:account_id>/sync')
def sync_instances(account_id: int):
    data = cloud_account_service.sync_instances(account_id)
    return response.success_response(data=data)


@bp.get('/accounts/<int:account_id>/credential')
def get_credential(account_id: int):
    data = cloud_account_service.get_credential(account_id)
    return response.success_response(data=data)


@bp.put('/accounts/<int:account_id>/credential')
def upsert_credential(account_id: int):
    data = cloud_account_service.upsert_credential(account_id, params.json_body())
    return response.success_response(data=data)


@bp.delete('/accounts/<int:account_id>/credential')
def delete_credential(account_id: int):
    cloud_account_service.delete_credential(account_id)
    return response.success_response(data={'deleted': True, 'account_id': account_id})
