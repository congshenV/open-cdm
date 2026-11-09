"""统一响应体。

采用 dms-service 的结构，并额外提供 CloudDM 风格的 ``success`` 字段，
让两种前端都能直接判断成功与否：

    {
      "success": true,           # CloudDM 风格，补充字段
      "code": 0,                 # dms-service 风格，0 表示成功
      "userMessage": "操作成功",   # 给用户看
      "message": "操作成功",       # 给开发看
      "data": {...},
      "ctx": {
        "requestId": "...",
        "requestBeginTs": "...",
        "costTime": 0.004,
        "atHostname": "..."
      }
    }

``code`` 保持 int 语义（0 成功），不做成字符串，避免两套体系混淆；
需要判真假的地方用 ``success``。
"""

import datetime
import logging
from typing import Any

from flask import jsonify

from app import config
from app.util.web.request_scope import get_request_begin_ts, get_request_id

logger = logging.getLogger(__name__)

# 成功与常见失败的业务码。
CODE_SUCCESS = 0
CODE_WARNING = 1
CODE_UNAUTHORIZED = -401
CODE_FORBIDDEN = -403
CODE_BAD_REQUEST = -400
CODE_NOT_FOUND = -404
CODE_CONFLICT = -409
CODE_TOO_MANY_REQUESTS = -429
CODE_INTERNAL_ERROR = -500


def _build_ctx() -> dict:
    begin_ts = get_request_begin_ts()
    now = datetime.datetime.now()
    if begin_ts is None:
        cost_time = 0.0
    else:
        cost_time = round((now - begin_ts).total_seconds(), 6)
    return {
        'requestId': get_request_id(),
        'requestBeginTs': begin_ts.isoformat() if begin_ts else '',
        'costTime': cost_time,
        'atHostname': config.Hostname,
    }


def success_response(data: Any = None, code: int = CODE_SUCCESS, user_message: str = '操作成功', message: str = '') -> Any:
    """构造成功响应。"""
    if data is None:
        data = {}
    if not message:
        message = user_message
    body = {
        'success': True,
        'code': code,
        'userMessage': user_message,
        'message': message,
        'data': data,
        'ctx': _build_ctx(),
    }
    return jsonify(body), 200


def error_response(code: int, user_message: str, message: str = '', http_status: int = 400) -> Any:
    """构造失败响应。

    ``http_status`` 保持语义正确，不要一律返回 200，
    这样 console 代理层可以直接透传状态码。
    """
    if not message:
        message = user_message
    body = {
        'success': False,
        'code': code,
        'userMessage': user_message,
        'message': message,
        'data': {},
        'ctx': _build_ctx(),
    }
    return jsonify(body), http_status
