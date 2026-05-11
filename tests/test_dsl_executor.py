"""DSL 执行器测试。

覆盖：
- 13 个算子各自的语义
- 跨股票隔离（时序算子）
- 跨日期隔离（横截面算子）
- 防前视偏差（无法引用未来行）
- 完整示例端到端（parse → evaluate → __signal__）
"""
from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from app.dsl import evaluate, parse


# ─── 测试夹具 ───────────────────────────────────────────────

def make_df(closes_by_symbol: dict[str, list[float]], market: str = "cn") -> pl.DataFrame:
    """从 {symbol: [close per day]} 字典造 UNIVERSE_SCHEMA 长表。

    保证所有 symbol 长度一致，且按 (market, symbol, date) 排序。
    """
    n_days = len(next(iter(closes_by_symbol.values())))
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]
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


def col_of(df: pl.DataFrame, symbol: str, name: str) -> list:
    return df.filter(pl.col("symbol") == symbol)[name].to_list()


# ─── 基础节点 ───────────────────────────────────────────────

def test_field_passthrough():
    p = parse("factor f = close")
    out = evaluate(p, make_df({"A": [10, 11, 12]}))
    assert col_of(out, "A", "f") == [10.0, 11.0, 12.0]


def test_arithmetic():
    p = parse("factor f = close + 5")
    out = evaluate(p, make_df({"A": [10, 20]}))
    assert col_of(out, "A", "f") == [15.0, 25.0]


def test_unary_negate():
    p = parse("factor f = -close")
    out = evaluate(p, make_df({"A": [10, 20]}))
    assert col_of(out, "A", "f") == [-10.0, -20.0]


def test_arithmetic_precedence():
    p = parse("factor f = close + 2 * 3")
    out = evaluate(p, make_df({"A": [10]}))
    assert col_of(out, "A", "f") == [16.0]  # 10 + (2 * 3)


# ─── 时序算子 ───────────────────────────────────────────────

def test_delay():
    p = parse("factor f = delay(close, 1)")
    out = evaluate(p, make_df({"A": [10, 11, 12]}))
    assert col_of(out, "A", "f") == [None, 10.0, 11.0]


def test_delay_zero_is_identity():
    p = parse("factor f = delay(close, 0)")
    out = evaluate(p, make_df({"A": [10, 11, 12]}))
    assert col_of(out, "A", "f") == [10.0, 11.0, 12.0]


def test_ma():
    p = parse("factor f = ma(close, 3)")
    out = evaluate(p, make_df({"A": [10, 20, 30, 40, 50]}))
    vals = col_of(out, "A", "f")
    assert vals[0] is None and vals[1] is None
    assert vals[2] == 20.0  # (10+20+30)/3
    assert vals[3] == 30.0
    assert vals[4] == 40.0


def test_std():
    p = parse("factor f = std(close, 3)")
    # 三个相同的值 std=0
    out = evaluate(p, make_df({"A": [10, 10, 10, 10]}))
    vals = col_of(out, "A", "f")
    assert vals[2] == 0.0
    assert vals[3] == 0.0


def test_sum():
    p = parse("factor f = sum(close, 2)")
    out = evaluate(p, make_df({"A": [10, 20, 30]}))
    vals = col_of(out, "A", "f")
    assert vals[0] is None
    assert vals[1] == 30.0
    assert vals[2] == 50.0


def test_max_ts_min_ts():
    p = parse("factor h = max_ts(close, 3)\nfactor l = min_ts(close, 3)")
    out = evaluate(p, make_df({"A": [10, 30, 20, 5, 15]}))
    high = col_of(out, "A", "h")
    low = col_of(out, "A", "l")
    assert high[2] == 30.0 and low[2] == 10.0
    assert high[3] == 30.0 and low[3] == 5.0
    assert high[4] == 20.0 and low[4] == 5.0


def test_returns():
    p = parse("factor f = returns(close)")
    out = evaluate(p, make_df({"A": [100, 110, 121]}))
    vals = col_of(out, "A", "f")
    assert vals[0] is None
    assert abs(vals[1] - 0.1) < 1e-9
    assert abs(vals[2] - 0.1) < 1e-9


# ─── 跨股票隔离（时序算子） ───────────────────────────────

def test_delay_isolates_symbols():
    """delay 不能跨股票拿数据。"""
    p = parse("factor f = delay(close, 1)")
    out = evaluate(p, make_df({"A": [10, 11], "B": [100, 110]}))
    assert col_of(out, "A", "f") == [None, 10.0]
    assert col_of(out, "B", "f") == [None, 100.0]


def test_ma_isolates_symbols():
    p = parse("factor f = ma(close, 2)")
    out = evaluate(p, make_df({"A": [10, 20], "B": [100, 200]}))
    assert col_of(out, "A", "f") == [None, 15.0]
    assert col_of(out, "B", "f") == [None, 150.0]


# ─── 横截面算子 ─────────────────────────────────────────────

def test_rank_normalized():
    """rank 输出 [-0.5, 0.5]；线性分布。"""
    p = parse("factor f = rank(close)")
    out = evaluate(p, make_df({"A": [1.0], "B": [2.0], "C": [3.0]}))
    vals = {r["symbol"]: r["f"] for r in out.iter_rows(named=True)}
    assert vals["A"] == -0.5
    assert vals["B"] == 0.0
    assert vals["C"] == 0.5


def test_rank_isolates_dates():
    """rank 按 date 分组；前后日数据不互相影响。"""
    p = parse("factor f = rank(close)")
    out = evaluate(p, make_df({
        "A": [10, 100],
        "B": [20, 50],
    }))
    # day1: A=10 (低), B=20 (高) → A=-0.5, B=0.5
    # day2: A=100 (高), B=50 (低) → A=0.5, B=-0.5
    a = col_of(out, "A", "f")
    b = col_of(out, "B", "f")
    assert a == [-0.5, 0.5]
    assert b == [0.5, -0.5]


