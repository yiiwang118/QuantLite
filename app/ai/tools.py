"""Agent 工具定义。

每个工具：
- name / description / input_schema：给 LLM 看
- execute(params, ctx)：实际执行

工具调用时返回**给 LLM 的内容尽量小**（token 贵），但同时记录完整结果到 ctx 里给前端用。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from app import db
from app.data import NAMED_UNIVERSES, MARKETS, MARKET_LABELS
from app.dsl import DSLError, parse as dsl_parse
from app.dsl import whitelist as wl

logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    """每次 agent 调用的状态：记录工具调用 + 完整结果（不返回给 LLM 的部分）。"""
    user: str
    tool_log: list[dict] = field(default_factory=list)
    backtest_result_full: dict | None = None  # 完整 nav_curve 等，给前端展示用
    final_dsl: str | None = None


# ─── 工具：DSL 校验 ─────────────────────────────────────────

def _tool_validate_dsl(params: dict, ctx: AgentContext) -> dict:
    dsl = params.get("dsl", "")
    if not dsl:
        return {"ok": False, "error": "dsl 字段为空"}
    try:
        prog = dsl_parse(dsl)
        ctx.final_dsl = dsl
        return {
            "ok": True,
            "factors": [f.name for f in prog.factors],
            "has_strategy": prog.strategy is not None,
            "strategy": {
                "universe": prog.strategy.universe,
                "signal": prog.strategy.signal,
                "top_n": prog.strategy.top_n,
                "rebalance": prog.strategy.rebalance,
            } if prog.strategy else None,
        }
    except DSLError as e:
        return {"ok": False, "error": str(e), "line": e.line, "col": e.col}


# ─── 工具：跑回测 ──────────────────────────────────────────

def _tool_run_backtest(params: dict, ctx: AgentContext) -> dict:
    """LLM 拿一段 DSL 来跑回测。返回精简摘要给 LLM，完整结果存 ctx。"""
    from app.data import loader
    from app.engine import run as run_engine

    dsl = params.get("dsl", "")
    if not dsl:
        return {"ok": False, "error": "dsl 字段为空"}
    try:
        prog = dsl_parse(dsl)
    except DSLError as e:
        return {"ok": False, "error": f"DSL 解析失败: {e}"}
    if prog.strategy is None:
        return {"ok": False, "error": "DSL 必须包含 strategy 块"}
    try:
        loader.ensure_data(prog.strategy.universe, None, prog.strategy.end)
        df = loader.load_universe(prog.strategy.universe)
        if df.height == 0:
            return {"ok": False, "error": f"universe {prog.strategy.universe!r} 没有任何缓存数据"}
        result = run_engine(prog, df)
    except Exception as e:
        return {"ok": False, "error": f"回测失败: {e}"}

    ctx.final_dsl = dsl
    ctx.backtest_result_full = {
        "dsl": dsl,
        "metrics": result.metrics,
        "benchmark_metrics": result.benchmark_metrics,
        "excess_return": result.excess_return,
        "nav_curve": result.nav_curve,
        "benchmark_curve": result.benchmark_curve,
        "rebalance_dates": result.rebalance_dates,
        "holdings_history": result.holdings_history,
        "duration_ms": result.duration_ms,
        "rows_used": result.rows_used,
        "params": {
            "universe": result.universe,
            "top_n": result.top_n,
            "rebalance": result.rebalance,
            "start": result.start, "end": result.end,
        },
    }
    # 给 LLM 的精简摘要
    m = result.metrics
    bm = result.benchmark_metrics
    return {
        "ok": True,
        "summary": {
            "universe": result.universe,
            "top_n": result.top_n,
            "rebalance": result.rebalance,
            "nav_curve_len": len(result.nav_curve),
            "rebalance_count": len(result.rebalance_dates),
            "duration_ms": result.duration_ms,
        },
        "strategy": {
            "cum_return": round(m["cum_return"], 4),
            "annual_return": round(m["annual_return"], 4),
            "sharpe": round(m["sharpe"], 3),
            "annual_vol": round(m["annual_vol"], 4),
            "max_drawdown": round(m["max_drawdown"], 4),
            "win_rate": round(m["win_rate"], 4),
        },
        "benchmark": {
            "cum_return": round(bm["cum_return"], 4),
            "annual_return": round(bm["annual_return"], 4),
            "sharpe": round(bm["sharpe"], 3),
            "max_drawdown": round(bm["max_drawdown"], 4),
        },
        "excess_return": round(result.excess_return, 4),
    }


# ─── 工具：列出 universe ─────────────────────────────────

def _tool_list_universes(params: dict, ctx: AgentContext) -> dict:
    return {
        "universes": [
            {"name": name, "size": len(symbols),
             "market": name.split(":")[0],
             "market_label": MARKET_LABELS.get(name.split(":")[0], name.split(":")[0])}
            for name, symbols in NAMED_UNIVERSES.items()
        ],
    }


# ─── 工具：列已保存策略 ──────────────────────────────────

def _tool_list_saved_strategies(params: dict, ctx: AgentContext) -> dict:
    rows = db.list_strategies()
    return {
        "strategies": [
            {"id": r["id"], "name": r["name"], "dsl": r["dsl"],
             "created_by": r["created_by"], "updated_at": r["updated_at"]}
            for r in rows[:20]  # 最多 20 个
        ],
        "total": len(rows),
    }


# ─── 工具注册表 ──────────────────────────────────────────

@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    execute: Callable[[dict, AgentContext], dict]


TOOLS: list[Tool] = [
    Tool(
        name="validate_dsl",
        description=(
            "校验一段 DSL 文本是否合法。返回 factors 列表 + strategy 概要 + 错误（如有）。"
            "在生成 DSL 后必先调用一次确保语法对，再考虑是否运行回测。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "dsl": {"type": "string", "description": "完整的 DSL 文本（包括 factor 定义和 strategy 块）"},
            },
            "required": ["dsl"],
        },
        execute=_tool_validate_dsl,
    ),
    Tool(
        name="run_backtest",
        description=(
            "用 DSL 跑回测，返回 6 个指标 + 与等权基准的对照。这是把策略变成数字的关键工具。"
            "当用户说『跑一下』『回测』『看效果』时调用。"
            "调用前最好先 validate_dsl 确认语法。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "dsl": {"type": "string", "description": "包含 strategy 块的完整 DSL"},
            },
            "required": ["dsl"],
        },
        execute=_tool_run_backtest,
    ),
    Tool(
        name="list_universes",
        description="列出系统当前支持的所有股票池（universe）。",
        input_schema={"type": "object", "properties": {}, "required": []},
        execute=_tool_list_universes,
    ),
    Tool(
        name="list_saved_strategies",
        description="列出已保存的命名策略，供加载或参考。",
        input_schema={"type": "object", "properties": {}, "required": []},
        execute=_tool_list_saved_strategies,
    ),
]

_TOOL_BY_NAME = {t.name: t for t in TOOLS}


def execute_tool(name: str, params: dict, ctx: AgentContext) -> dict:
    tool = _TOOL_BY_NAME.get(name)
    if tool is None:
        return {"error": f"未知工具: {name}"}
    try:
        result = tool.execute(params, ctx)
        return result
    except Exception as e:
        logger.exception(f"tool {name} failed")
        return {"error": f"工具 {name} 执行失败: {e}"}


# ─── 工具 schema 给两家 LLM ──────────────────────────────

def tools_for_anthropic() -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in TOOLS
    ]


def tools_for_openai() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in TOOLS
    ]
