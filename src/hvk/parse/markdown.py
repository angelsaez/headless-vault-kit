"""Markdown parsing: everything Obsidian derives from a note when it builds its cache.

Frontmatter, properties, tags, aliases, headings, block ids, links, embeds, tasks and
Dataview-style inline fields. This is tier 0 of the plan's three-tier model, and the piece
that has to match the app exactly.

Two approximations are deliberate and documented rather than hidden:

* **Indented code blocks.** Telling a real indented code block from a list continuation line
  needs a full block parser. Here a run of lines indented four spaces or more counts as code
  only when it opens right after a blank line and does not itself look like a list item. That
  covers both cases in ``test-vaults/``: a genuine indented block, and a nested task indented
  under its parent.
* **Obsidian comments.** Text between ``%%`` markers is treated as a comment and produces no
  links, tags or tasks. ADR-0003 lists this as pending confirmation against the app.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field

from ruamel.yaml import YAML, YAMLError

from hvk.parse import tasks as task_fields
from hvk.parse.model import Block, Heading, Parsed, Prop, RawLink, Tag, Task
from hvk.parse.registry import Parser
from ruamel.yaml.constructor import SafeConstructor
from ruamel.yaml.nodes import MappingNode

# The row shapes moved to hvk.parse.model, so a parser written outside this file has somewhere
# to import them from that is not the Markdown parser (ADR-0017). They are re-exported here
# because this is where they lived for five phases and every caller knows it.
__all__ = [
    "PARSER", "Block", "Heading", "Parsed", "ParsedNote", "Prop", "RawLink", "Tag", "Task",
    "parse_file", "parse_note", "split_frontmatter",
]


class _AppLikeConstructor(SafeConstructor):
    """Resolve repeated frontmatter keys the way the app does.

    js-yaml assigns keys in document order, so the last occurrence of a repeated key wins.
    ruamel raises by default and keeps the first when told not to raise, which would either
    discard a whole note's frontmatter or read a different value than the app shows. Neither
    is acceptable for tier 0, so the mapping is built here instead.
    """

    def construct_mapping(self, node, deep: bool = False):
        if not isinstance(node, MappingNode):
            return super().construct_mapping(node, deep=deep)
        self.flatten_mapping(node)
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=True)
            try:
                hash(key)
            except TypeError:
                key = str(key)
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


# ruamel with typ="safe" follows YAML 1.2, which is what Obsidian gets from js-yaml. That is
# the whole reason ADR-0001 pins this dependency instead of using PyYAML.
_yaml = YAML(typ="safe", pure=True)
_yaml.Constructor = _AppLikeConstructor
_yaml.allow_duplicate_keys = True

FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
BLOCK_ID_RE = re.compile(r"(?:^|[ \t])\^([A-Za-z0-9][A-Za-z0-9-]*)[ \t]*$")
CODE_SPAN_RE = re.compile(r"`+[^`]*`+")
WIKILINK_RE = re.compile(r"(!?)\[\[([^\[\]]+?)\]\]")
MDLINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(\s*<?([^)<>\s]*)>?(?:\s+\"[^\"]*\")?\s*\)")
TAG_RE = re.compile(r"(?:(?<=^)|(?<=[\s(\[<>*_~]))#([\w/-]*[^\W\d_][\w/-]*)", re.UNICODE)
QUOTE_PREFIX_RE = re.compile(r"^[ \t]*(?:>[ \t]?)+")
TASK_RE = re.compile(r"^([ \t]*)[-*+][ \t]+\[(.)\][ \t]?(.*)$")
LIST_ITEM_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+")
FIELD_LINE_RE = re.compile(r"^[ \t]*(?:(?:[-*+]|\d+[.)])[ \t]+)?([^\s:][^:\n]*?)::[ \t]*(.*)$")
FIELD_BRACKET_RE = re.compile(r"\[([^\[\]:]+?)::[ \t]*([^\[\]]*)\]")
EXTERNAL_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)")

# Frontmatter keys Obsidian treats specially. Both spellings are accepted, as the app does.
TAG_KEYS = ("tags", "tag")
ALIAS_KEYS = ("aliases", "alias")


@dataclass
class ParsedNote(Parsed):
    """A note: the contract, plus the one thing only a note has.

    ``frontmatter`` is the YAML mapping as it parsed, kept whole. The index stores properties
    row by row and cannot hand that back -- an order-note reads its own state out of it, and a
    base has to tell a key that was absent from one that was empty.
    """

    frontmatter: dict = field(default_factory=dict)


def split_frontmatter(text: str) -> tuple[str | None, str, int]:
    """Split leading YAML frontmatter from the body.

    Returns ``(yaml_text, body, body_start_line)`` where ``body_start_line`` is the 1-based
    line number of the body's first line. Frontmatter only counts when the opening fence is
    on line 1 and a closing fence exists; anything else is body.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text, 1
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:]), i + 2
    return None, text, 1


