"""健康检查与冒烟测试接口。

用于验证 console 代理链路是否正常。
"""

import datetime

from flask import Blueprint

from app.util.web import response

bp = Blueprint('ping', __name__, url_prefix='/v1')


@bp.get('/ping')
def ping():
    """连通性验证。"""
    data = {
        'service': 'dmops',
        'status': 'UP',
        'time': datetime.datetime.now().isoformat(),
    }
    return response.success_response(data=data)


@bp.get('/hello')
def hello():
    """冒烟测试，返回 hello world。"""
    data = {
        'message': 'hello world',
        'service': 'dmops',
    }
    return response.success_response(data=data)
