"""C 阶段新增的 5 个算子的测试。"""
from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from app.dsl import DSLError, evaluate, parse


def make_df(closes_by_symbol: dict[str, list[float]], market: str = "cn",
            volumes_by_symbol: dict[str, list[float]] | None = None) -> pl.DataFrame:
    n_days = len(next(iter(closes_by_symbol.values())))
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]
    rows = []
    for sym, closes in closes_by_symbol.items():
        vols = volumes_by_symbol.get(sym) if volumes_by_symbol else [100] * len(closes)
        for i, c in enumerate(closes):
            rows.append({
                "date": dates[i], "market": market, "symbol": sym,
                "open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                "volume": int(vols[i]), "amount": c * vols[i],
            })
    return pl.DataFrame(
        rows,
        schema={
            "date": pl.Date, "market": pl.Utf8, "symbol": pl.Utf8,
            "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
            "close": pl.Float64, "volume": pl.Int64, "amount": pl.Float64,
        },
    ).sort(["market", "symbol", "date"])


def col_of(df, symbol, name):
    return df.filter(pl.col("symbol") == symbol)[name].to_list()


# ─── ts_argmax / ts_argmin ─────────────────────────────────

def test_ts_argmax_returns_position():
    """ts_argmax(x, n) 返回窗口内最大值的位置（0=最旧，n-1=当前）。"""
    p = parse("factor f = ts_argmax(close, 3)")
    # close = [10, 30, 20, 5, 50]
    # window 3：
    #  index 2: [10, 30, 20] → max at pos 1
    #  index 3: [30, 20,  5] → max at pos 0
    #  index 4: [20,  5, 50] → max at pos 2
    out = evaluate(p, make_df({"A": [10, 30, 20, 5, 50]}))
    vals = col_of(out, "A", "f")
    assert vals[0] is None and vals[1] is None  # 不足窗口
    assert vals[2] == 1.0
    assert vals[3] == 0.0
    assert vals[4] == 2.0


def test_ts_argmin_returns_position():
    p = parse("factor f = ts_argmin(close, 3)")
    out = evaluate(p, make_df({"A": [10, 30, 20, 5, 50]}))
    vals = col_of(out, "A", "f")
    assert vals[2] == 0.0   # min at pos 0 (=10)
    assert vals[3] == 2.0   # min at pos 2 (=5)
    assert vals[4] == 1.0   # min at pos 1 (=5)


# ─── ts_rank ────────────────────────────────────────────────

def test_ts_rank_percentile():
    """ts_rank(x, n)：当前值在 n 期窗口内的百分位 [0, 1]。"""
    p = parse("factor f = ts_rank(close, 5)")
    # close = [10, 20, 30, 40, 50, 25]
    # idx 4: window [10, 20, 30, 40, 50] → 50 is largest → rank 4 → (5-1)/(5-1) = 1.0
    # idx 5: window [20, 30, 40, 50, 25] → 25 is 2nd smallest → rank 2 → (2-1)/(5-1) = 0.25
    out = evaluate(p, make_df({"A": [10, 20, 30, 40, 50, 25]}))
    vals = col_of(out, "A", "f")
    assert vals[3] is None  # idx 3 不足窗口 (需要 5 个，只有 4 个)
    assert abs(vals[4] - 1.0) < 1e-9
    assert abs(vals[5] - 0.25) < 1e-9


# ─── decay_linear ───────────────────────────────────────────

def test_decay_linear_weights():
    """decay_linear(x, n)：线性递减权重的加权均值。"""
    p = parse("factor f = decay_linear(close, 3)")
    # n=3: weights = [3, 2, 1] / 6 = [0.5, 0.333, 0.167]
    # 当前权重 3，1 期前权重 2，2 期前权重 1
    # close = [1, 2, 3, 4]
    # idx 2: 3*3 + 2*2 + 1*1 = 9 + 4 + 1 = 14, / 6 = 2.333
    # idx 3: 3*4 + 2*3 + 1*2 = 12 + 6 + 2 = 20, / 6 = 3.333
    out = evaluate(p, make_df({"A": [1.0, 2.0, 3.0, 4.0]}))
    vals = col_of(out, "A", "f")
    assert vals[0] is None and vals[1] is None
    assert abs(vals[2] - (14 / 6)) < 1e-9
    assert abs(vals[3] - (20 / 6)) < 1e-9


# ─── corr ───────────────────────────────────────────────────

def test_corr_basic():
    """corr(x, y, n) = 滚动相关系数。close 与 volume 正相关 → corr ≈ 1。"""
    p = parse("factor f = corr(close, volume, 5)")
    df = make_df(
        {"A": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]},
        volumes_by_symbol={"A": [100, 110, 120, 130, 140, 150]},
    )
    out = evaluate(p, df)
    vals = col_of(out, "A", "f")
    # 完美线性相关 → 1.0
    assert vals[3] is None
    assert abs(vals[4] - 1.0) < 1e-6
    assert abs(vals[5] - 1.0) < 1e-6


def test_corr_negative():
    """close 涨、volume 跌 → corr 接近 -1。"""
    p = parse("factor f = corr(close, volume, 5)")
    df = make_df(
        {"A": [10.0, 11.0, 12.0, 13.0, 14.0]},
        volumes_by_symbol={"A": [150, 140, 130, 120, 110]},
    )
    out = evaluate(p, df)
    val = col_of(out, "A", "f")[4]
    assert abs(val - (-1.0)) < 1e-6


# ─── 防前视偏差（C 算子也应该被拦）──────────────────────

def test_ts_argmax_window_must_be_positive_int():
    with pytest.raises(DSLError, match="非负整数"):
        parse("factor f = ts_argmax(close, -3)")


def test_corr_window_arg_position():
    """corr 的窗口参数在 args[2]。负数被拦。"""
    with pytest.raises(DSLError, match="非负整数"):
        parse("factor f = corr(close, volume, -5)")


def test_decay_linear_non_constant_window():
    """非常量窗口被拦。"""
    with pytest.raises(DSLError, match="必须是常量"):
        parse(
            "factor n = close\n"
            "factor f = decay_linear(close, n)"
        )


# ─── 端到端（在 strategy 里用新算子）──────────────────

def test_full_strategy_with_new_operators():
    """完整策略用新算子。"""
    dsl = """
    factor mom_pos = ts_argmax(close, 20)
    factor pv_corr = corr(close, volume, 20)
    factor smooth_close = decay_linear(close, 5)
    factor s = rank(mom_pos) + rank(pv_corr)
    strategy {
        universe: cn:sample
        signal:   s
        select:   top 2
        rebalance: weekly
        start: 2024-01-01
    }
    """
    p = parse(dsl)
    # 跑得通就行
    assert len(p.factors) == 4
    assert p.strategy is not None
