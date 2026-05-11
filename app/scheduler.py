"""进程内定时拉取。

每个 uvicorn worker 都会起一个 BackgroundScheduler；
靠 FileLock 跨进程去重，cron 触发时只有一个 worker 真正干活。
执行结果写到 data_cache/_schedule_runs.json，所有 worker 共享。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from filelock import FileLock, Timeout

from app.config import settings
from app.data import loader

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def _runs_path() -> Path:
    return settings.data_cache_dir / "_schedule_runs.json"


def _save_run(universe: str, info: dict[str, Any]) -> None:
    p = _runs_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(p) + ".lock", timeout=10):
        data: dict = {}
        if p.exists():
            try:
                data = json.loads(p.read_text())
            except Exception:
                data = {}
        history = data.setdefault(universe, {"history": []})
        history["last"] = info
        history["history"].append(info)
        history["history"] = history["history"][-20:]  # 只留最近 20 次
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def load_runs() -> dict:
    p = _runs_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _scheduled_fetch(universe: str) -> None:
    """定时任务执行体。FileLock 保证多 worker 中只有一个真正干活。"""
    lock_name = f"quant-lite-sched-{universe.replace(':', '_')}.lock"
    lock_path = settings.data_cache_dir / ".lock" / lock_name
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with FileLock(str(lock_path), timeout=0):
            start = time.time()
            start_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
            logger.info(f"[scheduler] start {universe}")
            try:
                results = loader.ensure_data(universe)
                ok = sum(1 for r in results if r.get("status") in
                         ("updated", "up_to_date", "no_new_rows", "empty"))
                errors = sum(1 for r in results if r.get("status") == "error")
                rows_added = sum(r.get("rows_added", 0) for r in results)
                info = {
                    "ts": start_iso,
                    "duration_s": round(time.time() - start, 2),
                    "ok": ok,
                    "errors": errors,
                    "rows_added": rows_added,
                    "status": "success" if errors == 0 else "partial",
                }
            except Exception as e:
                logger.exception(f"[scheduler] {universe} crashed")
                info = {
                    "ts": start_iso,
                    "duration_s": round(time.time() - start, 2),
                    "status": "error",
                    "error": str(e),
                    "ok": 0, "errors": 0, "rows_added": 0,
                }
            _save_run(universe, info)
            logger.info(f"[scheduler] done {universe}: {info}")
    except Timeout:
        logger.info(f"[scheduler] {universe} skip (another worker is running it)")


def start_scheduler() -> None:
    global _scheduler
    if not settings.schedule_enabled:
        logger.info("Scheduler disabled (schedule_enabled=False)")
        return
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(timezone=settings.schedule_tz)

    # CN：mon-fri 18:00
    for uni in settings.schedule_cn_universes.split(","):
        uni = uni.strip()
        if not uni:
            continue
        _scheduler.add_job(
            _scheduled_fetch,
            CronTrigger(day_of_week="mon-fri",
                        hour=settings.schedule_cn_hour,
                        minute=settings.schedule_cn_minute,
                        timezone=settings.schedule_tz),
            kwargs={"universe": uni},
            id=f"fetch::{uni}",
            name=f"拉取 {uni}",
            misfire_grace_time=3600,
            coalesce=True,
            replace_existing=True,
        )

    # US：tue-sat 06:00（美东周五收盘 = 北京周六上午）
    for uni in settings.schedule_us_universes.split(","):
        uni = uni.strip()
        if not uni:
            continue
        _scheduler.add_job(
            _scheduled_fetch,
            CronTrigger(day_of_week="tue-sat",
                        hour=settings.schedule_us_hour,
                        minute=settings.schedule_us_minute,
                        timezone=settings.schedule_tz),
            kwargs={"universe": uni},
            id=f"fetch::{uni}",
            name=f"拉取 {uni}",
            misfire_grace_time=3600,
            coalesce=True,
            replace_existing=True,
        )

    _scheduler.start()
    jobs_summary = [(j.id, str(j.next_run_time)) for j in _scheduler.get_jobs()]
    logger.info(f"Scheduler started: {jobs_summary}")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")


def get_jobs_info() -> list[dict]:
    """返回任务列表 + 下次/上次运行时间。"""
    runs = load_runs()
    if _scheduler is None or not _scheduler.running:
        # 即使本 worker 没起 scheduler，也能从磁盘 runs 文件展示历史
        out = []
        for uni, data in runs.items():
            out.append({
                "id": f"fetch::{uni}",
                "universe": uni,
                "next_run": None,
                "last_run": data.get("last"),
            })
        return out

    out = []
    for j in _scheduler.get_jobs():
        universe = j.kwargs.get("universe") if isinstance(j.kwargs, dict) else None
        out.append({
            "id": j.id,
            "name": j.name,
            "universe": universe,
            "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
            "last_run": (runs.get(universe, {}) or {}).get("last") if universe else None,
        })
    return out


def trigger_now(universe: str) -> dict:
    """手动触发一次定时任务（不等结果，立刻返回）。"""
    if _scheduler is None:
        raise RuntimeError("scheduler not running in this worker")
    _scheduler.add_job(
        _scheduled_fetch, kwargs={"universe": universe},
        id=f"manual::{universe}::{int(time.time())}",
    )
    return {"queued": universe}
