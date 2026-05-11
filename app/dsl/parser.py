"""DSL 递归下降解析器。

文法（非正式 EBNF）：

    program     := (factor_def | strategy)*
    factor_def  := "factor" IDENT "=" expr
    strategy    := "strategy" "{" strategy_field+ "}"

    strategy_field :=
        | "universe"  ":" universe_value
        | "signal"    ":" IDENT
        | "select"    ":" "top" NUMBER
        | "rebalance" ":" IDENT
        | "start"     ":" DATE
        | "end"       ":" DATE

    universe_value := IDENT (":" IDENT)?      # "cn:sample" or "sample"

    expr   := term  (("+" | "-") term)*       # 优先级最低
    term   := unary (("*" | "/") unary)*
    unary  := "-" unary | primary
    primary :=
        | NUMBER
        | "(" expr ")"
        | IDENT                                # 字段 / factor 引用
        | IDENT "(" args? ")"                  # 算子调用
    args   := expr ("," expr)*

静态检查（解析期一并完成）：
- 算子在 OPERATORS 白名单
- 算子参数数量正确
- 窗口型算子的第二个参数是非负整数常量 ← **防前视偏差**
- 字段在 FIELDS 白名单
- factor 名字不重复 / 不和保留字冲突
- factor 引用必须先定义后使用
- strategy 必需字段都给了，signal 必须是已定义 factor
"""
from __future__ import annotations

from datetime import date as date_t
from typing import Any

