"""dmops 应用入口。

    create_app()  构造 Flask 应用，供 gunicorn 或测试使用
    python main.py  本地开发启动
"""

import logging

from flask import Flask
from werkzeug.exceptions import HTTPException

from app import config
from app.route import register_route
from app.util.auth import identity
from app.util.errors import ApiError
from app.util.web import request_scope, response
from app.worker import backup_drill_worker

logger = logging.getLogger(__name__)


def _config_log() -> None:
    logging.basicConfig(
        level=getattr(logging, config.Log.level.upper(), logging.INFO),
        format=config.Log.format,
        datefmt=config.Log.date_fmt,
        force=True,
    )


def _check_identity() -> None:
    """启动时校验身份配置。

    secret 缺失时每个请求都会 401，只会在 console 日志里留下一串 401，排查成本很高，
    所以这里直接拒绝启动，把原因写在第一屏日志里。
    """
    if not config.Identity.verify_enabled:
        logger.warning('[dmops] 身份校验已关闭（DMOPS_IDENTITY_VERIFY_ENABLED=false），仅可用于本地直连调试')
        return

    secret = config.Identity.secret
    if not secret:
        logger.error('[dmops] DMOPS_IDENTITY_SECRET 为空，console 转发过来的请求会全部 401')
        logger.error('[dmops] 本地开发：把 console 的 dmops.proxy.identity.secret 写进 dmops/.env，再 make run')
        raise RuntimeError('DMOPS_IDENTITY_SECRET is empty, console forwarded requests cannot be verified')

    logger.info('[dmops] 身份校验已开启，secret 长度=%d', len(secret))


def _register_hooks(app: Flask) -> None:
    @app.before_request
    def before_request_hook():
        request_scope.init_request_scope()
        # 所有接口统一要求合法身份，不做例外。
        failed = identity.verify_identity()
        if failed is not None:
            return failed
        # 写操作与配置明文详情仅管理员可用（console 代理注入管理员标志）。
        failed = identity.verify_admin()
        if failed is not None:
            return failed

    @app.teardown_request
    def teardown_request_hook(_exc):
        # 为当前请求释放资源预留；目前无连接池。
        return None


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return response.error_response(
            code=error.code,
            user_message=error.user_message,
            message=error.message,
            http_status=error.http_status,
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException):
        if error.code == 404:
            return response.error_response(
                code=response.CODE_NOT_FOUND,
                user_message='接口不存在',
                message=f'route not found: {error.description}',
                http_status=404,
            )
        return response.error_response(
            code=-int(error.code or 500),
            user_message=error.name,
            message=error.description or '',
            http_status=error.code or 500,
        )

    @app.errorhandler(Exception)
    def handle_unexpected_exception(error: Exception):
        logger.exception('[dmops] 未捕获异常: %s', error)
        return response.error_response(
            code=response.CODE_INTERNAL_ERROR,
            user_message='服务内部错误',
            message=repr(error),
            http_status=500,
        )


def create_app() -> Flask:
    _config_log()
    _check_identity()

    app = Flask(__name__)
    # Flask 2.2+ 用 app.json 控制序列化，JSON_AS_ASCII 已失效。
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    _register_error_handlers(app)
    _register_hooks(app)
    register_route(app)

    # 备份恢复演练 worker（§8：gunicorn -w 1 单进程，线程仅此一份）。
    backup_drill_worker.start()

    return app


if __name__ == '__main__':
    create_app().run(host=config.Server.host, port=config.Server.port, debug=config.Server.debug)
