"""回测相关 API：跑回测、列策略、列回测历史。"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app import db
from app.api.auth import get_current_user
from app.data import loader
from app.dsl import DSLError, parse
from app.engine import run as run_backtest

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── 跑回测 ──────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    dsl: str = Field(..., description="DSL 文本")
    save_as: Optional[str] = Field(
        default=None,
        description="给一个名字就保存策略 + 回测；不给只跑不存",
    )


@router.post("/backtest")
async def post_backtest(
    req: BacktestRequest = Body(...),
    user: str = Depends(get_current_user),
):
    # 1. 解析 DSL
    try:
        program = parse(req.dsl)
    except DSLError as e:
        raise HTTPException(400, f"DSL 解析失败：{e}")

    if program.strategy is None:
        raise HTTPException(400, "DSL 必须包含 strategy 块")

    # 2. 确保数据可用（自动延伸）
    try:
        end = program.strategy.end
        await asyncio.to_thread(loader.ensure_data, program.strategy.universe, None, end)
    except Exception as e:
        raise HTTPException(500, f"数据准备失败：{e}")

    # 3. 加载长表
    try:
        df = await asyncio.to_thread(
            loader.load_universe, program.strategy.universe, None, None,
        )
    except Exception as e:
        raise HTTPException(500, f"加载行情数据失败：{e}")

    if df.height == 0:
        raise HTTPException(500, f"universe {program.strategy.universe!r} 没有任何数据")

    # 4. 跑引擎（CPU/Polars 计算，放线程池）
    try:
        result = await asyncio.to_thread(run_backtest, program, df)
    except Exception as e:
        logger.exception("backtest failed")
        raise HTTPException(500, f"回测失败：{e}")

    params = {
        "universe": result.universe,
        "top_n": result.top_n,
        "rebalance": result.rebalance,
        "start": result.start,
        "end": result.end,
    }

    backtest_id: int | None = None
    strategy_id: int | None = None

    # 5. 可选保存
    if req.save_as:
        try:
            strategy_id = await asyncio.to_thread(
                db.save_strategy, req.save_as, req.dsl, user,
            )
            backtest_id = await asyncio.to_thread(
                db.save_backtest,
                strategy_id=strategy_id,
                dsl=req.dsl,
                params=json.dumps(params, ensure_ascii=False),
                metrics=json.dumps(result.metrics),
                nav_curve=json.dumps(result.nav_curve),
                duration_ms=result.duration_ms,
                created_by=user,
            )
        except Exception as e:
            logger.exception("save failed")
            raise HTTPException(500, f"保存失败：{e}")

    return {
        "id": backtest_id,
        "strategy_id": strategy_id,
        "saved": req.save_as is not None,
        "metrics": result.metrics,
        "nav_curve": result.nav_curve,
        "benchmark_curve": result.benchmark_curve,
        "benchmark_metrics": result.benchmark_metrics,
        "excess_return": result.excess_return,
        "rebalance_dates": result.rebalance_dates,
        "holdings_history": result.holdings_history,
        "params": params,
        "duration_ms": result.duration_ms,
        "rows_used": result.rows_used,
        "triggered_by": user,
    }


# ─── 校验 DSL（不跑回测，只语法 + 语义检查）────────────────

class ValidateRequest(BaseModel):
    dsl: str


@router.post("/dsl/validate")
def validate_dsl(req: ValidateRequest, _user: str = Depends(get_current_user)):
    try:
        program = parse(req.dsl)
    except DSLError as e:
        return {"ok": False, "error": str(e), "line": e.line, "col": e.col}
    return {
        "ok": True,
        "factors": [f.name for f in program.factors],
        "has_strategy": program.strategy is not None,
        "strategy": (
            {
                "universe": program.strategy.universe,
                "signal": program.strategy.signal,
                "top_n": program.strategy.top_n,
                "rebalance": program.strategy.rebalance,
                "start": program.strategy.start.isoformat() if program.strategy.start else None,
                "end": program.strategy.end.isoformat() if program.strategy.end else None,
            } if program.strategy else None
        ),
    }


# ─── strategies CRUD ────────────────────────────────────────

@router.get("/strategies")
def list_strategies(_user: str = Depends(get_current_user)):
    return db.list_strategies()


@router.get("/strategies/{strategy_id}")
def get_strategy(strategy_id: int, _user: str = Depends(get_current_user)):
    s = db.get_strategy(strategy_id)
    if not s:
        raise HTTPException(404, "strategy not found")
    return s


@router.delete("/strategies/{strategy_id}")
def delete_strategy(strategy_id: int, _user: str = Depends(get_current_user)):
    ok = db.delete_strategy(strategy_id)
    if not ok:
        raise HTTPException(404, "strategy not found")
    return {"deleted": True}


# ─── backtests 列表 + 查看 ─────────────────────────────────

@router.get("/backtests")
def list_backtests(
    limit: int = 50,
    _user: str = Depends(get_current_user),
):
    rows = db.list_backtests(limit=limit)
    # 把 JSON 字段反序列化方便前端
    out = []
    for r in rows:
        out.append({
            **r,
            "params": json.loads(r["params"]) if r.get("params") else {},
            "metrics": json.loads(r["metrics"]) if r.get("metrics") else {},
        })
    return out


@router.get("/backtests/{backtest_id}")
def get_backtest(backtest_id: int, _user: str = Depends(get_current_user)):
    r = db.get_backtest(backtest_id)
    if not r:
        raise HTTPException(404, "backtest not found")
    return {
        **r,
        "params": json.loads(r["params"]) if r.get("params") else {},
        "metrics": json.loads(r["metrics"]) if r.get("metrics") else {},
        "nav_curve": json.loads(r["nav_curve"]) if r.get("nav_curve") else [],
    }


@router.delete("/backtests/{backtest_id}")
def delete_backtest(backtest_id: int, _user: str = Depends(get_current_user)):
    ok = db.delete_backtest(backtest_id)
    if not ok:
        raise HTTPException(404, "backtest not found")
    return {"deleted": True}
