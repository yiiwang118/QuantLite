"""数据相关 API。"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import db, scheduler as sched
from app.api.auth import get_current_user
from app.config import settings
from app.data import (
    MARKETS,
    MARKET_LABELS,
    MARKET_CURRENCIES,
    NAMED_UNIVERSES,
)
from app.data import loader

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── 概览 ────────────────────────────────────────────────────

@router.get("/overview")
def overview(_user: str = Depends(get_current_user)):
    stats = db.db_stats()
    meta = loader.get_meta()
    cache = loader.cache_overview()  # 这个还是 disk-walk，但单次不慢
    return {
        "meta": meta,
        "db": stats,
        "cache": cache,
        "markets": [
            {
                "code": m,
                "label": MARKET_LABELS[m],
                "currency": MARKET_CURRENCIES[m],
                "cache": cache.get(m, {"files": 0, "size_bytes": 0, "size_mb": 0}),
                "symbols_count": stats["symbols_by_market"].get(m, {}).get("symbols", 0),
                "rows_count": stats["symbols_by_market"].get(m, {}).get("rows", 0),
                "calendar_count": stats["calendar_by_market"].get(m, 0),
                "named_universes": [
                    name for name in NAMED_UNIVERSES if name.startswith(f"{m}:")
                ],
            }
            for m in MARKETS
        ],
    }


@router.get("/markets")
def list_markets(_user: str = Depends(get_current_user)):
    return [
        {
            "code": m,
            "label": MARKET_LABELS[m],
            "currency": MARKET_CURRENCIES[m],
            "named_universes": [
                {"name": name, "size": len(NAMED_UNIVERSES[name])}
                for name in NAMED_UNIVERSES if name.startswith(f"{m}:")
            ],
        }
        for m in MARKETS
    ]


# ─── symbols ─────────────────────────────────────────────────

@router.get("/symbols")
def list_symbols(
    market: Optional[str] = Query(default=None),
    _user: str = Depends(get_current_user),
):
    """纯 DB 查询，O(1) 行/symbol；不读 Parquet。"""
    if market and market not in MARKETS:
        raise HTTPException(400, f"unsupported market: {market!r}")
    rows = db.list_symbols(market=market)
    # 把 cache 列展开成前端期望的字段（rows / min_date / max_date / size_bytes 已在 row 里）
    for r in rows:
        r["cached"] = (r.get("rows") or 0) > 0
    return rows


@router.get("/symbols/{market}/{symbol}/sparkline")
def symbol_sparkline(
    market: str, symbol: str,
    days: int = Query(default=30, ge=1, le=200),
    _user: str = Depends(get_current_user),
):
    """单个 sparkline。一般批量用 /sparklines。"""
    if market not in MARKETS:
        raise HTTPException(400, f"unsupported market: {market!r}")
    return {"market": market, "symbol": symbol, "closes": loader.load_sparkline(market, symbol, days)}


@router.get("/sparklines")
def batch_sparklines(
    market: Optional[str] = Query(default=None),
    days: int = Query(default=30, ge=1, le=200),
    _user: str = Depends(get_current_user),
):
    """批量返回所有 cached symbol 的 sparkline。单次请求干掉 N 个 RTT。"""
    if market and market not in MARKETS:
        raise HTTPException(400, f"unsupported market: {market!r}")
    rows = db.list_symbols(market=market)
    out = []
    for r in rows:
        if not (r.get("rows") or 0):
            continue
        closes = loader.load_sparkline(r["market"], r["symbol"], days)
        out.append({"market": r["market"], "symbol": r["symbol"], "closes": closes})
    return out


@router.get("/symbols/{market}/{symbol}")
def symbol_detail(
    market: str,
    symbol: str,
    start: Optional[date] = Query(default=None),
    end: Optional[date] = Query(default=None),
    limit: int = Query(default=800, ge=1, le=10000),
    _user: str = Depends(get_current_user),
):
    if market not in MARKETS:
        raise HTTPException(400, f"unsupported market: {market!r}")

    meta = db.get_symbol(market, symbol)
    df = loader.load_symbol(market, symbol)

    if df.height > 0:
        if start:
            df = df.filter(df["date"] >= start)
        if end:
            df = df.filter(df["date"] <= end)
        df = df.tail(limit)

    candles = []
    for row in df.iter_rows(named=True):
        candles.append({
            "date": row["date"].isoformat(),
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
            "amount": row["amount"],
        })

    return {
        "market": market,
        "symbol": symbol,
        "meta": meta,
        "stats": {
            "cached": (meta.get("rows") or 0) > 0 if meta else False,
            "rows": (meta or {}).get("rows") or 0,
            "min_date": (meta or {}).get("min_date"),
            "max_date": (meta or {}).get("max_date"),
            "size_bytes": (meta or {}).get("size_bytes") or 0,
        },
        "candles": candles,
    }


# ─── 拉数据 ──────────────────────────────────────────────────

class FetchRequest(BaseModel):
    universe: Optional[str] = Field(default=None)
    symbols: Optional[list[dict]] = Field(default=None)
    end_date: Optional[date] = None


@router.post("/data/fetch")
async def fetch_data(
    req: FetchRequest = Body(...),
    user: str = Depends(get_current_user),
):
    if req.universe and req.symbols:
        raise HTTPException(400, "universe 和 symbols 二选一")
    if req.universe:
        items = req.universe
    elif req.symbols:
        items = [(s["market"], s["symbol"]) for s in req.symbols]
    else:
        raise HTTPException(400, "需要 universe 或 symbols")

    results = await asyncio.to_thread(loader.ensure_data, items, None, req.end_date)
    summary = {
        "ok": sum(1 for r in results if r["status"] in ("updated", "up_to_date", "empty", "no_new_rows")),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "rows_added": sum(r.get("rows_added", 0) for r in results),
    }
    return {"triggered_by": user, "summary": summary, "results": results}


# ─── 交易日历 ────────────────────────────────────────────────

@router.get("/calendar/{market}")
def get_calendar(
    market: str,
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    _user: str = Depends(get_current_user),
):
    if market not in MARKETS:
        raise HTTPException(400, f"unsupported market: {market!r}")
    dates = db.list_calendar(market, start=start, end=end)
    return {"market": market, "count": len(dates), "dates": dates}


@router.post("/calendar/{market}/refresh")
async def refresh_calendar(
    market: str,
    user: str = Depends(get_current_user),
):
    if market not in MARKETS:
        raise HTTPException(400, f"unsupported market: {market!r}")
    n = await asyncio.to_thread(loader.refresh_calendar, market)
    return {"market": market, "added_or_kept": n, "triggered_by": user}


# ─── 当前用户 ────────────────────────────────────────────────

@router.get("/me")
def me(user: str = Depends(get_current_user)):
    return {"username": user}


# ─── 定时任务 ────────────────────────────────────────────────

@router.get("/schedule")
def schedule_status(_user: str = Depends(get_current_user)):
    """查看定时拉取的下次时间 + 最近一次结果。"""
    return {
        "enabled": settings.schedule_enabled,
        "tz": settings.schedule_tz,
        "jobs": sched.get_jobs_info(),
    }


@router.post("/schedule/trigger/{universe:path}")
def schedule_trigger(
    universe: str,
    user: str = Depends(get_current_user),
):
    """手动触发一次定时任务（用于测试）。"""
    try:
        result = sched.trigger_now(universe)
        return {"triggered_by": user, **result}
    except Exception as e:
        raise HTTPException(500, f"trigger failed: {e}")
