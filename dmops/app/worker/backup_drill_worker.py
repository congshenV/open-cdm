"""备份恢复演练 worker 主循环。

线程在 create_app() 中随进程启动（gunicorn -w 1 单进程），循环逻辑：
- 找一条可处理的记录：优先心跳超时的 cloning（断点续跑），其次 pending。
- pending 先抢占（条件更新 pending→cloning），抢不到说明被取消/被别的逻辑动过，跳过。
- 单条记录的克隆提交与轮询是同步长操作（最长克隆超时窗），期间不扫描其他记录，
  全局并发=1 的约束由这个串行天然保证。
"""

import logging
import threading
import traceback

from app import config
from app.infra import backup_drill_repository as drill_repo
from app.infra.db import get_engine
from app.service import backup_drill_service

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop_event = threading.Event()


def start() -> None:
    """启动 worker 线程（幂等，重复调用不叠加线程）。"""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_run_loop, name='dmops-drill-worker', daemon=True)
    _thread.start()
    logger.info('[dmops] drill worker started interval=%ss', config.Drill.scan_interval_sec)


def stop() -> None:
    """通知 worker 停止（优雅退出，进程关闭时用；不中断进行中的克隆轮询）。"""
    _stop_event.set()


def _run_loop() -> None:
    while not _stop_event.is_set():
        try:
            _tick()
        except Exception as error:
            # 扫描层异常不能带死线程；单条记录的处理异常在 _process 内部兜底。
            logger.error(
                '[dmops] drill worker tick failed: %s\n%s', error, traceback.format_exc(),
            )
        _stop_event.wait(config.Drill.scan_interval_sec)


def _tick() -> None:
    """单轮扫描：处理一条记录（串行，全局并发=1）。"""
    drill = _pick_drill()
    if drill is None:
        return
    _process(drill)


def _pick_drill() -> dict | None:
    """优先接管心跳超时的 cloning，其次抢占最早的 pending。"""
    stale = drill_repo.list_stale_cloning(config.Drill.heartbeat_timeout_sec)
    if stale:
        return stale[0]

    pending = drill_repo.list_pending_jobs(limit=1)
    if not pending:
        return None

    drill = pending[0]
    with get_engine().begin() as conn:
        claimed = drill_repo.claim_pending(conn, drill['id'])
    if not claimed:
        # pending 被并发取消（cancel 与抢占竞争，两者都条件更新，只有一方成功）。
        logger.info('[dmops] drill %s claim failed, likely canceled', drill['id'])
        return None

    # 返回抢占后的状态视图。
    drill = drill_repo.get_drill(drill['id'])
    return drill


def _process(drill: dict) -> None:
    """处理一条 cloning 记录：提交克隆（幂等）+ 轮询到终态。"""
    drill_id = drill['id']
    logger.info(
        '[dmops] drill %s picked up drill_no=%s resume=%s',
        drill_id, drill.get('drill_no'), bool(drill.get('clone_instance_id')),
    )
    try:
        backup_drill_service.run_clone_stage(drill)
    except Exception as error:
        # 编排层的意外异常兜底落 failed，避免记录停在无心跳的 cloning 被反复接管。
        logger.error(
            '[dmops] drill %s clone stage crashed: %s\n%s', drill_id, error, traceback.format_exc(),
        )
        with get_engine().begin() as conn:
            drill_repo.finish_drill(
                conn, drill_id, drill_repo.STATUS_FAILED,
                f'内部错误：{error}',
            )
