"""identity.verify_admin 单测：写操作与配置明文详情的管理员拦截。"""

import pytest
from flask import Flask

from app.util.auth import identity


@pytest.fixture()
def flask_app():
    return Flask(__name__)


@pytest.fixture()
def enforce(monkeypatch):
    """打开身份校验（生产语义）。"""
    from app import config as config_module

    monkeypatch.setattr(config_module.Identity, 'verify_enabled', True)
    return config_module.Identity


def test_verify_admin_disabled_identity_allows_all(flask_app, monkeypatch):
    """本地调试关闭身份校验：不做权限控制。"""
    from app import config as config_module

    monkeypatch.setattr(config_module.Identity, 'verify_enabled', False)
    with flask_app.test_request_context('/v1/backup-drills', method='POST'):
        assert identity.verify_admin() is None


def test_verify_admin_blocks_non_admin_write(flask_app, enforce):
    """写请求无管理员标志：403。"""
    with flask_app.test_request_context(
        '/v1/backup-drills', method='POST',
        headers={enforce.admin_header: 'false'},
    ):
        failed = identity.verify_admin()
        assert failed is not None
        assert failed[1] == 403


def test_verify_admin_allows_admin_write(flask_app, enforce):
    """写请求带管理员标志：放行。"""
    with flask_app.test_request_context(
        '/v1/backup-drills', method='POST',
        headers={enforce.admin_header: 'true'},
    ):
        assert identity.verify_admin() is None


def test_verify_admin_missing_header_blocks_write(flask_app, enforce):
    """缺少管理员标志头（非 console 注入）：按非管理员处理。"""
    with flask_app.test_request_context('/v1/backup-drills', method='POST'):
        failed = identity.verify_admin()
        assert failed is not None
        assert failed[1] == 403


def test_verify_admin_allows_read_endpoints(flask_app, enforce):
    """只读接口不拦：列表/详情/报告。"""
    for path in ('/v1/backup-drills', '/v1/backup-drills/2', '/v1/configs',
                 '/v1/instances/rm-x/backups', '/v1/backup-drills/2/report'):
        with flask_app.test_request_context(path, method='GET'):
            assert identity.verify_admin() is None, path


def test_verify_admin_blocks_config_detail_read(flask_app, enforce):
    """配置详情返回解密明文：读操作也仅管理员可见。"""
    with flask_app.test_request_context('/v1/configs/3', method='GET'):
        failed = identity.verify_admin()
        assert failed is not None
        assert failed[1] == 403

    with flask_app.test_request_context(
        '/v1/configs/3', method='GET',
        headers={enforce.admin_header: 'true'},
    ):
        assert identity.verify_admin() is None
