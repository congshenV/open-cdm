"""pytest 全局夹具。

单测不连真实 MySQL / 阿里云：repo 层用内存 SQLite 模拟（相同 SQL 方言子集），
adapter/service 层用 monkeypatch 替身。
"""

import os
import sys

import pytest

# dmops 工程以 dmops/ 为运行目录，把 package root 加进 sys.path。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 本地测试环境变量，避免 config 读到真实配置。
os.environ.setdefault('DMOPS_IDENTITY_VERIFY_ENABLED', 'false')


@pytest.fixture()
def sqlite_engine(monkeypatch):
    """用 SQLite 内存库替换 get_engine，并预建 drill 表。

    SQLite 支持 FOR UPDATE 解析但忽略行锁，单线程测试足够；
    这里只验证 SQL 行为与状态机逻辑，不做并发正确性。
    """
    import sqlalchemy

    engine = sqlalchemy.create_engine('sqlite://')
    # SQLite 单次 execute 只吃一条语句，DDL 按分号拆开逐条建。
    with engine.connect() as conn:
        for statement in _SQLITE_DDL.strip().split(';'):
            if statement.strip():
                conn.execute(sqlalchemy.text(statement))
        conn.commit()

    # from-import 绑定的是函数引用，db 模块与各使用方逐个替换。
    from app.infra import backup_drill_repository as drill_repo_module
    from app.infra import cloud_credential_repository as credential_repo_module
    from app.infra import config_repository as config_repo_module
    from app.infra import db as db_module
    from app.service import backup_drill_service as service_module
    from app.worker import backup_drill_worker as worker_module

    for module in (db_module, drill_repo_module, credential_repo_module, config_repo_module,
                   service_module, worker_module):
        monkeypatch.setattr(module, 'get_engine', lambda: engine)
    return engine


# 与 docs/backup-drill-design.md §5 对齐的最小建表（一期字段）。
_SQLITE_DDL = '''
CREATE TABLE ops_backup_drill (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  drill_no           TEXT NOT NULL UNIQUE,
  account_id         INTEGER NOT NULL,
  region             TEXT NOT NULL,
  source_instance_id TEXT NOT NULL,
  source_ds_id       INTEGER,
  backup_id          TEXT NOT NULL,
  backup_start_time  TEXT,
  backup_end_time    TEXT,
  clone_instance_id  TEXT,
  clone_ds_id        INTEGER,
  clone_params       TEXT,
  target_tables      TEXT,
  status             TEXT NOT NULL DEFAULT 'pending',
  error_message      TEXT,
  triggered_by       TEXT NOT NULL,
  clone_started_at   TEXT,
  clone_finished_at  TEXT,
  compare_started_at TEXT,
  compare_finished_at TEXT,
  finished_at        TEXT,
  offline_status     INTEGER NOT NULL DEFAULT 0,
  offline_confirmed_at TEXT,
  offline_confirmed_by TEXT,
  created_at         TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at         TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ops_config (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  config_name  TEXT,
  config_scope TEXT,
  config_type  TEXT,
  config_key   TEXT,
  config_value TEXT,
  is_encrypt   INTEGER DEFAULT 0,
  create_user  TEXT,
  description  TEXT,
  created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at   TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE dm_ds (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  gmt_create       TEXT,
  gmt_modified     TEXT,
  uid              TEXT,
  owner            TEXT,
  data_source_type TEXT,
  host             TEXT,
  instance_desc    TEXT,
  version          TEXT,
  driver           TEXT,
  instance_id      TEXT,
  access_key       TEXT,
  secret_key       TEXT,
  security_type    TEXT,
  life_cycle_state TEXT,
  status           TEXT,
  status_message   TEXT,
  bind_cluster_id  INTEGER,
  ds_env_id        INTEGER
);

CREATE TABLE ops_backup_drill_step (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  drill_id   INTEGER NOT NULL,
  layer      TEXT NOT NULL,
  target     TEXT NOT NULL,
  status     TEXT NOT NULL,
  summary    TEXT,
  detail     TEXT,
  error      TEXT,
  cost_ms    INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ops_backup_drill_diff (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  drill_id     INTEGER NOT NULL,
  step_id      INTEGER NOT NULL,
  layer        TEXT NOT NULL,
  item_type    TEXT NOT NULL,
  target       TEXT NOT NULL,
  attempt_no   INTEGER,
  status       TEXT NOT NULL,
  source_value TEXT,
  clone_value  TEXT,
  note         TEXT,
  created_at   TEXT DEFAULT CURRENT_TIMESTAMP
);
'''
