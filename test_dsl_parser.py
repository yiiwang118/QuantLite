"""DSL 解析器测试。

覆盖：
- happy path：架构示例完整解析
- 不变量：防前视偏差（delay 负窗口、非常量窗口）
- 白名单：未知字段 / 未知算子 / 未定义 factor 引用
- 结构：算子参数数量、运算符优先级、括号、注释
- 策略块：必需字段、未知字段、字段重复、universe 多市场
"""
from datetime import date

import pytest

from app.dsl import (
    BinOp,
    Call,
    DSLError,
    FactorRef,
    Field,
    Number,
    UnaryOp,
    parse,
)


# ─── 完整示例（架构 §4.1.1） ──────────────────────────────

EXAMPLE = """
# 定义因子
factor mom20 = close / delay(close, 20) - 1
factor vol60 = std(returns(close), 60)
factor score = rank(mom20) - rank(vol60)

# 定义策略
strategy {
    universe:  cn:sample
    signal:    score
    select:    top 3
    rebalance: weekly
    start:     2023-01-01
}
"""


def test_parse_architecture_example():
    p = parse(EXAMPLE)
    assert len(p.factors) == 3
    assert [f.name for f in p.factors] == ["mom20", "vol60", "score"]

    # mom20 = close / delay(close, 20) - 1
    # 顶层应该是 减法
    mom = p.factors[0].expr
    assert isinstance(mom, BinOp) and mom.op == "-"
    # 左边是 close / delay(close, 20)
    assert isinstance(mom.left, BinOp) and mom.left.op == "/"
    assert isinstance(mom.left.left, Field) and mom.left.left.name == "close"
    delay_call = mom.left.right
    assert isinstance(delay_call, Call) and delay_call.op == "delay"
    assert isinstance(delay_call.args[0], Field) and delay_call.args[0].name == "close"
    assert isinstance(delay_call.args[1], Number) and delay_call.args[1].value == 20

    # 策略
    s = p.strategy
    assert s is not None
    assert s.universe == "cn:sample"
    assert s.signal == "score"
    assert s.top_n == 3
    assert s.rebalance == "weekly"
    assert s.start == date(2023, 1, 1)
    assert s.end is None


# ─── 防前视偏差不变量 ─────────────────────────────────────

def test_reject_negative_delay():
    with pytest.raises(DSLError, match="非负整数"):
        parse("factor f = delay(close, -1)")


def test_reject_decimal_window():
    with pytest.raises(DSLError, match="非负整数"):
        parse("factor f = ma(close, 5.5)")


def test_reject_non_constant_window():
    """delay(x, factor_name) — 窗口必须是常量，不能是变量。"""
    with pytest.raises(DSLError, match="窗口参数必须是常量"):
        parse(
            "factor n = close\n"
            "factor f = delay(close, n)"
        )


def test_accept_zero_window():
    """delay(x, 0) 在语法上允许（等价于不延迟）；非负就行。"""
    p = parse("factor f = delay(close, 0)")
    assert isinstance(p.factors[0].expr, Call)


# ─── 白名单 ─────────────────────────────────────────────

def test_reject_unknown_field():
    with pytest.raises(DSLError, match="未定义的标识符"):
        parse("factor f = turnover + close")


def test_reject_unknown_operator():
    with pytest.raises(DSLError, match="未知算子"):
        parse("factor f = correl(close, 20)")


def test_reject_undefined_factor_reference():
    """引用未先定义的 factor 应该报错。"""
    with pytest.raises(DSLError, match="未定义的标识符"):
        parse(
            "factor a = rank(b)\n"
            "factor b = close"
        )


def test_accept_factor_referenced_after_def():
    """先定义后引用是 OK 的。"""
    p = parse(
        "factor b = close\n"
        "factor a = rank(b)"
    )
    a_expr = p.factors[1].expr
    assert isinstance(a_expr, Call) and a_expr.op == "rank"
    assert isinstance(a_expr.args[0], FactorRef) and a_expr.args[0].name == "b"


# ─── 参数数量 ───────────────────────────────────────────

def test_arity_check_wrong_count():
    with pytest.raises(DSLError, match="需要 2 个参数"):
        parse("factor f = delay(close)")
    with pytest.raises(DSLError, match="需要 1 个参数"):
        parse("factor f = rank(close, 5)")


# ─── 结构性测试 ─────────────────────────────────────────

def test_arithmetic_precedence():
    """close + 2 * 3 应该被解析为 close + (2 * 3)。"""
    p = parse("factor f = close + 2 * 3")
    e = p.factors[0].expr
    assert isinstance(e, BinOp) and e.op == "+"
    assert isinstance(e.left, Field)
    assert isinstance(e.right, BinOp) and e.right.op == "*"


def test_parens_override_precedence():
    """(close + 2) * 3 应该左边是括号里。"""
    p = parse("factor f = (close + 2) * 3")
    e = p.factors[0].expr
    assert isinstance(e, BinOp) and e.op == "*"
    assert isinstance(e.left, BinOp) and e.left.op == "+"


def test_unary_minus():
    p = parse("factor f = -close")
    e = p.factors[0].expr
    assert isinstance(e, UnaryOp) and e.op == "-"
    assert isinstance(e.operand, Field)


def test_comments_ignored():
    code = """
    # 顶层注释
    factor f = close  # 行尾注释
    """
    p = parse(code)
    assert len(p.factors) == 1


