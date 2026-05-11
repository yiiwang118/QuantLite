"""回测净值曲线的 6 个标准指标。

固定年化基数 = 252 个交易日，不按实际天数动态算（保证不同时间段可比）。
"""
from __future__ import annotations

import math
import statistics

_TRADING_DAYS_PER_YEAR = 252


def compute_metrics(nav_curve: list[tuple[str, float]]) -> dict[str, float]:
    """从 [(date_iso, nav), ...] 算 6 个指标。"""
    if len(nav_curve) < 2:
        return _empty()

    navs = [v for _, v in nav_curve]
    n = len(navs)
    nav0, nav_end = navs[0], navs[-1]

    if nav0 <= 0:
        return _empty()

    cum_return = nav_end / nav0 - 1.0

    # 年化收益：(nav_end / nav0) ^ (252 / n) - 1
    years = n / _TRADING_DAYS_PER_YEAR
    if nav_end > 0 and years > 0:
        annual_return = (nav_end / nav0) ** (1.0 / years) - 1.0
    else:
        annual_return = -1.0  # 完全亏空

    # 每日收益（n-1 个）
    daily_rets = [navs[i] / navs[i - 1] - 1.0 for i in range(1, n)]

    # 年化波动 = std(daily_rets) * sqrt(252)
    if len(daily_rets) >= 2:
        std = statistics.stdev(daily_rets)
        annual_vol = std * math.sqrt(_TRADING_DAYS_PER_YEAR)
    else:
        annual_vol = 0.0

    # 夏普（无风险利率 0）
    sharpe = annual_return / annual_vol if annual_vol > 0 else 0.0

    # 最大回撤
    peak = navs[0]
    max_dd = 0.0
    for v in navs:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd

    # 胜率：正收益日 / 非零收益日
    nonzero = [r for r in daily_rets if r != 0]
    if nonzero:
        wins = sum(1 for r in nonzero if r > 0)
        win_rate = wins / len(nonzero)
    else:
        win_rate = 0.0

    return {
        "cum_return": cum_return,
        "annual_return": annual_return,
        "annual_vol": annual_vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
    }


def _empty() -> dict[str, float]:
    return {
        "cum_return": 0.0,
        "annual_return": 0.0,
        "annual_vol": 0.0,
        "sharpe": 0.0,
        "max_drawdown": 0.0,
        "win_rate": 0.0,
    }
