"""CloudDM 元数据表访问（同库直读，dmops/AGENTS.md 例外场景）。

例外登记（2026-11-05 用户确认，2026-11-06 扩围）：备份恢复演练"注册数据源"功能
读取 dm_sys_cluster / dm_sys_env（弹窗下拉选项）与 dm_ds（按 host 查重复注册）；
只读 SELECT，不写。
"""

from sqlalchemy import text

from app.infra.db import get_engine


def list_clusters() -> list[dict]:
    """CloudDM 集群清单（id + 描述名），注册数据源弹窗选项。"""
    with get_engine().connect() as conn:
        rows = conn.execute(
            text('SELECT id, cluster_desc FROM dm_sys_cluster ORDER BY id')
        ).mappings().all()
    return [dict(row) for row in rows]


def list_envs() -> list[dict]:
    """CloudDM 环境清单（id + 环境名），注册数据源弹窗选项。"""
    with get_engine().connect() as conn:
        rows = conn.execute(
            text('SELECT id, env_name FROM dm_sys_env ORDER BY id')
        ).mappings().all()
    return [dict(row) for row in rows]


def find_alive_ds_by_host(host: str, port: str = '') -> dict | None:
    """按连接地址查未删除的数据源（防重复注册）。

    console 落库的 dm_ds.host 形态是 "address:port"（如 rm-xxx.rwlb...:3306）；
    调用方传 host + port 组成完整键等值匹配。port 缺省时退化为前缀匹配
    （host LIKE 'address%'）兜底历史口径——等值优先，无等值再取前缀最小 id。
    life_cycle_state 排除 DELETED/DELETING。
    """
    from sqlalchemy import text

    from app.infra.db import get_engine

    full_key = f'{host}:{port}' if port else host
    with get_engine().connect() as conn:
        row = conn.execute(
            text('''
                SELECT id, host, instance_desc
                FROM dm_ds
                WHERE host = :full_key
                  AND life_cycle_state NOT IN ('DELETED', 'DELETING')
                ORDER BY id
                LIMIT 1
            '''),
            {'full_key': full_key},
        ).mappings().first()
        if row is None and port:
            # 前缀兜底：库里可能存过不带端口的形态。
            row = conn.execute(
                text('''
                    SELECT id, host, instance_desc
                    FROM dm_ds
                    WHERE host = :host_only
                      AND life_cycle_state NOT IN ('DELETED', 'DELETING')
                    ORDER BY id
                    LIMIT 1
                '''),
                {'host_only': host},
            ).mappings().first()
    return dict(row) if row else None
