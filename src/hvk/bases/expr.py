"""Parsing Bases expressions into a tree.

A filter or formula in a ``.base`` file is a small expression language, not a pattern to match
against: ``if(price, price.toFixed(2) + " dollars")`` has literals, a call, a method chain and
an operator. So this is a real tokeniser and a Pratt parser, which is both shorter and far more
honest than regular expressions would be, and gives phase 4's Dataview subset something to
build on.

Parsing is separate from evaluation on purpose. A parse error can then name the column it
happened at, and :mod:`hvk.bases.eval` can be tested against trees rather than strings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Longest first, so that '>=' never tokenises as '>' followed by '='.
OPERATORS = (
    "&&", "||", "==", "!=", ">=", "<=",
    ">", "<", "+", "-", "*", "/", "%", "!", ".", ",", "(", ")", "[", "]",
)

WORD_OPERATORS = {"and": "&&", "or": "||", "not": "!"}
KEYWORDS = {"true": True, "false": False, "null": None}

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")

# Binding power per infix operator. Higher binds tighter.
PRECEDENCE = {
    "||": 1, "&&": 2,
    "==": 3, "!=": 3,
    "<": 4, "<=": 4, ">": 4, ">=": 4,
    "+": 5, "-": 5,
    "*": 6, "/": 6, "%": 6,
}
UNARY_PRECEDENCE = 7
POSTFIX_PRECEDENCE = 8


class ExpressionError(Exception):
    """Raised for anything the expression language cannot represent or evaluate."""


@dataclass(frozen=True)
class Token:
    kind: str      # 'number' | 'string' | 'name' | 'op' | 'end'
    value: object
    column: int


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(source)
    while i < n:
        char = source[i]
        if char.isspace():
            i += 1
            continue
        if char in "\"'":
            closing = source.find(char, i + 1)
            while closing != -1 and source[closing - 1] == "\\":
                closing = source.find(char, closing + 1)
            if closing == -1:
                raise ExpressionError(f"unterminated string at column {i + 1}")
            raw = source[i + 1:closing].replace("\\" + char, char).replace("\\\\", "\\")
            tokens.append(Token("string", raw, i))
            i = closing + 1
            continue
        number = NUMBER_RE.match(source, i)
        if number and (char.isdigit()):
            text = number.group(0)
            tokens.append(Token("number", float(text) if "." in text else int(text), i))
            i = number.end()
            continue
        name = NAME_RE.match(source, i)
        if name:
            word = name.group(0)
            if word in WORD_OPERATORS:
                tokens.append(Token("op", WORD_OPERATORS[word], i))
            elif word in KEYWORDS:
                tokens.append(Token("keyword", KEYWORDS[word], i))
            else:
                tokens.append(Token("name", word, i))
            i = name.end()
            continue
        for operator in OPERATORS:
            if source.startswith(operator, i):
                tokens.append(Token("op", operator, i))
                i += len(operator)
                break
        else:
            raise ExpressionError(f"unexpected character {char!r} at column {i + 1}")
    tokens.append(Token("end", None, n))
    return tokens


# -- the tree ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Literal:
    value: object


@dataclass(frozen=True)
class Name:
    identifier: str


@dataclass(frozen=True)
class Member:
    target: object
    name: str


@dataclass(frozen=True)
class Index:
    target: object
    key: object


@dataclass(frozen=True)
class ListLiteral:
    elements: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class Call:
    callee: object
    arguments: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class Unary:
    operator: str
    operand: object


@dataclass(frozen=True)
class Binary:
    operator: str
    left: object
    right: object


class _Parser:
    def __init__(self, tokens: list[Token], source: str):
        self.tokens = tokens
        self.source = source
        self.position = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.position]

    def advance(self) -> Token:
        token = self.current
        self.position += 1
        return token

    def expect(self, operator: str) -> None:
        token = self.current
        if token.kind != "op" or token.value != operator:
            raise ExpressionError(
                f"expected {operator!r} at column {token.column + 1} of {self.source!r}"
            )
        self.position += 1

    def parse(self) -> object:
        tree = self.expression(0)
        if self.current.kind != "end":
            raise ExpressionError(
                f"unexpected {self.current.value!r} at column {self.current.column + 1} "
                f"of {self.source!r}"
            )
        return tree

    def expression(self, minimum: int) -> object:
        left = self.prefix()
        while True:
            token = self.current
            if token.kind != "op":
                break
            if token.value in (".", "(", "["):
                left = self.postfix(left)
                continue
            power = PRECEDENCE.get(token.value)
            if power is None or power < minimum:
                break
            self.advance()
            right = self.expression(power + 1)
            left = Binary(token.value, left, right)
        return left

    def prefix(self) -> object:
        token = self.advance()
        if token.kind in ("number", "string"):
            return Literal(token.value)
        if token.kind == "keyword":
            return Literal(token.value)
        if token.kind == "name":
            return Name(token.value)
        if token.kind == "op":
            if token.value in ("!", "-"):
                return Unary(token.value, self.expression(UNARY_PRECEDENCE))
            if token.value == "(":
                inner = self.expression(0)
                self.expect(")")
                return inner
            if token.value == "[":
                return ListLiteral(self.arguments("]"))
        raise ExpressionError(
            f"unexpected {token.value!r} at column {token.column + 1} of {self.source!r}"
        )

    def postfix(self, left: object) -> object:
        token = self.advance()
        if token.value == ".":
            name = self.advance()
            if name.kind != "name":
                raise ExpressionError(
                    f"expected a property name after '.' at column {name.column + 1}"
                )
            return Member(left, name.value)
        if token.value == "(":
            return Call(left, self.arguments(")"))
        key = self.expression(0)
        self.expect("]")
        return Index(left, key)

    def arguments(self, closing: str) -> tuple:
        """Parse a comma-separated list up to *closing*, which is consumed."""
        if self.current.kind == "op" and self.current.value == closing:
            self.advance()
            return ()
        collected = []
        while True:
            collected.append(self.expression(0))
            token = self.advance()
            if token.kind == "op" and token.value == closing:
                return tuple(collected)
            if not (token.kind == "op" and token.value == ","):
                raise ExpressionError(
                    f"expected ',' or {closing!r} at column {token.column + 1} "
                    f"of {self.source!r}"
                )


def parse(source: str) -> object:
    """Parse one Bases expression into a tree."""
    if not source or not source.strip():
        raise ExpressionError("empty expression")
    return _Parser(tokenize(source), source).parse()
