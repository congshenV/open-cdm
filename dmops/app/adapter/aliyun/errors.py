"""阿里云 SDK 异常转换。"""

import logging

from alibabacloud_credentials.exceptions import CredentialException

from app.util.errors import ApiError
from app.util.web import response

logger = logging.getLogger(__name__)


def translate_sdk_error(error: Exception, action: str) -> ApiError:
    """把 SDK 异常转换为统一的 ApiError，保留阿里云错误码和 RequestId。"""
    code = str(getattr(error, 'code', '') or '')
    message = str(getattr(error, 'message', '') or error)
    request_id = ''
    data = getattr(error, 'data', None)
    if isinstance(data, dict):
        request_id = str(data.get('RequestId') or data.get('requestId') or '')
    detail = f'{code}: {message}'.strip(': ')
    if request_id:
        detail = f'{detail} requestId={request_id}'

    logger.warning('[dmops] aliyun api failed action=%s code=%s detail=%s', action, code, detail)

    if isinstance(error, CredentialException) or code == 'InvalidCredentials':
        return ApiError(
            code=response.CODE_BAD_REQUEST,
            user_message='阿里云凭据获取失败，请检查认证配置',
            message=detail,
            http_status=400,
        )
    if code in ('InvalidDBInstanceId.NotFound', 'InvalidRegionId.NotFound'):
        return ApiError(
            code=response.CODE_NOT_FOUND,
            user_message='实例或地域不存在',
            message=detail,
            http_status=404,
        )
    if code in (
        'InvalidAccessKeyId.NotFound', 'InvalidAccessKeyId.Inactive',
        'Forbidden.AccessKey', 'InvalidSecurityToken.Expired',
        'InvalidSecurityToken.MismatchWithAccessKey', 'InvalidSecurityToken.Malformed',
    ):
        return ApiError(
            code=response.CODE_BAD_REQUEST,
            user_message='阿里云账号认证失败，请检查认证配置',
            message=detail,
            http_status=400,
        )
    if code in ('InvalidUserOperatorPermission', 'Forbidden', 'Forbidden.RAM', 'NoPermission'):
        return ApiError(
            code=response.CODE_FORBIDDEN,
            user_message='没有权限执行该操作',
            message=detail,
            http_status=403,
        )
    if 'Throttling' in code:
        return ApiError(
            code=response.CODE_TOO_MANY_REQUESTS,
            user_message='阿里云接口限流，请稍后重试',
            message=detail,
            http_status=429,
        )
    return ApiError(
        code=response.CODE_INTERNAL_ERROR,
        user_message=f'调用阿里云接口失败：{action}',
        message=detail,
        http_status=500,
    )
