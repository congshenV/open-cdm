"""备份恢复演练接口（一期：克隆链路）。"""

from flask import Blueprint

from app.service import backup_drill_service
from app.util.web import params, response

bp = Blueprint('backup_drill', __name__, url_prefix='/v1')


@bp.get('/instances/<instance_id>/drill-preflight')
def drill_preflight(instance_id: str):
    account_id = params.query_int('account_id', 0, minimum=1)
    region = params.query_str('region')
    data = backup_drill_service.preflight(account_id, region, instance_id)
    return response.success_response(data=data)


@bp.post('/backup-drills')
def create_drill():
    body = params.json_body()
    data = backup_drill_service.create_drill(body)
    return response.success_response(data=data)


@bp.get('/backup-drills')
def list_drills():
    account_id = params.query_int('account_id', 0)
    instance_id = params.query_str('instance_id')
    status = params.query_str('status')
    offline = params.query_str('offline') == '1'
    page = params.query_int('page', 1, minimum=1)
    page_size = params.query_int('page_size', 20, minimum=1, maximum=100)
    data = backup_drill_service.list_drills(
        account_id=account_id,
        instance_id=instance_id,
        status=status,
        offline=offline,
        page=page,
        page_size=page_size,
    )
    return response.success_response(data=data)


@bp.get('/backup-drills/<int:drill_id>')
def get_drill(drill_id: int):
    data = backup_drill_service.get_drill(drill_id)
    return response.success_response(data=data)


@bp.post('/backup-drills/<int:drill_id>/cancel')
def cancel_drill(drill_id: int):
    data = backup_drill_service.cancel_drill(drill_id)
    return response.success_response(data=data)


@bp.post('/backup-drills/<int:drill_id>/confirm-offline')
def confirm_offline(drill_id: int):
    data = backup_drill_service.confirm_offline(drill_id)
    return response.success_response(data=data)


# ---- 注册数据源（源端/克隆实例，JWT 透传调 console）----

@bp.get('/backup-drills/<int:drill_id>/register-ds/<target>/prefill')
def register_ds_prefill(drill_id: int, target: str):
    """注册弹窗预填：目标实例连接地址/端口/引擎映射/默认描述。"""
    data = backup_drill_service.register_ds_prefill(drill_id, target)
    return response.success_response(data=data)


@bp.post('/backup-drills/<int:drill_id>/register-ds/<target>/test')
def register_ds_test(drill_id: int, target: str):
    """测试连接（connectDs 真实建连，不落库）。"""
    body = params.json_body()
    data = backup_drill_service.register_ds_test(drill_id, target, body)
    return response.success_response(data=data)


@bp.post('/backup-drills/<int:drill_id>/register-ds/<target>/submit')
def register_ds_submit(drill_id: int, target: str):
    """提交新增（addDs），dsId 回写演练表。"""
    body = params.json_body()
    data = backup_drill_service.register_ds_submit(drill_id, target, body)
    return response.success_response(data=data)


# ---- 数据校验（半自动）----

@bp.post('/backup-drills/<int:drill_id>/verify-db-tables')
def verify_db_tables(drill_id: int):
    """库名 + 每库表数量对比（触发即追加一条校验记录）。"""
    data = backup_drill_service.verify_db_tables(drill_id)
    return response.success_response(data=data)


@bp.get('/backup-drills/<int:drill_id>/drill-tables')
def drill_tables(drill_id: int):
    """选表辅助：源端全部候选表及主键/自动更新列标注（前端搜索过滤）。"""
    data = backup_drill_service.drill_tables(drill_id)
    return response.success_response(data=data)


@bp.post('/backup-drills/<int:drill_id>/verify-table-data')
def verify_table_data(drill_id: int):
    """表数据校验（选定表逐表稳定行采样对比，同步执行）。"""
    body = params.json_body()
    data = backup_drill_service.verify_table_data(drill_id, body.get('target_tables'))
    return response.success_response(data=data)


@bp.get('/backup-drills/<int:drill_id>/verifications')
def list_verifications(drill_id: int):
    """校验历史（含每步 diff 明细）。"""
    data = backup_drill_service.list_verifications(drill_id)
    return response.success_response(data=data)
