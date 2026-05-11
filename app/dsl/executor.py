"""DSL 执行器：AST → Polars 表达式。

入口：`evaluate(program, df)` —— 给一个 UNIVERSE_SCHEMA 的长表，
返回追加了所有 factor 列 + `__signal__` 列的新 df。

防前视偏差**第二道防线**（执行期）：
- 所有窗口型算子用 `shift(n), n ≥ 0` —— 永远不访问未来行
- 时序算子 `.over(['market', 'symbol'])` —— 防止跨股票数据污染
- 横截面算子 `.over('date')` —— 同一日内的多股票排序，不跨日

13 个算子（与 `whitelist.py` 同步）：
- 时序窗口型：delay, ma, std, sum, max_ts, min_ts
- 时序单参：returns
- 横截面：rank, zscore
- 数学：abs, log, sign
"""
from __future__ import annotations

import polars as pl

from app.dsl.ast_nodes import (
    BinOp,
    Call,
    Expr,
    Field,
    FactorRef,
    Number,
    Program,
    UnaryOp,
)


_SIGNAL_COL = "__signal__"


def evaluate(program: Program, df: pl.DataFrame) -> pl.DataFrame:
    """运行 program，给 df 追加 factor 列；若有 strategy，再加 __signal__。

    要求 df 至少包含 UNIVERSE_SCHEMA 的列：date / market / symbol / OHLCV。
    会先按 (market, symbol, date) 排序，再按 factor 定义顺序逐个 with_columns。
    """
    df = df.sort(["market", "symbol", "date"])
    for factor_def in program.factors:
        expr = _translate(factor_def.expr).alias(factor_def.name)
        df = df.with_columns(expr)
    if program.strategy is not None:
        # __signal__ = 引用 strategy.signal 那一列
        df = df.with_columns(pl.col(program.strategy.signal).alias(_SIGNAL_COL))
    return df


# ─── 节点分发 ────────────────────────────────────────────────

def _translate(node: Expr) -> pl.Expr:
    if isinstance(node, Number):
        return pl.lit(node.value, dtype=pl.Float64)
    if isinstance(node, Field):
        return pl.col(node.name).cast(pl.Float64)
    if isinstance(node, FactorRef):
        return pl.col(node.name)
    if isinstance(node, UnaryOp):
        if node.op == "-":
            return -_translate(node.operand)
        raise RuntimeError(f"unsupported unary op: {node.op!r}")
    if isinstance(node, BinOp):
        left = _translate(node.left)
        right = _translate(node.right)
        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        if node.op == "/":
            return left / right
        raise RuntimeError(f"unsupported bin op: {node.op!r}")
    if isinstance(node, Call):
        return _translate_call(node)
    raise RuntimeError(f"unsupported AST node: {type(node).__name__}")


# ─── 算子分发 ────────────────────────────────────────────────

