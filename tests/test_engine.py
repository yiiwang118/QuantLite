"""回测引擎测试。

覆盖：
- 调仓日生成（weekly / monthly / daily）
- 等权基线（持有全 universe）→ NAV 应该跟 universe 均值一致
- T+1 结算（信号日不在当日实现收益）
- rank 选股能选出 top N
- 指标计算正确性（已知 NAV 曲线 → 已知指标）
- 边界（空信号、单股 universe、所有调仓日都没有有效信号）
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import polars as pl
import pytest

from app.dsl import parse
from app.engine import compute_metrics, run
from app.engine.backtest import get_rebalance_dates


# ─── 测试夹具 ───────────────────────────────────────────────

def make_df(closes_by_symbol: dict[str, list[float]], market: str = "cn") -> pl.DataFrame:
    """{symbol: [close per day]} → UNIVERSE_SCHEMA 长表。

    使用真实的工作日序列（跳过周末），避免 weekly 调仓在测试里把每天都当成新周。
    """
    n_days = len(next(iter(closes_by_symbol.values())))
    # 从 2024-01-01（周一）开始连续 n_days 个工作日
    dates: list[date] = []
    d = date(2024, 1, 1)
    while len(dates) < n_days:
        if d.weekday() < 5:  # 周一到周五
            dates.append(d)
        d = d + timedelta(days=1)

    rows = []
    for sym, closes in closes_by_symbol.items():
        for i, c in enumerate(closes):
            rows.append({
                "date": dates[i], "market": market, "symbol": sym,
                "open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                "volume": 100, "amount": c * 100.0,
            })
    return pl.DataFrame(
        rows,
        schema={
            "date": pl.Date, "market": pl.Utf8, "symbol": pl.Utf8,
            "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
            "close": pl.Float64, "volume": pl.Int64, "amount": pl.Float64,
        },
    ).sort(["market", "symbol", "date"])


# ─── 调仓日 ─────────────────────────────────────────────────

def test_rebalance_daily():
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(5)]
    assert get_rebalance_dates(dates, "daily") == dates


def test_rebalance_weekly():
    # 2024-01-01 周一，每隔一天采样
    dates = [
        date(2024, 1, 1),  # week 1
        date(2024, 1, 3),
        date(2024, 1, 5),
        date(2024, 1, 8),  # week 2
        date(2024, 1, 10),
        date(2024, 1, 15),  # week 3
    ]
    out = get_rebalance_dates(dates, "weekly")
    assert out == [date(2024, 1, 1), date(2024, 1, 8), date(2024, 1, 15)]


def test_rebalance_monthly():
    dates = [
        date(2024, 1, 1), date(2024, 1, 15),
        date(2024, 2, 1), date(2024, 2, 20),
        date(2024, 3, 1),
    ]
    out = get_rebalance_dates(dates, "monthly")
    assert out == [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]


# ─── 等权基线（核心健全性测试）────────────────────────────

def test_equal_weight_baseline_matches_universe_mean():
    """选 top 2（=universe 全持有，等权）应该跟全 universe 等权基准一致。"""
    # 2 只股票，每日不同收益
    p = parse(
        "factor s = close\n"
        "strategy {\n"
        "    universe:  cn:sample\n"
        "    signal:    s\n"
        "    select:    top 2\n"
        "    rebalance: daily\n"
        "}\n"
    )
    # A: 100, 110, 121, 133.1   (+10% 每日)
    # B: 100, 105, 110.25, 115.7625  (+5% 每日)
    df = make_df({
        "A": [100.0, 110.0, 121.0, 133.1],
        "B": [100.0, 105.0, 110.25, 115.7625],
    })
    result = run(p, df)

    # 等权组合日收益 = (10% + 5%) / 2 = 7.5%
    # 持有 3 个交易日（最后一天没有 next_ret）
    # NAV: 1.0 * 1.075^3 = 1.2423...
    nav_end = result.nav_curve[-1][1]
    expected = 1.075 ** 3
    assert abs(nav_end - expected) < 1e-6


def test_top1_picks_higher_signal():
    """top 1 + signal=close：应该总是持有 close 大的那只。"""
    p = parse(
        "factor s = close\n"
        "strategy {\n"
        "    universe:  cn:sample\n"
        "    signal:    s\n"
        "    select:    top 1\n"
        "    rebalance: daily\n"
        "}\n"
    )
    # A close 一直更大 → 持有 A，得到 A 的全部收益
    # A: +10% 每日；B: +1% 每日
    df = make_df({
        "A": [100.0, 110.0, 121.0, 133.1],
        "B": [50.0, 50.5, 51.005, 51.515],
    })
    result = run(p, df)
    # NAV 应该 = A 的累计收益 = 1.10^3 (3 个 next_ret 期)
    nav_end = result.nav_curve[-1][1]
    expected = 1.10 ** 3
    assert abs(nav_end - expected) < 1e-6


# ─── T+1 结算 ────────────────────────────────────────────────

def test_t_plus_one_settlement():
    """signal_t 决定 t 末的持仓，收益从 t→t+1 实现；信号日当天不在 NAV 体现。"""
    p = parse(
        "factor s = close\n"
        "strategy {\n"
        "    universe:  cn:sample\n"
        "    signal:    s\n"
        "    select:    top 1\n"
        "    rebalance: daily\n"
        "}\n"
    )
    # A 第一天就高，所以 day 1 调仓后开始持有 A
    df = make_df({"A": [100.0, 110.0], "B": [50.0, 50.0]})  # 2 天
    result = run(p, df)
    # day 1：调仓 → 持有 A。next_ret_1 = 110/100 - 1 = 0.10 → NAV[1] = 1.10
    # day 2：last day，没有 next_ret → NAV[2] = 1.10
    assert len(result.nav_curve) == 2
    assert abs(result.nav_curve[0][1] - 1.10) < 1e-9


# ─── 选股逻辑 ───────────────────────────────────────────────

def test_top_n_holdings_recorded():
    """holdings_history 应该正确记录每个调仓日选了哪几只股票。"""
    p = parse(
        "factor s = close\n"
        "strategy {\n"
        "    universe:  cn:sample\n"
        "    signal:    s\n"
        "    select:    top 2\n"
        "    rebalance: daily\n"
        "}\n"
    )
    df = make_df({
        "A": [100.0, 100.0, 100.0],
        "B": [200.0, 200.0, 200.0],
        "C": [50.0, 50.0, 50.0],
    })
    result = run(p, df)
    # 每天都选 close 最大的 2 只 → B, A
    for d, holdings in result.holdings_history.items():
        assert set(holdings) == {"cn/B", "cn/A"}


def test_no_holdings_when_all_signals_null():
    """全 null 信号 → 不调仓 → NAV 保持 1.0。"""
    p = parse(
        "factor s = delay(close, 100)\n"  # 100 期前的数据，全部 NaN
        "strategy {\n"
        "    universe:  cn:sample\n"
        "    signal:    s\n"
        "    select:    top 1\n"
        "    rebalance: daily\n"
        "}\n"
    )
    df = make_df({"A": [100.0, 101.0, 102.0]})
    result = run(p, df)
    for _, nav in result.nav_curve:
        assert nav == 1.0


# ─── 指标 ──────────────────────────────────────────────────

def test_metrics_basic():
    """已知 NAV 曲线 → 已知指标。"""
    # NAV: 1.0, 1.1, 1.21, 1.331（每日 +10%），4 个点
    curve = [
        ("2024-01-01", 1.0),
        ("2024-01-02", 1.1),
        ("2024-01-03", 1.21),
        ("2024-01-04", 1.331),
    ]
    m = compute_metrics(curve)
    assert abs(m["cum_return"] - 0.331) < 1e-6
    # 4 天，年化 = 1.331 ^ (252/4) - 1（巨大数字，但应该正常计算）
    assert m["annual_return"] > 1.0
    assert abs(m["win_rate"] - 1.0) < 1e-9  # 每天都涨
    assert m["max_drawdown"] == 0.0  # 全程上涨


def test_metrics_drawdown():
    """有回撤的曲线。"""
    curve = [
        ("2024-01-01", 1.0),
        ("2024-01-02", 1.5),
        ("2024-01-03", 0.75),  # 从 1.5 → 0.75，回撤 50%
        ("2024-01-04", 1.0),
    ]
    m = compute_metrics(curve)
    assert abs(m["max_drawdown"] - 0.5) < 1e-9


def test_metrics_empty():
    """单点曲线 → 全 0。"""
    m = compute_metrics([("2024-01-01", 1.0)])
    assert m["cum_return"] == 0.0


# ─── 反向哨兵 ────────────────────────────────────────────────

def test_signal_must_use_only_past():
    """构造一个"完美未来信号"——signal 用 delay(close, 0)（今天的 close），
    并不直接窥探未来。但能选到 top close 也只对应今天，未必对应 next_ret。
    所以总收益不会爆表（不会有作弊的迹象）。
    """
    p = parse(
        "factor s = close\n"
        "strategy {\n"
        "    universe:  cn:sample\n"
        "    signal:    s\n"
        "    select:    top 1\n"
        "    rebalance: daily\n"
        "}\n"
    )
    # A 在前 2 天高，后 2 天低；B 反之
    # 如果信号有未来视角，会持续选对赢家；我们的实现按 close_t 选，应该真实
    df = make_df({
        "A": [200.0, 200.0, 50.0, 50.0],
        "B": [100.0, 100.0, 100.0, 100.0],
    })
    result = run(p, df)
    # day 1：close A=200 > B=100，选 A。next_ret_A = 200/200-1=0；NAV=1.0
    # day 2：close A=200 > B=100，选 A。next_ret_A = 50/200-1=-0.75；NAV=0.25
    # day 3：close A=50 < B=100，选 B。next_ret_B = 100/100-1=0；NAV=0.25
    # day 4：last day, NAV unchanged
    assert abs(result.nav_curve[-1][1] - 0.25) < 1e-6
    # 确认有 50% 以上的回撤
    assert result.metrics["max_drawdown"] > 0.7


# ─── 端到端 ─────────────────────────────────────────────────

def test_full_run_with_architecture_example():
    """架构示例完整跑通。"""
    p = parse(
        "factor mom = close / delay(close, 1) - 1\n"
        "factor s = rank(mom)\n"
        "strategy {\n"
        "    universe:  cn:sample\n"
        "    signal:    s\n"
        "    select:    top 1\n"
        "    rebalance: weekly\n"
        "}\n"
    )
    # 5 只股票，10 天数据
    closes = {
        "A": [100.0 + i * 1 for i in range(10)],
        "B": [100.0 + i * 2 for i in range(10)],
        "C": [100.0 - i * 1 for i in range(10)],
        "D": [100.0 + i * 0.5 for i in range(10)],
        "E": [100.0 + i * 1.5 for i in range(10)],
    }
    df = make_df(closes)
    result = run(p, df)
    assert result.metrics["cum_return"] is not None
    assert len(result.nav_curve) == 10
    assert result.rows_used > 0
    assert result.universe == "cn:sample"
    assert result.top_n == 1
    assert result.rebalance == "weekly"
    assert result.duration_ms < 5000  # 应该很快
