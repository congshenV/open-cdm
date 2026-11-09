"""get_by_key 解密闭环单测：加密配置项读出明文，消费方 JSON 异常显式报错。"""

import pytest

from app.infra import config_repository as config_repo
from app.service import backup_drill_service
from app.service.config_service import decrypt_value, encrypt_value
from app.util.errors import ApiError


@pytest.fixture()
def encrypt_secret(monkeypatch):
    """固定测试密钥（32 字节），加解密同钥。"""
    from app import config as config_module

    monkeypatch.setattr(config_module.Config, 'encrypt_secret', '0' * 32)
    return '0' * 32


def test_get_by_key_decrypts_encrypted_row(sqlite_engine, encrypt_secret):
    """is_encrypt=1 的行：get_by_key 返回解密后的明文（与 get_config 同口径）。"""
    plain = '{"user": "admin", "passwd": "secret"}'
    with config_repo.get_engine().begin() as conn:
        from sqlalchemy import text

        conn.execute(text('''
            INSERT INTO ops_config
                (config_name, config_scope, config_type, config_key, config_value,
                 is_encrypt, create_user, description)
            VALUES
                ('t', 'rds', 'json', 'k_enc', :value, 1, 'tester', '')
        '''), {'value': encrypt_value(plain)})
        conn.execute(text('''
            INSERT INTO ops_config
                (config_name, config_scope, config_type, config_key, config_value,
                 is_encrypt, create_user, description)
            VALUES
                ('t', 'rds', 'json', 'k_plain', :value, 0, 'tester', '')
        '''), {'value': plain})

    assert config_repo.get_by_key('k_enc')['config_value'] == plain
    assert config_repo.get_by_key('k_plain')['config_value'] == plain


def test_get_by_key_missing_returns_none(sqlite_engine):
    assert config_repo.get_by_key('no_such_key') is None


def test_default_rds_credentials_invalid_json_raises(sqlite_engine, encrypt_secret):
    """已配置但值非合法 JSON（如密文未被正确解密）：显式报错而非静默空白。"""
    with config_repo.get_engine().begin() as conn:
        from sqlalchemy import text

        conn.execute(text('''
            INSERT INTO ops_config
                (config_name, config_scope, config_type, config_key, config_value,
                 is_encrypt, create_user, description)
            VALUES
                ('t', 'rds', 'json', 'rds_default_u_p', :value, 0, 'tester', '')
        '''), {'value': 'not-a-json{{{'})

    with pytest.raises(ApiError) as exc:
        backup_drill_service._default_rds_credentials()
    assert '不是合法 JSON' in exc.value.user_message


def test_default_rds_credentials_encrypted_roundtrip(sqlite_engine, encrypt_secret):
    """加密存储的默认账号密码：get_by_key 解密后正常预填。"""
    plain = '{"user": "admin", "passwd": "secret"}'
    with config_repo.get_engine().begin() as conn:
        from sqlalchemy import text

        conn.execute(text('''
            INSERT INTO ops_config
                (config_name, config_scope, config_type, config_key, config_value,
                 is_encrypt, create_user, description)
            VALUES
                ('t', 'rds', 'json', 'rds_default_u_p', :value, 1, 'tester', '')
        '''), {'value': encrypt_value(plain)})

    user, passwd = backup_drill_service._default_rds_credentials()
    assert user == 'admin'
    assert passwd == 'secret'


def test_default_rds_credentials_empty_value_falls_back(sqlite_engine, encrypt_secret):
    """配置存在但值为空：静默回落空串（用户手填），不报错。"""
    with config_repo.get_engine().begin() as conn:
        from sqlalchemy import text

        conn.execute(text('''
            INSERT INTO ops_config
                (config_name, config_scope, config_type, config_key, config_value,
                 is_encrypt, create_user, description)
            VALUES
                ('t', 'rds', 'json', 'rds_default_u_p', '', 0, 'tester', '')
        '''))

    assert backup_drill_service._default_rds_credentials() == ('', '')