def _translate_call(call: Call) -> pl.Expr:
    op = call.op
    args = call.args

    # ── 时序窗口型：window 是非负整数常量（parser 已保证）──
    if op == "delay":
        x, n = _translate(args[0]), _window(args[1])
        return x.shift(n).over(["market", "symbol"])

    if op == "ma":
        x, n = _translate(args[0]), _window(args[1])
        return x.rolling_mean(window_size=n, min_samples=n).over(["market", "symbol"])

    if op == "std":
        x, n = _translate(args[0]), _window(args[1])
        return x.rolling_std(window_size=n, min_samples=n).over(["market", "symbol"])

    if op == "sum":
        x, n = _translate(args[0]), _window(args[1])
        return x.rolling_sum(window_size=n, min_samples=n).over(["market", "symbol"])

    if op == "max_ts":
        x, n = _translate(args[0]), _window(args[1])
        return x.rolling_max(window_size=n, min_samples=n).over(["market", "symbol"])

    if op == "min_ts":
        x, n = _translate(args[0]), _window(args[1])
        return x.rolling_min(window_size=n, min_samples=n).over(["market", "symbol"])

    # ── 时序窗口型（新增）─────────────────────────────────
    if op == "ts_argmax":
        x, n = _translate(args[0]), _window(args[1])
        # 窗口内最大值的相对位置（0=窗口最旧，n-1=当前）
        return x.rolling_map(
            lambda s: float(s.arg_max()) if s.is_not_null().any() else float("nan"),
            window_size=n, min_samples=n,
        ).over(["market", "symbol"])

    if op == "ts_argmin":
        x, n = _translate(args[0]), _window(args[1])
        return x.rolling_map(
            lambda s: float(s.arg_min()) if s.is_not_null().any() else float("nan"),
            window_size=n, min_samples=n,
        ).over(["market", "symbol"])

    if op == "ts_rank":
        x, n = _translate(args[0]), _window(args[1])
        # 当前值在 n 期窗口内的百分位（0=最小，1=最大）
        return x.rolling_map(
            _ts_rank_window, window_size=n, min_samples=n,
        ).over(["market", "symbol"])

    if op == "decay_linear":
        x, n = _translate(args[0]), _window(args[1])
        # 线性递减权重的加权均值：当前权重 n，n-1 期前权重 1
        # 用 shift(i) * (n - i) 求和再除以总权重
        if n <= 0:
            return x  # 退化
        total_weight = n * (n + 1) // 2
        parts = [x.shift(i) * (n - i) for i in range(n)]
        result = parts[0]
        for p in parts[1:]:
            result = result + p
        return (result / total_weight).over(["market", "symbol"])

    if op == "corr":
        x = _translate(args[0])
        y = _translate(args[1])
        n = _window(args[2])
        # 滚动相关：cov / (std_x * std_y)
        mean_x = x.rolling_mean(window_size=n, min_samples=n)
        mean_y = y.rolling_mean(window_size=n, min_samples=n)
        cov = (x * y).rolling_mean(window_size=n, min_samples=n) - mean_x * mean_y
        var_x = (x * x).rolling_mean(window_size=n, min_samples=n) - mean_x * mean_x
        var_y = (y * y).rolling_mean(window_size=n, min_samples=n) - mean_y * mean_y
        std_prod = var_x.sqrt() * var_y.sqrt()
        # 窗口不足（std_prod 为 null）→ null；std_prod = 0（常数列）→ 0；否则正常
        return (
            pl.when(std_prod.is_null())
            .then(pl.lit(None, dtype=pl.Float64))
            .when(std_prod > 0)
            .then(cov / std_prod)
            .otherwise(pl.lit(0.0, dtype=pl.Float64))
        ).over(["market", "symbol"])

    # ── 时序单参：日收益率 ─────────────────────────────────
    if op == "returns":
        x = _translate(args[0])
        return ((x / x.shift(1)) - 1).over(["market", "symbol"])

    # ── 横截面：同日跨股票 ─────────────────────────────────
    if op == "rank":
        x = _translate(args[0])
        return _rank_normalized(x)

    if op == "zscore":
        x = _translate(args[0])
        return _zscore(x)

    # ── 数学：元素级 ────────────────────────────────────────
    if op == "abs":
        return _translate(args[0]).abs()

    if op == "log":
        return _translate(args[0]).log()

    if op == "sign":
        return _translate(args[0]).sign()

    raise RuntimeError(f"unsupported operator: {op!r}")


def _window(node: Expr) -> int:
    """把窗口参数 AST 解析成 int。parser 已保证它是非负整数常量。"""
    # 直接 Number
    if isinstance(node, Number):
        return int(node.value)
    # 一元负号 + Number —— 理论上 parser 会拦掉负数，但兜底处理
    if isinstance(node, UnaryOp) and node.op == "-" and isinstance(node.operand, Number):
        v = -int(node.operand.value)
        if v < 0:
            raise RuntimeError(f"negative window slipped past parser: {v}")
        return v
    raise RuntimeError(f"window must be a constant int, got {type(node).__name__}")


# ─── rank / zscore 的健壮实现 ─────────────────────────────

def _rank_normalized(x: pl.Expr) -> pl.Expr:
    """横截面排名归一化到 [-0.5, 0.5]，per date。

    - x 为 null → 输出 null
    - 单日只有 ≤1 个非空值 → 输出 0（无法分辨高低）
    - 否则：(rank - 1) / (n_valid - 1) - 0.5
    """
    rank = x.rank(method="average").over("date")
    n_valid = x.is_not_null().sum().over("date")
    return (
        pl.when(x.is_null())
        .then(pl.lit(None, dtype=pl.Float64))
        .when(n_valid <= 1)
        .then(pl.lit(0.0, dtype=pl.Float64))
        .otherwise((rank - 1) / (n_valid - 1) - 0.5)
    )


def _ts_rank_window(s) -> float:
    """ts_rank 的窗口函数：当前值（窗口最末）在窗口中的百分位 [0, 1]。"""
    n = len(s)
    if n == 0:
        return float("nan")
    current = s[-1]
    if current is None:
        return float("nan")
    # 用 polars Series 的 rank 方法太重，直接 numpy
    arr = s.to_numpy()
    valid = arr[~_isnan(arr)]
    if len(valid) <= 1:
        return 0.5
    # current 在 valid 中的位置（百分位）
    less_or_eq = (valid <= current).sum()
    return (less_or_eq - 1) / (len(valid) - 1)


def _isnan(arr):
    import numpy as np
    return np.isnan(arr) if arr.dtype.kind == "f" else (arr != arr)


def _zscore(x: pl.Expr) -> pl.Expr:
    """横截面 zscore：(x - mean) / std，per date。

    - x 为 null → 输出 null
    - std 为 null 或 0（单股或所有相同）→ 输出 0
    """
    mean = x.mean().over("date")
    std = x.std().over("date")
    return (
        pl.when(x.is_null())
        .then(pl.lit(None, dtype=pl.Float64))
        .when(std.is_null() | (std == 0))
        .then(pl.lit(0.0, dtype=pl.Float64))
        .otherwise((x - mean) / std)
    )
