"""DSL 模块对外接口。

下游模块（executor、API、AI prompt）从这里 import，不要直接 import 子模块。
"""
from app.dsl.ast_nodes import (
    BinOp,
    Call,
    DSLError,
    Expr,
    FactorDef,
    FactorRef,
    Field,
    Number,
    Program,
    Strategy,
    UnaryOp,
)
from app.dsl.executor import evaluate
from app.dsl.parser import parse
from app.dsl.whitelist import (
    FIELDS,
    OPERATORS,
    OPERATOR_ARITY,
    REBALANCE_FREQS,
    STRATEGY_FIELDS,
    STRATEGY_REQUIRED,
    TS_OPERATORS,
    CS_OPERATORS,
    MATH_OPERATORS,
    WINDOW_OPS,
)

__all__ = [
    # parser 接口
    "parse",
    "evaluate",
    "DSLError",
    # AST 节点
    "Program",
    "FactorDef",
    "Strategy",
    "Expr",
    "Number",
    "Field",
    "FactorRef",
    "Call",
    "UnaryOp",
    "BinOp",
    # 白名单常量
    "FIELDS",
    "OPERATORS",
    "OPERATOR_ARITY",
    "TS_OPERATORS",
    "CS_OPERATORS",
    "MATH_OPERATORS",
    "WINDOW_OPS",
    "STRATEGY_FIELDS",
    "STRATEGY_REQUIRED",
    "REBALANCE_FREQS",
]
