"""Parsing Bases expressions: precedence, chaining and the errors."""

from __future__ import annotations

import pytest

from hvk.bases.expr import (
    Binary,
    Call,
    ExpressionError,
    Index,
    ListLiteral,
    Literal,
    Member,
    Name,
    Unary,
    parse,
    tokenize,
)


def test_literals():
    assert parse("42") == Literal(42)
    assert parse("3.5") == Literal(3.5)
    assert parse('"text"') == Literal("text")
    assert parse("'text'") == Literal("text")
    assert parse("true") == Literal(True)
    assert parse("null") == Literal(None)


def test_a_bare_name_is_a_property_reference():
    assert parse("status") == Name("status")
    assert parse("kebab-case-name") == Name("kebab-case-name")


def test_arithmetic_binds_tighter_than_comparison():
    assert parse("a + b > c") == Binary(">", Binary("+", Name("a"), Name("b")), Name("c"))


def test_multiplication_binds_tighter_than_addition():
    assert parse("a + b * c") == Binary("+", Name("a"), Binary("*", Name("b"), Name("c")))


def test_comparison_binds_tighter_than_and():
    assert parse("a > 1 && b < 2") == Binary(
        "&&", Binary(">", Name("a"), Literal(1)), Binary("<", Name("b"), Literal(2))
    )


def test_and_binds_tighter_than_or():
    tree = parse("a && b || c")
    assert tree.operator == "||"
    assert tree.left.operator == "&&"


def test_word_operators_are_the_same_as_symbols():
    assert parse("a and b or not c") == parse("a && b || !c")


def test_parentheses_override_precedence():
    assert parse("(a + b) * c") == Binary("*", Binary("+", Name("a"), Name("b")), Name("c"))


def test_method_chaining_on_a_parenthesised_expression():
    """Straight from the official example: (price / age).toFixed(2)."""
    tree = parse("(price / age).toFixed(2)")
    assert isinstance(tree, Call)
    assert tree.callee.name == "toFixed"
    assert tree.callee.target == Binary("/", Name("price"), Name("age"))


def test_nested_calls_and_concatenation():
    """The other official example: if(price, price.toFixed(2) + " dollars")."""
    tree = parse('if(price, price.toFixed(2) + " dollars")')
    assert isinstance(tree, Call) and tree.callee == Name("if")
    assert len(tree.arguments) == 2
    assert tree.arguments[1].operator == "+"


def test_dotted_paths():
    assert parse("file.name") == Member(Name("file"), "name")
    assert parse("this.file.folder") == Member(Member(Name("this"), "file"), "folder")


def test_calls_with_no_arguments():
    assert parse("today()") == Call(Name("today"), ())


def test_calls_with_several_arguments():
    tree = parse('file.hasTag("a", "b", "c")')
    assert len(tree.arguments) == 3


def test_list_literals_and_indexing():
    assert parse("[1, 2]") == ListLiteral((Literal(1), Literal(2)))
    assert parse("tags[0]") == Index(Name("tags"), Literal(0))
    assert parse("[]") == ListLiteral(())


def test_unary_operators():
    assert parse("!done") == Unary("!", Name("done"))
    assert parse("-price") == Unary("-", Name("price"))


def test_escaped_quotes_inside_strings():
    assert parse(r'"say \"hi\""') == Literal('say "hi"')


def test_strings_may_contain_the_other_quote():
    assert parse("\"it's fine\"") == Literal("it's fine")


@pytest.mark.parametrize(
    "source, message",
    [
        ('"unterminated', "unterminated string"),
        ("a $ b", "unexpected character"),
        ("a +", "unexpected"),
        ("(a", r"expected '\)'"),
        ("f(a b)", "expected ','"),
        ("a.", "expected a property name"),
        ("", "empty expression"),
        ("   ", "empty expression"),
    ],
)
def test_errors_say_what_and_where(source, message):
    with pytest.raises(ExpressionError, match=message):
        parse(source)


def test_two_character_operators_are_not_split():
    kinds = [(t.kind, t.value) for t in tokenize("a >= b != c")]
    assert ("op", ">=") in kinds and ("op", "!=") in kinds


def test_the_full_official_filter_parses():
    for source in (
        'file.hasTag("tag")',
        'file.hasLink("Textbook")',
        'file.inFolder("Required Reading")',
        'status != "done"',
        "formula.ppu > 5",
        "price > 2.1",
    ):
        parse(source)
