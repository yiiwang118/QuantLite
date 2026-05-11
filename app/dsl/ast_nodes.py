"""DSL AST 节点定义。

设计原则：节点是只读 dataclass，带 line/col 用于错误定位。
所有节点都可以被 executor 模式匹配（Phase 3）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Union

# ─── 表达式节点 ──────────────────────────────────────────────

@dataclass(frozen=True)
class Number:
    """数字字面量。"""
    value: float
    line: int = 0
    col: int = 0


@dataclass(frozen=True)
class Field:
    """字段引用，如 close / open / volume。"""
    name: str
    line: int = 0
    col: int = 0


@dataclass(frozen=True)
class FactorRef:
    """对已定义因子的引用，如 mom20。"""
    name: str
    line: int = 0
    col: int = 0


@dataclass(frozen=True)
class Call:
    """算子调用，如 delay(close, 20)。"""
    op: str
    args: tuple["Expr", ...]
    line: int = 0
    col: int = 0


@dataclass(frozen=True)
class UnaryOp:
    """一元运算，目前只有负号 -expr。"""
    op: str          # "-"
    operand: "Expr"
    line: int = 0
    col: int = 0


@dataclass(frozen=True)
class BinOp:
    """二元运算：+ - * /。"""
    op: str          # "+", "-", "*", "/"
    left: "Expr"
    right: "Expr"
    line: int = 0
    col: int = 0


Expr = Union[Number, Field, FactorRef, Call, UnaryOp, BinOp]


# ─── 顶层结构 ────────────────────────────────────────────────

@dataclass(frozen=True)
class FactorDef:
    """factor name = expr。"""
    name: str
    expr: Expr
    line: int = 0
    col: int = 0


@dataclass(frozen=True)
class Strategy:
    """strategy { ... } 块。"""
    universe: str             # 如 "cn:sample"
    signal: str               # 引用的 factor 名
    top_n: int                # select: top N
    rebalance: str            # daily / weekly / monthly
    start: date | None = None
    end: date | None = None
    line: int = 0
    col: int = 0


@dataclass(frozen=True)
class Program:
    """整个 DSL 程序。"""
    factors: tuple[FactorDef, ...]
    strategy: Strategy | None     # 允许只有 factor 定义（用于因子单独验证）


# ─── 异常 ────────────────────────────────────────────────────

class DSLError(Exception):
    """DSL 解析 / 校验异常，带行列号。"""

    def __init__(self, message: str, line: int = 0, col: int = 0):
        self.message = message
        self.line = line
        self.col = col
        prefix = f"L{line}:{col} " if line else ""
        super().__init__(f"{prefix}{message}")
