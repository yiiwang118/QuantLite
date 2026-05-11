"""回测引擎。

输入：Program（含 strategy）+ 长表 df（带 OHLCV）
输出：BacktestResult（净值曲线 + 指标 + 调仓日 + 持仓历史 + 耗时）

防前视偏差**第三道防线**（T+0 信号 / T+1 结算）：
- 在 day t：用 signal_t（由 day t 之前的数据计算）决定 day t 结束时的持仓
- day t → day t+1：持有该组合
- 当日组合收益 = mean(holdings 的 next_ret_t)
  其中 next_ret(s, t) = close(s, t+1) / close(s, t) - 1
- NAV(t+1) = NAV(t) * (1 + 组合收益)

V2 新增：
- long-short：当 strategy.bottom_n > 0，多头 top N + 空头 bottom M，PnL = long_ret - short_ret
- 交易成本：每次 rebalance 按 turnover 扣除 turnover * cost * 2（双边）
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date as date_t
from typing import Any

import polars as pl

from app.dsl import Program, evaluate


@dataclass
class BacktestResult:
    nav_curve: list[tuple[str, float]]
    metrics: dict[str, float]
    benchmark_curve: list[tuple[str, float]]
    benchmark_metrics: dict[str, float]
    excess_return: float
    rebalance_dates: list[str]
    holdings_history: dict[str, list[str]]            # date → ["L:cn/600519", "S:cn/000001", ...]
    duration_ms: int
    rows_used: int
    universe: str
    top_n: int
    bottom_n: int
    rebalance: str
    cost: float
    total_cost: float                                  # 累计扣除的成本（绝对值）
    start: str | None
    end: str | None


def _compute_benchmark(df: pl.DataFrame, all_dates: list[date_t]) -> list[tuple[str, float]]:
    """等权基准：每天持有全 universe 等权重，每日再平衡。"""
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


def _select_holdings(
    df: pl.DataFrame, d: date_t, top_n: int, bottom_n: int,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """返回 (long_holdings, short_holdings)。"""
    day_df = (
        df.filter(pl.col("date") == d)
        .filter(pl.col("__signal__").is_not_null())
        .sort("__signal__", descending=True)
    )
    if day_df.height == 0:
        return [], []
    longs_df = day_df.head(top_n)
    longs = list(zip(longs_df["market"].to_list(), longs_df["symbol"].to_list()))
    shorts: list[tuple[str, str]] = []
    if bottom_n > 0:
        shorts_df = day_df.tail(bottom_n)
        shorts = list(zip(shorts_df["market"].to_list(), shorts_df["symbol"].to_list()))
    return longs, shorts


def _turnover(old: list[tuple[str, str]], new: list[tuple[str, str]]) -> float:
    """单边换手率：从 old 集合到 new 集合，0=完全相同，1=完全不同。

    等权下，turnover_one_way = (新持仓中不在旧持仓的占比 + 旧持仓中不在新持仓的占比) / 2
    简化等价于：1 - |intersection| / max(|old|, |new|)
    """
    if not new:
        return 0.0
    if not old:
        return 1.0  # 首次建仓 = 100%
    old_set = set(old)
    new_set = set(new)
    overlap = len(old_set & new_set)
    union_size = max(len(old_set), len(new_set))
    return 1.0 - overlap / union_size if union_size > 0 else 0.0


def _portfolio_return(
    df_next_ret: pl.DataFrame,
    longs: list[tuple[str, str]],
    shorts: list[tuple[str, str]],
    d: date_t,
) -> float:
    """计算 day d 的组合收益。多头等权 - 空头等权。"""
    long_ret = _equal_weight_return(df_next_ret, longs, d)
    if not shorts:
        return long_ret
    short_ret = _equal_weight_return(df_next_ret, shorts, d)
    # long-short：净收益 = long - short（market-neutral）
    return long_ret - short_ret


def _equal_weight_return(
    df_next_ret: pl.DataFrame,
    holdings: list[tuple[str, str]],
    d: date_t,
) -> float:
    """等权持仓在 day d 的次日收益均值。"""
    if not holdings:
        return 0.0
    keys = pl.DataFrame(
        [{"market": m, "symbol": s} for m, s in holdings],
        schema={"market": pl.Utf8, "symbol": pl.Utf8},
    )
    sub = df_next_ret.filter(pl.col("date") == d).join(
        keys, on=["market", "symbol"], how="inner",
    )
    if sub.height == 0:
        return 0.0
    mean = sub["__next_ret__"].drop_nulls().mean()
    return float(mean) if mean is not None else 0.0


def run(program: Program, df: pl.DataFrame) -> BacktestResult:
    """跑回测。df 是 UNIVERSE_SCHEMA 长表。"""
    if program.strategy is None:
        raise ValueError("DSL 必须包含 strategy 块")

    t0 = time.time()
    strategy = program.strategy
    top_n = strategy.top_n
    bottom_n = strategy.bottom_n
    cost = strategy.cost

    # ── 1. 算因子 + 信号列 ─────────────────────────────────
    if "__signal__" not in df.columns:
        df = evaluate(program, df)

    # ── 2. 算每股 next_ret ──────────────────────────────────
    df = df.with_columns(
        ((pl.col("close").shift(-1).over(["market", "symbol"]) / pl.col("close")) - 1)
        .alias("__next_ret__")
    )
    df_next_ret = df.select(["date", "market", "symbol", "__next_ret__"])

    # ── 3. 时间窗口 ──────────────────────────────────────────
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

    # ── 5. 滚 NAV：边算持仓边算收益边扣成本 ────────────────
    nav = 1.0
    total_cost = 0.0
    longs: list[tuple[str, str]] = []
    shorts: list[tuple[str, str]] = []
    nav_curve: list[tuple[str, float]] = []
    holdings_history: dict[str, list[str]] = {}

    for d in all_dates:
        if d in rebalance_set:
            new_longs, new_shorts = _select_holdings(df, d, top_n, bottom_n)
            if new_longs or new_shorts:
                # turnover 综合：多空两边各算一次
                long_to = _turnover(longs, new_longs)
                short_to = _turnover(shorts, new_shorts) if bottom_n > 0 else 0.0
                avg_to = (long_to + short_to) / 2 if bottom_n > 0 else long_to
                # 双边成本：换手率 × cost × 2（买入 + 卖出）
                cost_drag = avg_to * cost * 2
                if cost_drag > 0:
                    nav *= (1.0 - cost_drag)
                    total_cost += cost_drag
                longs, shorts = new_longs, new_shorts
                history_entry = [f"L:{m}/{s}" for m, s in longs] + \
                                [f"S:{m}/{s}" for m, s in shorts]
                holdings_history[d.isoformat()] = history_entry

        # 当日组合收益
        port_ret = _portfolio_return(df_next_ret, longs, shorts, d)
        nav *= (1.0 + port_ret)
        nav_curve.append((d.isoformat(), nav))

    # ── 6. 指标 + benchmark ────────────────────────────────
    from app.engine.metrics import compute_metrics
    metrics = compute_metrics(nav_curve)

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
        bottom_n=bottom_n,
        rebalance=strategy.rebalance,
        cost=cost,
        total_cost=total_cost,
        start=strategy.start.isoformat() if strategy.start else None,
        end=strategy.end.isoformat() if strategy.end else None,
    )
