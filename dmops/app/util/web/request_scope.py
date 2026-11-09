"""单次请求的上下文。

用 Flask 的 g 存放，避免跨请求串数据。
"""

import datetime
import uuid
from typing import Optional

from flask import g, has_request_context

from app import config


def init_request_scope() -> None:
    """请求开始时初始化上下文，优先复用上游传来的 requestId。"""
    if not has_request_context():
        return
    from flask import request

    upstream_id = request.headers.get(config.Identity.request_id_header)
    g.request_id = upstream_id or str(uuid.uuid4())
    g.request_begin_ts = datetime.datetime.now()


def get_request_id() -> str:
    if has_request_context() and getattr(g, 'request_id', None):
        return g.request_id
    return ''


def get_request_begin_ts() -> Optional[datetime.datetime]:
    if has_request_context():
        return getattr(g, 'request_begin_ts', None)
    return None


def get_current_uid() -> str:
    """已通过签名校验的用户 uid，由身份校验中间件写入。"""
    if has_request_context():
        return getattr(g, 'current_uid', '')
    return ''