def _classify(value) -> tuple[str | None, str]:
    """Render a YAML value as text plus a type tag for the ``props`` table."""
    if value is None:
        return None, "null"
    if isinstance(value, bool):
        return ("true" if value else "false"), "bool"
    if isinstance(value, (int, float)):
        return str(value), "number"
    if isinstance(value, _dt.datetime):
        return value.isoformat(), "datetime"
    if isinstance(value, _dt.date):
        return value.isoformat(), "date"
    if isinstance(value, str):
        return value, "string"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str), "map"
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), ensure_ascii=False, default=str), "list"
    return str(value), "string"


def _frontmatter_props(data: dict, line: int) -> list[Prop]:
    props: list[Prop] = []
    for key, value in data.items():
        key = str(key)
        if isinstance(value, (list, tuple)):
            if not value:
                props.append(Prop(key, None, "list", None, False, line))
            for idx, item in enumerate(value):
                text, kind = _classify(item)
                props.append(Prop(key, text, kind, idx, False, line))
        else:
            text, kind = _classify(value)
            props.append(Prop(key, text, kind, None, False, line))
    return props


def _split_tag_values(value) -> list[str]:
    """Frontmatter tags may be a list, or a string separated by spaces or commas."""
    out: list[str] = []
    if isinstance(value, str):
        parts = [p for p in re.split(r"[,\s]+", value) if p]
    elif isinstance(value, (list, tuple)):
        parts = [str(v) for v in value if v is not None]
    else:
        return out
    for part in parts:
        part = str(part).strip().lstrip("#")
        if part:
            out.append(part)
    return out


def _strip_comments(line: str, in_comment: bool) -> tuple[str, bool]:
    """Remove Obsidian ``%% ... %%`` comments, carrying multi-line state across lines."""
    out: list[str] = []
    i = 0
    while True:
        idx = line.find("%%", i)
        if idx == -1:
            if not in_comment:
                out.append(line[i:])
            break
        if in_comment:
            in_comment = False
        else:
            out.append(line[i:idx])
            in_comment = True
        i = idx + 2
    return "".join(out), in_comment


def _blank(match: re.Match) -> str:
    return " " * len(match.group(0))


def _split_subpath(target: str) -> tuple[str, str | None]:
    """Separate a trailing ``#heading`` or ``#^block`` from the link target."""
    idx = target.find("#")
    if idx == -1:
        return target.strip(), None
    return target[:idx].strip(), target[idx:].strip() or None


