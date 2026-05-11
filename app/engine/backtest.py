"""回测引擎。

输入：Program（含 strategy）+ 长表 df（带 OHLCV）
输出：BacktestResult（净值曲线 + 6 指标 + 调仓日 + 持仓历史 + 耗时）

防前视偏差**第三道防线**（T+0 信号 / T+1 结算）：
- 在 day t：用 signal_t（由 day t 之前的数据计算）决定 day t 结束时的持仓
- day t → day t+1：持有该组合
- day t 的"组合当日收益" = mean(holdings 的 next_ret_t)
  其中 next_ret(s, t) = close(s, t+1) / close(s, t) - 1
- NAV(t+1) = NAV(t) * (1 + 组合当日收益)

简化（V1，与架构 §4.3.3 一致）：
- 等权
- 不扣交易成本
- 忽略涨跌停 / 停牌
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date as date_t
from typing import Any

import polars as pl

from app.dsl import Program, evaluate


@dataclass
class BacktestResult:
    nav_curve: list[tuple[str, float]]                # [(date_iso, nav), ...]
    metrics: dict[str, float]
    benchmark_curve: list[tuple[str, float]]           # 等权持有全 universe 的净值
    benchmark_metrics: dict[str, float]
    excess_return: float                                # 策略累计 - 基准累计
    rebalance_dates: list[str]                         # 实际触发了换仓的日子
    holdings_history: dict[str, list[str]]             # date_iso -> ["cn/600519", ...]
    duration_ms: int
    rows_used: int
    universe: str
    top_n: int
    rebalance: str
    start: str | None
    end: str | None


def _compute_benchmark(df: pl.DataFrame, all_dates: list[date_t]) -> list[tuple[str, float]]:
    """等权基准：每天持有全 universe 等权重，每日再平衡。

    简单做法：每日"组合收益" = 当日所有 symbol 的 next_ret 算术平均。
    NAV = cumprod(1 + 组合收益)。
    """
    if "__next_ret__" not in df.columns:
        df = df.with_columns(
            ((pl.col("close").shift(-1).over(["market", "symbol"]) / pl.col("close")) - 1)
            .alias("__next_ret__")
        )

    daily_mean = (
        df.group_by("date")
        .agg(pl.col("__next_ret__").mean().alias("mean_ret"))
        .sort("date")
    )
    ret_map: dict[date_t, float] = {
        row["date"]: row["mean_ret"]
        for row in daily_mean.iter_rows(named=True)
        if row["mean_ret"] is not None
    }

    nav = 1.0
    curve: list[tuple[str, float]] = []
    for d in all_dates:
        r = ret_map.get(d)
        if r is not None:
            nav = nav * (1.0 + r)
        curve.append((d.isoformat(), nav))
    return curve


def get_rebalance_dates(trading_dates: list[date_t], freq: str) -> list[date_t]:
    """从交易日序列中按 freq 挑出调仓日。"""
    if not trading_dates:
        return []
    if freq == "daily":
        return list(trading_dates)
    if freq == "weekly":
        seen: set[tuple[int, int]] = set()
        out = []
        for d in trading_dates:
            iso = d.isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    if freq == "monthly":
        seen: set[tuple[int, int]] = set()
        out = []
        for d in trading_dates:
            key = (d.year, d.month)
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    raise ValueError(f"unsupported rebalance freq: {freq!r}")


def run(program: Program, df: pl.DataFrame) -> BacktestResult:
    """跑回测。df 是 UNIVERSE_SCHEMA 长表，会先经过 executor。"""
    if program.strategy is None:
        raise ValueError("DSL 必须包含 strategy 块")

    t0 = time.time()
    strategy = program.strategy

    # ── 1. 算因子 + 信号列 ─────────────────────────────────
    if "__signal__" not in df.columns:
        df = evaluate(program, df)

    # ── 2. 算每股 next_ret（明日相对今日的收益）─────────────
    # shift(-1) 在每个 (market, symbol) 组内：取下一行 close
    df = df.with_columns(
        ((pl.col("close").shift(-1).over(["market", "symbol"]) / pl.col("close")) - 1)
        .alias("__next_ret__")
    )

    # ── 3. 决定回测时间窗口 ─────────────────────────────────
    all_dates = df["date"].unique().sort().to_list()
    if strategy.start:
        all_dates = [d for d in all_dates if d >= strategy.start]
    if strategy.end:
        all_dates = [d for d in all_dates if d <= strategy.end]
    if not all_dates:
        raise ValueError("回测区间内没有任何交易日")

    # ── 4. 调仓日 ──────────────────────────────────────────
    rebalance_dates = get_rebalance_dates(all_dates, strategy.rebalance)
    rebalance_set = set(rebalance_dates)

    # ── 5. 构造每日持仓 ────────────────────────────────────
    top_n = strategy.top_n
    current_holdings: list[tuple[str, str]] = []      # [(market, symbol), ...]
    positions_by_date: dict[date_t, list[tuple[str, str]]] = {}
    holdings_history: dict[str, list[str]] = {}

    for d in all_dates:
        if d in rebalance_set:
            day_df = (
                df.filter(pl.col("date") == d)
                .filter(pl.col("__signal__").is_not_null())
                .sort("__signal__", descending=True)
                .head(top_n)
            )
            if day_df.height > 0:
                current_holdings = list(zip(
                    day_df["market"].to_list(),
                    day_df["symbol"].to_list(),
                ))
                holdings_history[d.isoformat()] = [
                    f"{m}/{s}" for m, s in current_holdings
                ]
        positions_by_date[d] = current_holdings

    # ── 6. 把"每日持仓"展开成长表，join next_ret ────────────
    hold_rows: list[dict[str, Any]] = []
    for d, holdings in positions_by_date.items():
        for m, s in holdings:
            hold_rows.append({"date": d, "market": m, "symbol": s})

    if hold_rows:
        holdings_df = pl.DataFrame(
            hold_rows,
            schema={"date": pl.Date, "market": pl.Utf8, "symbol": pl.Utf8},
        )
        joined = holdings_df.join(
            df.select(["date", "market", "symbol", "__next_ret__"]),
            on=["date", "market", "symbol"], how="left",
        )
        port_returns = (
            joined.group_by("date")
            .agg(pl.col("__next_ret__").mean().alias("port_ret"))
            .sort("date")
        )
        port_ret_map: dict[date_t, float] = {
            row["date"]: row["port_ret"]
            for row in port_returns.iter_rows(named=True)
            if row["port_ret"] is not None
        }
    else:
        port_ret_map = {}

    # ── 7. 滚 NAV ──────────────────────────────────────────
    nav = 1.0
    nav_curve: list[tuple[str, float]] = []
    for d in all_dates:
        pr = port_ret_map.get(d)
        if pr is not None:
            nav = nav * (1.0 + pr)
        nav_curve.append((d.isoformat(), nav))

    # ── 8. 指标 + benchmark ────────────────────────────────
    from app.engine.metrics import compute_metrics
    metrics = compute_metrics(nav_curve)

    # benchmark：等权持有全 universe
    bench_df = df.filter(
        (pl.col("date") >= all_dates[0]) & (pl.col("date") <= all_dates[-1])
    )
    benchmark_curve = _compute_benchmark(bench_df, all_dates)
    benchmark_metrics = compute_metrics(benchmark_curve)

    excess_return = metrics["cum_return"] - benchmark_metrics["cum_return"]

    duration_ms = int((time.time() - t0) * 1000)

    return BacktestResult(
        nav_curve=nav_curve,
        metrics=metrics,
        benchmark_curve=benchmark_curve,
        benchmark_metrics=benchmark_metrics,
        excess_return=excess_return,
        rebalance_dates=[d.isoformat() for d in rebalance_dates],
        holdings_history=holdings_history,
        duration_ms=duration_ms,
        rows_used=df.height,
        universe=strategy.universe,
        top_n=top_n,
        rebalance=strategy.rebalance,
        start=strategy.start.isoformat() if strategy.start else None,
        end=strategy.end.isoformat() if strategy.end else None,
    )