def test_rank_handles_nulls():
    """rank(delay(close, 1)) day 1 应该是 null（输入为 null）。"""
    p = parse("factor f = rank(delay(close, 1))")
    out = evaluate(p, make_df({"A": [10, 11], "B": [20, 22]}))
    # day 1: delay = null/null → rank = null
    day1 = out.filter(pl.col("date") == date(2024, 1, 1))["f"].to_list()
    assert all(v is None for v in day1)


def test_zscore():
    """zscore 把每日多股票标准化到均值 0 标准差 1。"""
    p = parse("factor f = zscore(close)")
    # 3 个值 [1, 2, 3]：均值 2，std=1（pl 默认 ddof=1 时 std=1.0）
    out = evaluate(p, make_df({"A": [1.0], "B": [2.0], "C": [3.0]}))
    vals = {r["symbol"]: r["f"] for r in out.iter_rows(named=True)}
    # Polars std 默认 ddof=1：std = 1.0
    assert abs(vals["A"] - (-1.0)) < 1e-9
    assert abs(vals["B"] - 0.0) < 1e-9
    assert abs(vals["C"] - 1.0) < 1e-9


# ─── 数学算子 ───────────────────────────────────────────────

def test_abs():
    p = parse("factor f = abs(close - 50)")
    out = evaluate(p, make_df({"A": [10, 50, 100]}))
    assert col_of(out, "A", "f") == [40.0, 0.0, 50.0]


def test_sign():
    p = parse("factor f = sign(close - 50)")
    out = evaluate(p, make_df({"A": [10, 50, 100]}))
    assert col_of(out, "A", "f") == [-1.0, 0.0, 1.0]


def test_log():
    import math
    p = parse("factor f = log(close)")
    out = evaluate(p, make_df({"A": [1.0]}))
    val = col_of(out, "A", "f")[0]
    assert abs(val - 0.0) < 1e-9  # log(1) = 0


# ─── factor 链式引用 ────────────────────────────────────────

def test_factor_reference_chain():
    """后面的 factor 可以引用前面的 factor。"""
    dsl = """
    factor a = close * 2
    factor b = a + 1
    factor c = b - a
    """
    p = parse(dsl)
    out = evaluate(p, make_df({"A": [10]}))
    assert col_of(out, "A", "a") == [20.0]
    assert col_of(out, "A", "b") == [21.0]
    assert col_of(out, "A", "c") == [1.0]


# ─── 防前视偏差（综合） ───────────────────────────────────

def test_no_negative_shift_possible():
    """parser 已经在 A1 拦掉负窗口；executor 兜底也不会接受。"""
    from app.dsl import DSLError
    with pytest.raises(DSLError, match="非负整数"):
        parse("factor f = delay(close, -1)")


def test_signal_column_only_uses_past_data():
    """信号在 day t 只能用 ≤ day t 的数据。

    构造：close = 1, 2, 4, 8 (×2 涨)
    mom = close / delay(close, 1) - 1
    day 1: null (no prior)
    day 2: 2/1 - 1 = 1.0  ← 只用了 day 1 和 day 2，没用 day 3、4
    day 3: 4/2 - 1 = 1.0
    day 4: 8/4 - 1 = 1.0
    """
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
    out = evaluate(p, make_df({"A": [1.0, 2.0, 4.0, 8.0]}))
    mom = col_of(out, "A", "mom")
    assert mom[0] is None
    assert abs(mom[1] - 1.0) < 1e-9


# ─── __signal__ 列 ──────────────────────────────────────────

def test_signal_column_added_when_strategy_given():
    p = parse(
        "factor s = close\n"
        "strategy {\n"
        "    universe: cn:sample\n"
        "    signal: s\n"
        "    select: top 1\n"
        "    rebalance: weekly\n"
        "}\n"
    )
    out = evaluate(p, make_df({"A": [10, 20]}))
    assert "__signal__" in out.columns
    assert col_of(out, "A", "__signal__") == [10.0, 20.0]


def test_no_signal_column_without_strategy():
    p = parse("factor f = close")
    out = evaluate(p, make_df({"A": [10]}))
    assert "__signal__" not in out.columns
    assert "f" in out.columns


# ─── 端到端：架构示例 ─────────────────────────────────────

def test_architecture_example_runs():
    """完整跑通架构 §4.1.1 示例，得到 __signal__ 列。"""
    dsl = """
    factor mom20 = close / delay(close, 1) - 1
    factor vol5 = std(returns(close), 5)
    factor score = rank(mom20) - rank(vol5)
    strategy {
        universe:  cn:sample
        signal:    score
        select:    top 2
        rebalance: weekly
        start:     2024-01-01
    }
    """
    p = parse(dsl)
    # 给 3 只股票各 8 天数据
    df = make_df({
        "A": [10, 11, 12, 11, 13, 14, 13, 15],
        "B": [20, 19, 21, 22, 23, 22, 24, 25],
        "C": [30, 31, 32, 33, 32, 34, 35, 36],
    })
    out = evaluate(p, df)
    assert "mom20" in out.columns
    assert "vol5" in out.columns
    assert "score" in out.columns
    assert "__signal__" in out.columns
    # 最后一天三只股票都有 score
    last = out.filter(pl.col("date") == date(2024, 1, 8))
    scores = last["__signal__"].to_list()
    assert len(scores) == 3
    assert all(s is not None for s in scores)
    # rank(mom20) - rank(vol5) 范围在 [-1, 1]
    for s in scores:
        assert -1.0 <= s <= 1.0
