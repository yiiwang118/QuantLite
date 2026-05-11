"""DSL 词法分析器。

把源文本切成 token 流。带行列号方便错误定位。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto

from app.dsl.ast_nodes import DSLError


class TokType(Enum):
    IDENT = auto()       # 标识符 / 关键字（factor / strategy / top）
    NUMBER = auto()      # 整数或小数
    DATE = auto()        # YYYY-MM-DD
    LBRACE = auto()      # {
    RBRACE = auto()      # }
    LPAREN = auto()      # (
    RPAREN = auto()      # )
    COMMA = auto()       # ,
    COLON = auto()       # :
    ASSIGN = auto()      # =
    PLUS = auto()        # +
    MINUS = auto()       # -
    STAR = auto()        # *
    SLASH = auto()       # /
    EOF = auto()         # 文件结束


@dataclass(frozen=True)
class Token:
    type: TokType
    value: str
    line: int
    col: int

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, L{self.line}:{self.col})"


_SIMPLE_TOKENS: dict[str, TokType] = {
    "{": TokType.LBRACE,
    "}": TokType.RBRACE,
    "(": TokType.LPAREN,
    ")": TokType.RPAREN,
    ",": TokType.COMMA,
    ":": TokType.COLON,
    "=": TokType.ASSIGN,
    "+": TokType.PLUS,
    "-": TokType.MINUS,
    "*": TokType.STAR,
    "/": TokType.SLASH,
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def tokenize(src: str) -> list[Token]:
    """把源代码切成 Token 列表（末尾带 EOF）。"""
    tokens: list[Token] = []
    line, col = 1, 1
    i, n = 0, len(src)

    while i < n:
        ch = src[i]

        # 换行
        if ch == "\n":
            line += 1
            col = 1
            i += 1
            continue

        # 空白
        if ch in " \t\r":
            col += 1
            i += 1
            continue

        # 行注释：# ... 直到行尾
        if ch == "#":
            while i < n and src[i] != "\n":
                i += 1
            continue

        # 标识符 / 关键字
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            tokens.append(Token(TokType.IDENT, src[i:j], line, col))
            col += j - i
            i = j
            continue

        # 数字 / 日期
        if ch.isdigit():
            # 先尝试匹配 DATE（YYYY-MM-DD，固定 10 字符）
            if i + 10 <= n and _DATE_RE.match(src[i:i+10]):
                tokens.append(Token(TokType.DATE, src[i:i+10], line, col))
                col += 10
                i += 10
                continue
            # 否则是 NUMBER
            j = i
            seen_dot = False
            while j < n and (src[j].isdigit() or (src[j] == "." and not seen_dot)):
                if src[j] == ".":
                    seen_dot = True
                j += 1
            tokens.append(Token(TokType.NUMBER, src[i:j], line, col))
            col += j - i
            i = j
            continue

        # 单字符 token
        if ch in _SIMPLE_TOKENS:
            tokens.append(Token(_SIMPLE_TOKENS[ch], ch, line, col))
            i += 1
            col += 1
            continue

        # 未知字符
        raise DSLError(f"未识别字符: {ch!r}", line, col)

    tokens.append(Token(TokType.EOF, "", line, col))
    return tokens