def test_decimal_number():
    p = parse("factor f = close * 0.5")
    e = p.factors[0].expr
    assert isinstance(e, BinOp)
    assert isinstance(e.right, Number) and e.right.value == 0.5


# ─── factor 重名 / 保留字 ──────────────────────────────

def test_duplicate_factor_def():
    with pytest.raises(DSLError, match="重复定义"):
        parse(
            "factor f = close\n"
            "factor f = open"
        )


def test_factor_name_collides_with_field():
    with pytest.raises(DSLError, match="冲突"):
        parse("factor close = open")


def test_factor_name_collides_with_operator():
    with pytest.raises(DSLError, match="冲突"):
        parse("factor rank = close")


# ─── 策略块 ─────────────────────────────────────────────

def _minimal_strategy(extra=""):
    return (
        "factor s = close\n"
        "strategy {\n"
        "    universe:  cn:sample\n"
        "    signal:    s\n"
        "    select:    top 3\n"
        "    rebalance: weekly\n"
        + extra +
        "}\n"
    )


def test_strategy_missing_required():
    """缺少 select 字段。"""
    code = (
        "factor s = close\n"
        "strategy {\n"
        "    universe:  cn:sample\n"
        "    signal:    s\n"
        "    rebalance: weekly\n"
        "}\n"
    )
    with pytest.raises(DSLError, match="缺少必需字段"):
        parse(code)


def test_strategy_unknown_field():
    code = (
        "factor s = close\n"
        "strategy {\n"
        "    universe:  cn:sample\n"
        "    signal:    s\n"
        "    select:    top 3\n"
        "    rebalance: weekly\n"
        "    bogus:     value\n"
        "}\n"
    )
    with pytest.raises(DSLError, match="未知策略字段"):
        parse(code)


def test_strategy_duplicate_field():
    code = (
        "factor s = close\n"
        "strategy {\n"
        "    universe:  cn:sample\n"
        "    universe:  us:sample\n"
        "    signal:    s\n"
        "    select:    top 3\n"
        "    rebalance: weekly\n"
        "}\n"
    )
    with pytest.raises(DSLError, match="重复定义"):
        parse(code)


def test_strategy_signal_must_be_factor():
    code = (
        "factor s = close\n"
        "strategy {\n"
        "    universe:  cn:sample\n"
        "    signal:    undefined_factor\n"
        "    select:    top 3\n"
        "    rebalance: weekly\n"
        "}\n"
    )
    with pytest.raises(DSLError, match="必须是已定义的 factor"):
        parse(code)


def test_strategy_universe_us():
    p = parse(_minimal_strategy())
    assert p.strategy.universe == "cn:sample"

    code = (
        "factor s = close\n"
        "strategy {\n"
        "    universe:  us:sample\n"
        "    signal:    s\n"
        "    select:    top 3\n"
        "    rebalance: weekly\n"
        "}\n"
    )
    p2 = parse(code)
    assert p2.strategy.universe == "us:sample"


def test_strategy_invalid_rebalance():
    code = (
        "factor s = close\n"
        "strategy {\n"
        "    universe:  cn:sample\n"
        "    signal:    s\n"
        "    select:    top 3\n"
        "    rebalance: hourly\n"
        "}\n"
    )
    with pytest.raises(DSLError, match="rebalance"):
        parse(code)


def test_strategy_select_must_be_positive():
    code = (
        "factor s = close\n"
        "strategy {\n"
        "    universe:  cn:sample\n"
        "    signal:    s\n"
        "    select:    top 0\n"
        "    rebalance: weekly\n"
        "}\n"
    )
    with pytest.raises(DSLError, match="正整数"):
        parse(code)


def test_strategy_with_end_date():
    p = parse(_minimal_strategy(extra="    start: 2023-01-01\n    end: 2024-12-31\n"))
    assert p.strategy.start == date(2023, 1, 1)
    assert p.strategy.end == date(2024, 12, 31)


def test_duplicate_strategy_blocks():
    """两个 strategy 块（共享一个 factor 定义）应该报 strategy 重复。"""
    code = (
        "factor s = close\n"
        "strategy {\n"
        "    universe:  cn:sample\n"
        "    signal:    s\n"
        "    select:    top 3\n"
        "    rebalance: weekly\n"
        "}\n"
        "strategy {\n"
        "    universe:  us:sample\n"
        "    signal:    s\n"
        "    select:    top 3\n"
        "    rebalance: weekly\n"
        "}\n"
    )
    with pytest.raises(DSLError, match="strategy 块只能定义一次"):
        parse(code)


# ─── 错误定位 ──────────────────────────────────────────

def test_error_carries_line_col():
    try:
        parse("\nfactor f = delay(close, -1)\n")
    except DSLError as e:
        # 错误应该出现在第 2 行
        assert e.line == 2
        return
    pytest.fail("应该抛 DSLError")


# ─── 程序无 strategy 也能解析（用于单独验证因子）──────

def test_factor_only_program():
    p = parse("factor f = close + 1")
    assert len(p.factors) == 1
    assert p.strategy is None


# ─── factor 之间的依赖 ─────────────────────────────────

def test_factor_chain():
    p = parse(
        "factor a = close\n"
        "factor b = ma(a, 5)\n"
        "factor c = a - b\n"
    )
    assert len(p.factors) == 3
    # b 引用 a
    b_expr = p.factors[1].expr
    assert isinstance(b_expr, Call) and b_expr.op == "ma"
    assert isinstance(b_expr.args[0], FactorRef)
