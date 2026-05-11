"""DSL 白名单：字段、算子、策略字段。

**单一来源**——下游所有需要"白名单"的地方都从这里 import：
- parser 做静态校验
- executor 派发到 Polars 实现
- AI prompt 拼接时（Phase 7）从这里读
- tests 验证一致性
"""
from __future__ import annotations

from typing import Final

# ─── 字段白名单 ──────────────────────────────────────────────

FIELDS: Final[frozenset[str]] = frozenset({
    "open", "high", "low", "close", "volume", "amount", "vwap",
})


# ─── 算子白名单（13 个，按类别）──────────────────────────────

TS_OPERATORS: Final[frozenset[str]] = frozenset({
    "delay", "ma", "std", "sum", "max_ts", "min_ts", "returns",
    "ts_argmax", "ts_argmin", "ts_rank", "decay_linear", "corr",
})

CS_OPERATORS: Final[frozenset[str]] = frozenset({
    "rank", "zscore",
})

MATH_OPERATORS: Final[frozenset[str]] = frozenset({
    "abs", "log", "sign",
})

OPERATORS: Final[frozenset[str]] = TS_OPERATORS | CS_OPERATORS | MATH_OPERATORS


# ─── 算子参数数量约束 ───────────────────────────────────────

OPERATOR_ARITY: Final[dict[str, int]] = {
    # 时序（窗口型）：(data, window)
    "delay": 2,
    "ma": 2,
    "std": 2,
    "sum": 2,
    "max_ts": 2,
    "min_ts": 2,
    "ts_argmax": 2,
    "ts_argmin": 2,
    "ts_rank": 2,
    "decay_linear": 2,
    # 时序（双参 + 窗口）：(x, y, window)
    "corr": 3,
    # 时序（单参）：(data) → 单期收益
    "returns": 1,
    # 横截面：(data)
    "rank": 1,
    "zscore": 1,
    # 数学：(data)
    "abs": 1,
    "log": 1,
    "sign": 1,
}

# 窗口参数的位置（0-indexed），必须是"非负整数常量"——防前视偏差第一道防线
# 大多数算子是 args[1]，corr 是 args[2]
WINDOW_OPS: Final[dict[str, int]] = {
    "delay": 1, "ma": 1, "std": 1, "sum": 1, "max_ts": 1, "min_ts": 1,
    "ts_argmax": 1, "ts_argmin": 1, "ts_rank": 1, "decay_linear": 1,
    "corr": 2,
}


# ─── 策略字段白名单 ──────────────────────────────────────────

STRATEGY_FIELDS: Final[frozenset[str]] = frozenset({
    "universe", "signal", "select", "rebalance", "start", "end",
})

STRATEGY_REQUIRED: Final[frozenset[str]] = frozenset({
    "universe", "signal", "select", "rebalance",
})


# ─── 字段值白名单 ────────────────────────────────────────────

REBALANCE_FREQS: Final[frozenset[str]] = frozenset({
    "daily", "weekly", "monthly",
})


# ─── 关键字（不能用作 factor / 字段名）────────────────────────

KEYWORDS: Final[frozenset[str]] = frozenset({
    "factor", "strategy", "top",
})


def is_reserved(name: str) -> bool:
    """检查名字是否是保留字（字段/算子/关键字），用于禁止 factor 同名。"""
    return name in FIELDS or name in OPERATORS or name in KEYWORDS
