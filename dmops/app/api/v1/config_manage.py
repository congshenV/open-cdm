"""配置管理接口。"""

from flask import Blueprint

from app.service import config_service
from app.util.web import params, response

bp = Blueprint('config_manage', __name__, url_prefix='/v1/configs')


@bp.get('')
def list_configs():
    scope = params.query_str('scope')
    keyword = params.query_str('keyword')
    data = config_service.list_configs(scope=scope, keyword=keyword)
    return response.success_response(data=data)


@bp.get('/<int:config_id>')
def get_config(config_id: int):
    data = config_service.get_config(config_id)
    return response.success_response(data=data)


@bp.post('')
def create_config():
    config_service.create_config(params.json_body())
    return response.success_response(user_message='创建成功')


@bp.put('/<int:config_id>')
def update_config(config_id: int):
    config_service.update_config(config_id, params.json_body())
    return response.success_response(user_message='修改成功')


@bp.delete('/<int:config_id>')
def delete_config(config_id: int):
    config_service.delete_config(config_id)
    return response.success_response(data={'deleted': True, 'config_id': config_id})
