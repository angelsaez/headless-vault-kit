"""Obsidian Bases: reading ``.base`` files and running their views against the index.

Tier 1 of the plan's three-tier model — an official Obsidian format with published syntax, so
this parses the format rather than emulating anything. ADR-0005 fixes which part of the
expression language is supported and what happens to the rest.
"""

from hvk.bases.evaluate import Context, evaluate_source
from hvk.bases.expr import ExpressionError, parse
from hvk.bases.values import File, Link

__all__ = ["Context", "ExpressionError", "File", "Link", "evaluate_source", "parse"]
