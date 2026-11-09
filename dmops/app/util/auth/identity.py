"""console 转发请求的身份校验。

CloudDM console 转发 ``/api/dmops/**`` 时会注入：

    X-DmOps-User       当前登录用户 uid
    X-DmOps-Signature  Base64(HmacSHA1(uid, identitySecret))
    X-DmOps-Is-Admin   是否为管理员（console 按 maintainer / 主账号判定）
    X-Request-Id       请求追踪 ID

签名算法必须与 CloudDM 的 ``OpenApiSigner.signString`` 保持字节级一致：
HmacSHA1 + UTF-8 + Base64。dmops 不能假设"经过 console 就可信"；
管理员标志同样由代理强制覆盖，客户端伪造无效（签名头也只有 console 能产生）。
"""

import base64
import hashlib
import hmac
import logging
import re

from flask import g, request

from app import config
from app.util.web import response

logger = logging.getLogger(__name__)

_HMAC_ALGORITHM = hashlib.sha1

# 配置详情接口返回解密明文，读操作也仅管理员可见。
_CONFIG_DETAIL_PATH = re.compile(r'^/v1/configs/\d+$')


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


def verify_admin() -> object | None:
    """写操作与配置明文详情仅管理员可用。

    规则（与 console 代理注入的 X-DmOps-Is-Admin 配合）：
    - GET/HEAD/OPTIONS 只读请求放行，唯一例外是配置详情（返回解密明文）；
    - 其余方法（POST/PUT/DELETE）均为写操作，要求管理员；
    - 本地调试关闭身份校验时视为管理员，保持直连可用。
    """
    if not config.Identity.verify_enabled:
        return None

    is_write = request.method.upper() not in ('GET', 'HEAD', 'OPTIONS')
    is_config_detail = request.method.upper() == 'GET' and _CONFIG_DETAIL_PATH.match(request.path)
    if not is_write and not is_config_detail:
        return None

    if request.headers.get(config.Identity.admin_header, '').strip().lower() == 'true':
        return None

    logger.warning('[dmops] 非管理员请求被拒绝 method=%s uri=%s', request.method, request.path)
    return response.error_response(
        code=response.CODE_FORBIDDEN,
        user_message='仅管理员可执行该操作',
        message='non-admin request on privileged endpoint',
        http_status=403,
    )
