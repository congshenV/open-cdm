"""console 转发请求的身份校验。

CloudDM console 转发 ``/api/dmops/**`` 时会注入：

    X-DmOps-User       当前登录用户 uid
    X-DmOps-Signature  Base64(HmacSHA1(uid, identitySecret))
    X-Request-Id       请求追踪 ID

签名算法必须与 CloudDM 的 ``OpenApiSigner.signString`` 保持字节级一致：
HmacSHA1 + UTF-8 + Base64。dmops 不能假设"经过 console 就可信"。
"""

import base64
import hashlib
import hmac
import logging

from flask import g, request

from app import config
from app.util.web import response

logger = logging.getLogger(__name__)

_HMAC_ALGORITHM = hashlib.sha1


def sign_identity(uid: str, secret: str) -> str:
    """计算身份签名，与 CloudDM OpenApiSigner 保持一致。"""
    digest = hmac.new(secret.encode('utf-8'), uid.encode('utf-8'), _HMAC_ALGORITHM).digest()
    return base64.b64encode(digest).decode('utf-8')


def verify_identity() -> object | None:
    """校验请求身份。

    通过时返回 None，并把 uid 写入请求上下文；
    失败时返回响应对象，由调用方直接返回。
    """
    if not config.Identity.verify_enabled:
        uid = request.headers.get(config.Identity.user_header, '')
        g.current_uid = uid
        return None

    secret = config.Identity.secret
    if not secret:
        logger.error('[dmops] identity.secret 未配置，拒绝所有请求')
        return response.error_response(
            code=response.CODE_UNAUTHORIZED,
            user_message='服务未完成身份配置',
            message='DMOPS_IDENTITY_SECRET is empty',
            http_status=401,
        )

    uid = request.headers.get(config.Identity.user_header, '')
    signature = request.headers.get(config.Identity.signature_header, '')
    if not uid or not signature:
        logger.warning('[dmops] 缺少身份头 uri=%s', request.path)
        return response.error_response(
            code=response.CODE_UNAUTHORIZED,
            user_message='缺少身份信息',
            message='missing identity header',
            http_status=401,
        )

    expected = sign_identity(uid, secret)
    if not hmac.compare_digest(expected, signature):
        logger.warning('[dmops] 身份签名不匹配 uri=%s uid=%s', request.path, uid)
        return response.error_response(
            code=response.CODE_UNAUTHORIZED,
            user_message='身份校验失败',
            message='invalid identity signature',
            http_status=401,
        )

    g.current_uid = uid
    return None
