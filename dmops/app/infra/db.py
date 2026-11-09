"""MySQL 访问入口。

复用 CloudDM 的数据库，使用 SQLAlchemy + PyMySQL。
表由 DBA 预先建好，这里不做 migration。
"""

import logging
import threading
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app import config

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_lock = threading.Lock()


def get_engine() -> Engine:
    """懒加载 MySQL Engine，进程内复用连接池。"""
    global _engine
    if _engine is not None:
        return _engine

    with _lock:
        if _engine is None:
            user = quote_plus(config.Database.user)
            password = quote_plus(config.Database.password)
            url = (
                f'mysql+pymysql://{user}:{password}@'
                f'{config.Database.host}:{config.Database.port}/{config.Database.name}'
                f'?charset={config.Database.charset}'
            )
            _engine = create_engine(
                url,
                pool_pre_ping=True,
                pool_size=config.Database.pool_size,
                max_overflow=config.Database.max_overflow,
                pool_recycle=3600,
            )
            logger.info(
                '[dmops] mysql engine ready host=%s port=%s db=%s',
                config.Database.host, config.Database.port, config.Database.name,
            )
    return _engine