from app.dsl import whitelist as wl
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
from app.dsl.lexer import Token, TokType, tokenize


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0
        self.factor_names: set[str] = set()

    # ─── 通用 token 操作 ─────────────────────────────────────

    def peek(self, offset: int = 0) -> Token:
        return self.tokens[self.pos + offset]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, type_: TokType, msg: str | None = None) -> Token:
        tok = self.peek()
        if tok.type != type_:
            raise DSLError(
                msg or f"期望 {type_.name}，实际 {tok.type.name} ({tok.value!r})",
                tok.line, tok.col,
            )
        return self.advance()

    def expect_ident(self, value: str) -> Token:
        tok = self.peek()
        if tok.type != TokType.IDENT or tok.value != value:
            raise DSLError(
                f"期望关键字 {value!r}，实际 {tok.value!r}",
                tok.line, tok.col,
            )
        return self.advance()

    # ─── 顶层 ───────────────────────────────────────────────

    def parse_program(self) -> Program:
        factors: list[FactorDef] = []
        strategy: Strategy | None = None
        while self.peek().type != TokType.EOF:
            tok = self.peek()
            if tok.type == TokType.IDENT and tok.value == "factor":
                factors.append(self.parse_factor_def())
            elif tok.type == TokType.IDENT and tok.value == "strategy":
                if strategy is not None:
                    raise DSLError("strategy 块只能定义一次", tok.line, tok.col)
                strategy = self.parse_strategy()
            else:
                raise DSLError(
                    f"期望 'factor' 或 'strategy' 开头，实际 {tok.value!r}",
                    tok.line, tok.col,
                )
        return Program(factors=tuple(factors), strategy=strategy)

    def parse_factor_def(self) -> FactorDef:
        kw = self.expect_ident("factor")
        name_tok = self.expect(TokType.IDENT, "factor 名后期望标识符")
        name = name_tok.value
        if wl.is_reserved(name):
            raise DSLError(
                f"factor 名 {name!r} 与字段 / 算子 / 关键字冲突",
                name_tok.line, name_tok.col,
            )
        if name in self.factor_names:
            raise DSLError(
                f"factor {name!r} 重复定义",
                name_tok.line, name_tok.col,
            )
        self.expect(TokType.ASSIGN, "factor 名后期望 '='")
        expr = self.parse_expr()
        self.factor_names.add(name)
        return FactorDef(name=name, expr=expr, line=kw.line, col=kw.col)

    # ─── 表达式（优先级爬升）─────────────────────────────────

    def parse_expr(self) -> Expr:
        left = self.parse_term()
        while self.peek().type in (TokType.PLUS, TokType.MINUS):
            op_tok = self.advance()
            right = self.parse_term()
            left = BinOp(op=op_tok.value, left=left, right=right,
                         line=op_tok.line, col=op_tok.col)
        return left

    def parse_term(self) -> Expr:
        left = self.parse_unary()
        while self.peek().type in (TokType.STAR, TokType.SLASH):
            op_tok = self.advance()
            right = self.parse_unary()
            left = BinOp(op=op_tok.value, left=left, right=right,
                         line=op_tok.line, col=op_tok.col)
        return left

    def parse_unary(self) -> Expr:
        if self.peek().type == TokType.MINUS:
            tok = self.advance()
            operand = self.parse_unary()
            return UnaryOp(op="-", operand=operand, line=tok.line, col=tok.col)
        return self.parse_primary()

    def parse_primary(self) -> Expr:
        tok = self.peek()

        if tok.type == TokType.NUMBER:
            self.advance()
            return Number(value=float(tok.value), line=tok.line, col=tok.col)

        if tok.type == TokType.LPAREN:
            self.advance()
            expr = self.parse_expr()
            self.expect(TokType.RPAREN, "缺少右括号 ')'")
            return expr

        if tok.type == TokType.IDENT:
            name = self.advance().value
            # 算子调用？
            if self.peek().type == TokType.LPAREN:
                self.advance()  # consume (
                args: list[Expr] = []
                if self.peek().type != TokType.RPAREN:
                    args.append(self.parse_expr())
                    while self.peek().type == TokType.COMMA:
                        self.advance()
                        args.append(self.parse_expr())
                self.expect(TokType.RPAREN, "缺少右括号 ')'")
                self._validate_call(name, args, tok.line, tok.col)
                return Call(op=name, args=tuple(args), line=tok.line, col=tok.col)

            # 字段引用
            if name in wl.FIELDS:
                return Field(name=name, line=tok.line, col=tok.col)
            # factor 引用
            if name in self.factor_names:
                return FactorRef(name=name, line=tok.line, col=tok.col)
            # 都不是
            raise DSLError(
                f"未定义的标识符 {name!r}（不是字段、不是已定义的 factor）",
                tok.line, tok.col,
            )

        raise DSLError(
            f"无法解析的 token: {tok.type.name}={tok.value!r}",
            tok.line, tok.col,
        )

    def _validate_call(self, op: str, args: list[Expr], line: int, col: int) -> None:
        if op not in wl.OPERATORS:
            raise DSLError(f"未知算子 {op!r}", line, col)

        expected = wl.OPERATOR_ARITY[op]
        if len(args) != expected:
            raise DSLError(
                f"算子 {op!r} 需要 {expected} 个参数，实际 {len(args)} 个",
                line, col,
            )

        if op in wl.WINDOW_OPS:
            window_pos = wl.WINDOW_OPS[op]
            window = args[window_pos]
            # 展开一元负号：delay(x, -1) 词法上是 UnaryOp(-, Number(1))
            if isinstance(window, UnaryOp) and window.op == "-" and isinstance(window.operand, Number):
                value = -window.operand.value
                w_line, w_col = window.line, window.col
            elif isinstance(window, Number):
                value = window.value
                w_line, w_col = window.line, window.col
            else:
                raise DSLError(
                    f"算子 {op!r} 的窗口参数必须是常量，"
                    f"实际是 {type(window).__name__}",
                    line, col,
                )
            if value < 0 or value != int(value):
                raise DSLError(
                    f"算子 {op!r} 的窗口必须是非负整数（防前视偏差），实际给了 {value}",
                    w_line, w_col,
                )

    # ─── 策略块 ─────────────────────────────────────────────

    def parse_strategy(self) -> Strategy:
        kw = self.expect_ident("strategy")
        self.expect(TokType.LBRACE, "strategy 后期望 '{'")
        fields: dict[str, Any] = {}

        while self.peek().type != TokType.RBRACE:
            if self.peek().type == TokType.EOF:
                raise DSLError("strategy 块未闭合（缺少 '}'）", kw.line, kw.col)
            key_tok = self.expect(TokType.IDENT, "策略字段名期望标识符")
            key = key_tok.value
            if key not in wl.STRATEGY_FIELDS:
                raise DSLError(
                    f"未知策略字段 {key!r}（允许：{sorted(wl.STRATEGY_FIELDS)}）",
                    key_tok.line, key_tok.col,
                )
            if key in fields:
                raise DSLError(
                    f"策略字段 {key!r} 重复定义",
                    key_tok.line, key_tok.col,
                )
            self.expect(TokType.COLON, f"字段 {key!r} 后期望 ':'")
            fields[key] = self._parse_strategy_value(key)

        self.expect(TokType.RBRACE)

        # 校验必需字段
        for req in wl.STRATEGY_REQUIRED:
            if req not in fields:
                raise DSLError(
                    f"策略缺少必需字段 {req!r}",
                    kw.line, kw.col,
                )

        # signal 必须是已定义 factor
        signal = fields["signal"]
        if signal not in self.factor_names:
            raise DSLError(
                f"signal {signal!r} 必须是已定义的 factor",
                kw.line, kw.col,
            )

        # select 解析后返回 (top_n, bottom_n) tuple
        top_n, bottom_n = fields["select"]
        return Strategy(
            universe=fields["universe"],
            signal=signal,
            top_n=top_n,
            bottom_n=bottom_n,
            rebalance=fields["rebalance"],
            cost=fields.get("cost", 0.0),
            start=fields.get("start"),
            end=fields.get("end"),
            line=kw.line,
            col=kw.col,
        )

    def _parse_strategy_value(self, key: str) -> Any:
        tok = self.peek()
        if key == "universe":
            # IDENT 或 IDENT ':' IDENT
            ns_tok = self.expect(TokType.IDENT, "universe 期望标识符")
            if self.peek().type == TokType.COLON:
                self.advance()
                name_tok = self.expect(TokType.IDENT,
                                       f"universe '{ns_tok.value}:' 后期望名字")
                return f"{ns_tok.value}:{name_tok.value}"
            return ns_tok.value

        if key == "signal":
            return self.expect(TokType.IDENT, "signal 期望 factor 名").value

        if key == "select":
            # "top" NUMBER ("bottom" NUMBER)?
            #   long-only:   top 3
            #   long-short:  top 3 bottom 3
            self.expect_ident("top")
            top_tok = self.expect(TokType.NUMBER, "select: top 后期望数字")
            try:
                top_n = int(float(top_tok.value))
            except ValueError:
                raise DSLError(f"无法解析数字 {top_tok.value!r}",
                               top_tok.line, top_tok.col)
            if top_n <= 0 or float(top_tok.value) != top_n:
                raise DSLError(
                    f"select: top N 中 N 必须是正整数，实际 {top_tok.value}",
                    top_tok.line, top_tok.col,
                )
            bottom_n = 0
            nxt = self.peek()
            if nxt.type == TokType.IDENT and nxt.value == "bottom":
                self.advance()
                bot_tok = self.expect(TokType.NUMBER, "select: bottom 后期望数字")
                try:
                    bottom_n = int(float(bot_tok.value))
                except ValueError:
                    raise DSLError(f"无法解析数字 {bot_tok.value!r}",
                                   bot_tok.line, bot_tok.col)
                if bottom_n <= 0 or float(bot_tok.value) != bottom_n:
                    raise DSLError(
                        f"select: bottom M 中 M 必须是正整数，实际 {bot_tok.value}",
                        bot_tok.line, bot_tok.col,
                    )
            return (top_n, bottom_n)

        if key == "cost":
            # 单边交易成本：0 <= cost < 0.5（半个百分点以上明显不合理）
            c_tok = self.expect(TokType.NUMBER, "cost 期望数字（如 0.001 = 10 bps）")
            try:
                c = float(c_tok.value)
            except ValueError:
                raise DSLError(f"无法解析数字 {c_tok.value!r}",
                               c_tok.line, c_tok.col)
            if c < 0 or c >= 0.5:
                raise DSLError(
                    f"cost 必须在 [0, 0.5) 范围内（推荐 0.0005 ~ 0.002），实际 {c}",
                    c_tok.line, c_tok.col,
                )
            return c

        if key == "rebalance":
            v_tok = self.expect(TokType.IDENT, "rebalance 期望标识符")
            if v_tok.value not in wl.REBALANCE_FREQS:
                raise DSLError(
                    f"rebalance 必须是 {sorted(wl.REBALANCE_FREQS)}，"
                    f"实际 {v_tok.value!r}",
                    v_tok.line, v_tok.col,
                )
            return v_tok.value

        if key in ("start", "end"):
            d_tok = self.expect(TokType.DATE, f"{key} 期望 YYYY-MM-DD 日期")
            try:
                return date_t.fromisoformat(d_tok.value)
            except ValueError as e:
                raise DSLError(f"非法日期 {d_tok.value!r}: {e}",
                               d_tok.line, d_tok.col)

        raise DSLError(f"内部错误：未实现字段 {key!r}", tok.line, tok.col)


def parse(src: str) -> Program:
    """对外入口：DSL 文本 → AST。"""
    tokens = tokenize(src)
    return Parser(tokens).parse_program()
