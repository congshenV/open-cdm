"""路由注册。

新增业务接口时，在这里注册对应 Blueprint。
"""

from flask import Flask

from app.api.v1 import backup, backup_drill, cloud_account, config_manage, instance, ping


def register_route(app: Flask) -> None:
    app.register_blueprint(ping.bp)
    app.register_blueprint(cloud_account.bp)
    app.register_blueprint(instance.bp)
    app.register_blueprint(backup.bp)
    app.register_blueprint(backup_drill.bp)
    app.register_blueprint(config_manage.bp)