def parse_note(text: str, *, fallback_title: str = "") -> ParsedNote:
    """Parse the full contents of a Markdown note."""
    note = ParsedNote()
    yaml_text, body, body_start = split_frontmatter(text)
    note.body = body

    if yaml_text is not None:
        try:
            data = _yaml.load(yaml_text) if yaml_text.strip() else None
        except YAMLError as exc:
            note.error = f"frontmatter: {type(exc).__name__}: {exc}".replace("\n", " ")[:500]
            data = None
        if isinstance(data, dict):
            note.frontmatter = data
            note.props.extend(_frontmatter_props(data, 1))
            for key in TAG_KEYS:
                if key in data:
                    for tag in _split_tag_values(data[key]):
                        note.tags.append(Tag(tag, "frontmatter", 1))
        elif data is not None and note.error is None:
            note.error = "frontmatter: top level is not a mapping"

    in_fence: str | None = None
    in_comment = False
    in_indented_code = False
    previous_blank = True

    for offset, raw_line in enumerate(body.split("\n")):
        line_no = body_start + offset
        blank = not raw_line.strip()

        # --- fenced code blocks -------------------------------------------------------
        fence = FENCE_RE.match(raw_line)
        if in_fence is not None:
            if fence and fence.group(1)[0] == in_fence[0] and len(fence.group(1)) >= len(in_fence):
                in_fence = None
            previous_blank = blank
            continue
        if fence:
            in_fence = fence.group(1)
            previous_blank = blank
            continue

        # --- indented code blocks (approximation, see the module docstring) -----------
        indented = raw_line[:4] in ("    ", "\t   ") or raw_line.startswith("\t")
        if in_indented_code:
            if blank or indented:
                previous_blank = blank
                continue
            in_indented_code = False
        elif indented and previous_blank and not LIST_ITEM_RE.match(raw_line):
            in_indented_code = True
            previous_blank = blank
            continue

        previous_blank = blank

        line, in_comment = _strip_comments(raw_line, in_comment)
        if not line.strip():
            continue

        # --- headings -----------------------------------------------------------------
        heading = HEADING_RE.match(line)
        if heading:
            note.headings.append(Heading(len(heading.group(1)), heading.group(2).strip(), line_no))
            continue

        # --- block ids ----------------------------------------------------------------
        block = BLOCK_ID_RE.search(line)
        if block:
            note.blocks.append(Block(block.group(1), line_no))
            line = line[: block.start()]

        # --- tasks --------------------------------------------------------------------
        unquoted = QUOTE_PREFIX_RE.sub("", line)
        task = TASK_RE.match(unquoted)
        if task:
            status = task.group(2)
            clean, extracted = task_fields.extract(task.group(3))
            note.tasks.append(
                Task(
                    clean, status, status in ("x", "X"), line_no,
                    due=extracted.pop("due", None), extra=extracted,
                )
            )

        # --- links, then whatever survives them ---------------------------------------
        work = CODE_SPAN_RE.sub(_blank, line)

        for match in WIKILINK_RE.finditer(work):
            inner = match.group(2)
            target = inner.split("|", 1)[0]
            path, subpath = _split_subpath(target)
            note.links.append(
                RawLink(path, subpath, "wikilink", match.group(1) == "!", line_no)
            )
        work = WIKILINK_RE.sub(_blank, work)

        for match in MDLINK_RE.finditer(work):
            target = match.group(3)
            if not target:
                continue
            if EXTERNAL_RE.match(target):
                note.links.append(RawLink(target, None, "external", match.group(1) == "!", line_no))
                continue
            path, subpath = _split_subpath(target)
            note.links.append(
                RawLink(path, subpath, "markdown", match.group(1) == "!", line_no)
            )
        work = MDLINK_RE.sub(_blank, work)

        for match in TAG_RE.finditer(work):
            note.tags.append(Tag(match.group(1), "inline", line_no))

        # --- Dataview-style inline fields ----------------------------------------------
        for match in FIELD_BRACKET_RE.finditer(work):
            note.props.append(
                Prop(match.group(1).strip(), match.group(2).strip(), "string", None, True, line_no)
            )
        bracketless = FIELD_BRACKET_RE.sub(_blank, work)
        field_line = FIELD_LINE_RE.match(QUOTE_PREFIX_RE.sub("", bracketless))
        if field_line and not TASK_RE.match(QUOTE_PREFIX_RE.sub("", bracketless)):
            key = field_line.group(1).strip()
            if key and "|" not in key:
                note.props.append(
                    Prop(key, field_line.group(2).strip(), "string", None, True, line_no)
                )

    title = note.frontmatter.get("title") if isinstance(note.frontmatter, dict) else None
    if isinstance(title, str) and title.strip():
        note.title = title.strip()
    else:
        h1 = next((h.text for h in note.headings if h.level == 1), None)
        note.title = h1 or fallback_title

    return note


def parse_file(text: str, path: str) -> ParsedNote:
    """The registry's entry point: parse one Markdown file, given its vault-relative path.

    ``parse_note`` takes a fallback title because it is also used on fragments -- the Markdown
    written inside a canvas box, which has no file of its own. This is the file-shaped wrapper,
    and the title it falls back to is the note's own name, which is what the app shows when a
    note has neither an H1 nor a ``title``.
    """
    return parse_note(text, fallback_title=path.rsplit("/", 1)[-1].removesuffix(".md"))


PARSER = Parser(name="markdown", extensions=("md",), kind="note", parse=parse_file)
