"""数据 loader：fetch_and_cache、ensure_data、load_universe、refresh_*。

并发安全：per-symbol FileLock + Parquet 原子写。
"""
from __future__ import annotations

import json
import logging
import os
import time as _time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import polars as pl
from filelock import FileLock

from app import db
from app.config import settings
from app.data import (
    MARKETS,
    NAMED_UNIVERSES,
    PARQUET_SCHEMA_VERSION,
    UNIVERSE_COLUMNS,
    UNIVERSE_SCHEMA,
    get_universe,
)
from app.data import sources

logger = logging.getLogger(__name__)


# ─── 路径辅助 ────────────────────────────────────────────────

def _data_dir() -> Path:
    return settings.data_cache_dir


def _meta_path() -> Path:
    return _data_dir() / "_meta.json"


def _lock_dir() -> Path:
    return _data_dir() / ".lock"


def _market_dir(market: str) -> Path:
    return _data_dir() / "daily" / market


def _parquet_path(market: str, symbol: str) -> Path:
    return _market_dir(market) / f"{symbol}.parquet"


def _lock_path(market: str, symbol: str) -> Path:
    return _lock_dir() / f"{market}_{symbol}.lock"


# ─── _meta.json ─────────────────────────────────────────────

def init_storage() -> dict:
    """初始化目录骨架 + meta + DB + 重建 cache stats。幂等。"""
    db.init_db()
    _data_dir().mkdir(parents=True, exist_ok=True)
    _lock_dir().mkdir(parents=True, exist_ok=True)
    for m in MARKETS:
        _market_dir(m).mkdir(parents=True, exist_ok=True)

    if _meta_path().exists():
        meta = json.loads(_meta_path().read_text())
        if meta.get("schema_version") != PARQUET_SCHEMA_VERSION:
            raise RuntimeError(
                f"Parquet schema 版本不匹配（缓存={meta.get('schema_version')}, "
                f"代码={PARQUET_SCHEMA_VERSION}），请删除 {_data_dir()} 后重新初始化。"
            )
    else:
        meta = {
            "schema_version": PARQUET_SCHEMA_VERSION,
            "initial_start_date": settings.initial_start_date.isoformat(),
            "compression": "zstd",
            "markets": list(MARKETS),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _meta_path().write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    # 重建 cache stats（DB 升级到 v2 后，旧记录的 rows/min/max/size 都是 0/NULL，需要重扫）
    resync_cache_stats()
    return meta


def get_meta() -> dict:
    if not _meta_path().exists():
        raise RuntimeError("storage not initialized; call init_storage() first")
    return json.loads(_meta_path().read_text())


# ─── 重建 cache stats ────────────────────────────────────────

def resync_cache_stats() -> int:
    """扫所有 Parquet 文件，把 rows/min_date/max_date/size_bytes 同步到 symbols 表。"""
    n = 0
    for m in MARKETS:
        d = _market_dir(m)
        if not d.exists():
            continue
        for path in d.glob("*.parquet"):
            symbol = path.stem
            try:
                df = pl.read_parquet(path, columns=["date"])
                rows = df.height
                min_d = df["date"].min().isoformat() if rows else None
                max_d = df["date"].max().isoformat() if rows else None
                db.update_symbol_stats(
                    m, symbol, rows=rows, min_date=min_d,
                    max_date=max_d, size_bytes=path.stat().st_size,
                )
                n += 1
            except Exception as e:
                logger.warning(f"resync_cache_stats: {m}/{symbol} failed: {e}")
    if n:
        logger.info(f"resync_cache_stats: synced {n} symbol(s)")
    return n


# ─── 单只股票拉取 ────────────────────────────────────────────

def fetch_and_cache(
    market: str,
    symbol: str,
    end_date: date | None = None,
    force: bool = False,
) -> dict:
    """拉一只股票的日频数据，增量更新；多进程安全。"""
    if market not in MARKETS:
        raise ValueError(f"unsupported market: {market!r}")

    end_date = end_date or date.today()
    path = _parquet_path(market, symbol)
    lock_path = _lock_path(market, symbol)
    _market_dir(market).mkdir(parents=True, exist_ok=True)
    _lock_dir().mkdir(parents=True, exist_ok=True)

    with FileLock(str(lock_path), timeout=120):
        df_old = None
        new_start = settings.initial_start_date
        if path.exists() and not force:
            df_old = pl.read_parquet(path)
            if df_old.height > 0:
                max_existing = df_old["date"].max()
                if max_existing >= end_date:
                    return _stats_result(market, symbol, 0, df_old, path, "up_to_date")
                new_start = max_existing + timedelta(days=1)

        src = sources.get(market)
        df_new = src.fetch_daily(symbol, new_start, end_date)
        if df_new.height == 0:
            return _stats_result(market, symbol, 0, df_old, path, "empty")

        df_new = (
            df_new.with_columns(
                pl.lit(market).alias("market"),
                pl.lit(symbol).alias("symbol"),
            )
            .select(list(UNIVERSE_COLUMNS))
            .with_columns(*[pl.col(c).cast(t) for c, t in UNIVERSE_SCHEMA.items()])
        )

        if df_old is None or df_old.height == 0:
            df = df_new
        else:
            df = (
                pl.concat([df_old, df_new])
                .unique(subset=["date"], keep="last")
                .sort("date")
            )

        tmp = path.with_suffix(".parquet.tmp")
        df.write_parquet(tmp, compression="zstd")
        os.replace(tmp, path)

        rows_added = df.height - (df_old.height if df_old is not None else 0)

    # 写元信息 + 缓存统计
    info = sources.get(market).fetch_symbol_info(symbol) or {}
    db.upsert_symbol(
        market=market, symbol=symbol,
        name=info.get("name", symbol),
        list_date=info.get("list_date"),
        status=info.get("status", "active"),
        last_fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        rows=df.height,
        min_date=df["date"].min().isoformat() if df.height else None,
        max_date=df["date"].max().isoformat() if df.height else None,
        size_bytes=path.stat().st_size,
    )
    return _stats_result(
        market, symbol, rows_added, df, path,
        "updated" if rows_added else "no_new_rows",
    )


def _stats_result(market, symbol, rows_added, df, path, status):
    """统一格式化 fetch_and_cache 结果。df 可以是 polars df 或 None。"""
    if df is None or df.height == 0:
        return {
            "market": market, "symbol": symbol,
            "rows_added": rows_added, "total_rows": 0,
            "max_date": None, "status": status,
        }
    return {
        "market": market, "symbol": symbol,
        "rows_added": rows_added, "total_rows": df.height,
        "max_date": df["date"].max().isoformat(),
        "status": status,
    }


# ─── 批量保证 ────────────────────────────────────────────────

def ensure_data(
    universe: Iterable[tuple[str, str]] | str,
    start: date | None = None,
    end: date | None = None,
) -> list[dict]:
    if isinstance(universe, str):
        items = get_universe(universe)
    else:
        items = list(universe)

    end = end or date.today()
    results = []
    for i, (market, symbol) in enumerate(items):
        if i > 0:
            _time.sleep(0.4)
        try:
            results.append(fetch_and_cache(market, symbol, end_date=end))
        except Exception as e:
            logger.exception(f"fetch_and_cache({market}, {symbol}) failed")
            results.append({
                "market": market, "symbol": symbol,
                "status": "error", "error": str(e),
                "rows_added": 0, "total_rows": 0, "max_date": None,
            })
    return results


# ─── 读 ───────────────────────────────────────────────────────

def load_symbol(
    market: str,
    symbol: str,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    path = _parquet_path(market, symbol)
    if not path.exists():
        if columns:
            schema = {c: UNIVERSE_SCHEMA[c] for c in columns if c in UNIVERSE_SCHEMA}
            return pl.DataFrame(schema=schema)
        return pl.DataFrame(schema=UNIVERSE_SCHEMA)
    if columns:
        return pl.read_parquet(path, columns=columns)
    return pl.read_parquet(path)


def load_universe(
    universe: Iterable[tuple[str, str]] | str,
    start: date | None = None,
    end: date | None = None,
) -> pl.DataFrame:
    if isinstance(universe, str):
        items = get_universe(universe)
    else:
        items = list(universe)

    frames = []
    for market, symbol in items:
        df = load_symbol(market, symbol)
        if df.height > 0:
            frames.append(df)
    if not frames:
        return pl.DataFrame(schema=UNIVERSE_SCHEMA)

    df = pl.concat(frames, how="vertical_relaxed")
    if start:
        df = df.filter(pl.col("date") >= start)
    if end:
        df = df.filter(pl.col("date") <= end)
    return df.sort(["market", "symbol", "date"])


# ─── refresh helpers ────────────────────────────────────────

def refresh_calendar(market: str, start: date | None = None, end: date | None = None) -> int:
    start = start or settings.initial_start_date
    end = end or date.today()
    src = sources.get(market)
    dates = src.fetch_calendar(start, end)
    iso = [d.isoformat() for d in dates]
    db.upsert_calendar(market, iso)
    return len(iso)


def refresh_symbols(market: str, universe: Iterable[str] | None = None) -> int:
    if universe is None:
        universe = NAMED_UNIVERSES.get(f"{market}:sample", ())
    src = sources.get(market)
    n = 0
    for symbol in universe:
        info = src.fetch_symbol_info(symbol)
        if info:
            db.upsert_symbol(
                market=market, symbol=symbol,
                name=info["name"],
                list_date=info.get("list_date"),
                status=info.get("status", "active"),
            )
            n += 1
    return n


# ─── 状态查询（前端 sparkline 用）────────────────────────────

def load_sparkline(market: str, symbol: str, days: int = 30) -> list[float]:
    """读最近 N 天的 close 价格，用于行内 sparkline。"""
    path = _parquet_path(market, symbol)
    if not path.exists():
        return []
    df = pl.read_parquet(path, columns=["date", "close"]).sort("date").tail(days)
    return df["close"].to_list()


def cache_overview() -> dict:
    out = {}
    for m in MARKETS:
        d = _market_dir(m)
        files = sorted(d.glob("*.parquet")) if d.exists() else []
        size = sum(f.stat().st_size for f in files)
        out[m] = {
            "files": len(files),
            "size_bytes": size,
            "size_mb": round(size / 1024 / 1024, 3),
        }
    return out
