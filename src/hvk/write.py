"""The only way anything in this project writes to a vault (ADR-0007).

Until phase 4 every line of code here only read, which meant a bug could produce a wrong
answer but never destroy anything. That is no longer true, so every write goes through this
module and obeys the same rules: atomic replacement, no write at all when nothing changed,
refusal when the file moved underneath, and the file's own line endings, final newline and
byte-order mark preserved exactly.

Frontmatter survives because it is never parsed here. Editing a note edits its text; the YAML
is never reserialised, so key order, comments and quoting stay as the author wrote them.

The generated-block helpers at the bottom take their markers as arguments. What a block is
called belongs to the feature that generates it, not to the machinery that splices it in.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

BOM = "﻿"
TRASH_DIR = ".trash"
# A dotfile, so the exclusion rules of ADR-0002 already keep the watcher and the index from
# ever seeing it during the instant it exists.
TEMP_PREFIX = ".hvk-tmp-"


class WriteError(Exception):
    """Raised when a write cannot be made safely. Never raised for 'nothing to do'."""


class ConflictError(WriteError):
    """The file changed since it was read. The caller should re-read and decide again."""


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Original:
    """A file as it was read, and everything a round trip would otherwise destroy.

    It carries its own resolved path, so a write cannot land somewhere other than where the
    content came from -- and so the check that the path is inside the vault, already made
    when reading, cannot be skipped when writing.
    """

    path: Path
    text: str                  # decoded, newlines as \n, without BOM or final newline
    newline: str = "\n"
    final_newline: bool = True
    bom: bool = False
    digest: str | None = None  # sha256 of the bytes on disk; None when the file was absent
    mixed_newlines: bool = False

    @property
    def exists(self) -> bool:
        return self.digest is not None

    def rendered(self, text: str) -> bytes:
        """Turn edited text back into bytes shaped like the file it came from."""
        body = text
        if self.final_newline and not body.endswith("\n"):
            body += "\n"
        elif not self.final_newline and body.endswith("\n"):
            body = body[:-1]
        if self.newline != "\n":
            body = body.replace("\n", self.newline)
        if self.bom:
            body = BOM + body
        return body.encode("utf-8")


@dataclass(frozen=True)
class Vault:
    """A vault, opened for writing.

    Every path goes through :meth:`resolve` first. That check lives here, on the object you
    need in order to write at all, for the same reason the index-inside-the-vault check lives
    on ``paths.Locations``: a safety rule that can be reached around is not a safety rule.
    """

    root: Path

    def __post_init__(self) -> None:
        root = Path(self.root).expanduser().resolve()
        if not root.is_dir():
            raise WriteError(f"vault path is not a directory: {root}")
        object.__setattr__(self, "root", root)

    def resolve(self, target: Path | str, *, allow_hidden: bool = False) -> Path:
        """Resolve *target* inside the vault, refusing anything that escapes it.

        The path itself is resolved, not just its parent: a symlink pointing outside is the
        interesting case, and a *broken* symlink pointing outside is the one that a check on
        the parent directory would wave through and then follow on open().
        """
        candidate = Path(target).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        try:
            resolved = candidate.resolve()
        except OSError as exc:                       # pragma: no cover - platform-specific
            raise WriteError(f"cannot resolve {target}: {exc}") from exc

        if not resolved.is_relative_to(self.root):
            raise WriteError(
                f"refusing to touch {target}: it resolves to {resolved}, outside the vault at "
                f"{self.root}. Vault content is untrusted input, and a path that escapes the "
                f"vault is the shape a prompt injection would take."
            )
        if resolved == self.root:
            raise WriteError(f"refusing to touch the vault root itself ({self.root})")

        relative = resolved.relative_to(self.root)
        if not allow_hidden and any(part.startswith(".") for part in relative.parts):
            raise WriteError(
                f"refusing to touch {relative.as_posix()}: this module writes notes, not the "
                f"hidden files around them. Nothing under a dot path -- .obsidian, .git, "
                f".trash -- is written by hvk."
            )
        return resolved

    def read(self, target: Path | str) -> Original:
        """Read a file, remembering everything a round trip would otherwise destroy.

        A file that is not there is not an error: it comes back with ``digest=None``, which
        is how "create it, but only if it is still absent" is expressed.
        """
        path = self.resolve(target)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return Original(path=path, text="")
        except OSError as exc:
            raise WriteError(f"cannot read {path}: {exc}") from exc

        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WriteError(
                f"{path} is not valid UTF-8 ({exc.reason} at byte {exc.start}). Refusing to "
                f"rewrite a file this project cannot read: repairing it would be guessing."
            ) from exc

        bom = decoded.startswith(BOM)
        if bom:
            decoded = decoded[len(BOM):]

        crlf = decoded.count("\r\n")
        lf = decoded.count("\n") - crlf
        text = decoded.replace("\r\n", "\n")
        final_newline = text.endswith("\n")
        if final_newline:
            text = text[:-1]

        return Original(
            path=path,
            text=text,
            newline="\r\n" if crlf > lf else "\n",
            final_newline=final_newline,
            bom=bom,
            digest=digest_bytes(raw),
            mixed_newlines=crlf > 0 and lf > 0,
        )

    def write(self, original: Original, text: str) -> bool:
        """Write *text* where *original* came from. True when the file actually changed.

        The write is refused if the file no longer matches the digest recorded in *original*:
        sync delivering an edit from a phone mid-operation is normal, and overwriting it
        would be the one unrecoverable mistake this module exists to prevent.
        """
        path = self.resolve(original.path)
        data = original.rendered(text)

        try:
            current: bytes | None = path.read_bytes()
        except FileNotFoundError:
            current = None
        except OSError as exc:
            raise WriteError(f"cannot read {path}: {exc}") from exc

        actual = digest_bytes(current) if current is not None else None
        if actual != original.digest:
            if original.digest is None:
                detail = "it exists now, and did not when it was read"
            elif actual is None:
                detail = "it has been deleted since it was read"
            else:
                detail = "its contents changed since it was read"
            raise ConflictError(
                f"{path}: {detail}. Nothing was written. Read it again and decide with the "
                f"new content."
            )

        # Nothing changed: do not open the file, do not touch its mtime. This is not an
        # optimisation -- it is what keeps a view regenerated every half hour from waking the
        # watcher and sync every half hour, on every device (ADR-0007).
        if current == data:
            return False

        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=TEMP_PREFIX, dir=str(path.parent))
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            raise WriteError(f"cannot write {path}: {exc}") from exc
        finally:
            # After a successful replace there is nothing left to remove; after a failure
            # there is, and leaving it behind would litter the vault with dotfiles.
            if os.path.exists(temporary):
                os.unlink(temporary)
        return True

    def trash(self, target: Path | str) -> Path:
        """Move a file to the vault's ``.trash/``, keeping its path relative to the vault.

        Nothing in this project unlinks a vault file. Keeping the relative path rather than
        flattening means two notes with the same name in different folders do not collide,
        and what was removed says where it came from.
        """
        path = self.resolve(target)
        if not path.is_file():
            raise WriteError(f"cannot trash {path}: it is not a file")

        relative = path.relative_to(self.root)
        destination = self.resolve(Path(TRASH_DIR) / relative, allow_hidden=True)
        if destination.exists():
            # Two removals of the same note in the same second are unlikely, and still must
            # not overwrite each other.
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            base, suffix = destination.stem, destination.suffix
            destination = destination.with_name(f"{base} {stamp}{suffix}")
            attempt = 2
            while destination.exists():
                destination = destination.with_name(f"{base} {stamp} {attempt}{suffix}")
                attempt += 1

        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(path, destination)
        except OSError as exc:
            raise WriteError(f"cannot move {path} to the trash: {exc}") from exc
        return destination


# -- generated blocks ---------------------------------------------------------------------

@dataclass(frozen=True)
class Block:
    """A region between two markers, and where in the text it was found."""

    open: str
    close: str
    body: str
    start: int          # offset of the first character of the opening marker
    end: int            # offset just past the last character of the closing marker
    indent: str = ""    # whitespace the closing marker sits behind on its own line


def find_blocks(text: str, start_marker: str, end_marker: str) -> list[Block]:
    """Every ``start_marker`` .. ``end_marker`` region in *text*, in the order they appear.

    An opening marker with no closing one is an error rather than an invitation to treat the
    rest of the file as generated content. So is a second opening marker before the first has
    closed: a nested block is a hand-edit gone wrong, and guessing which one to replace is
    how a note loses a paragraph.
    """
    blocks: list[Block] = []
    position = 0
    while True:
        start = text.find(start_marker, position)
        if start < 0:
            return blocks
        body_start = start + len(start_marker)
        close = text.find(end_marker, body_start)
        if close < 0:
            raise WriteError(
                f"found {start_marker!r} with no matching {end_marker!r}. Refusing to guess "
                f"where the generated block ends: the rest of the file is not ours to replace."
            )
        nested = text.find(start_marker, body_start)
        if 0 <= nested < close:
            raise WriteError(
                f"found {start_marker!r} again before the first one was closed with "
                f"{end_marker!r}. Refusing to replace either: fix the markers by hand."
            )
        # Whitespace the closing marker sits behind belongs to the marker's own line, not to
        # the generated body. Without this, replacing the body of a block nested in a list
        # would quietly unindent the closing marker -- a line the generator never wrote.
        line_start = text.rfind("\n", body_start, close) + 1
        indent = text[line_start:close] if text[line_start:close].strip() == "" else ""

        end = close + len(end_marker)
        blocks.append(
            Block(open=start_marker, close=end_marker, body=text[body_start:close - len(indent)],
                  start=start, end=end, indent=indent)
        )
        position = end


def replace_block(text: str, block: Block, body: str) -> str:
    """Return *text* with the body of *block* replaced, and nothing else touched.

    Idempotent by construction: replacing a block with what it already holds returns the same
    string, which is what makes "regenerate twice, get no diff" true rather than hoped for.
    The markers keep their own lines, so an empty body leaves a well-formed empty block
    instead of collapsing the two markers together.
    """
    inner = body.strip("\n")
    tail = f"\n{block.indent}{block.close}"
    rebuilt = f"{block.open}\n{inner}{tail}" if inner else f"{block.open}{tail}"
    return text[:block.start] + rebuilt + text[block.end:]


# -- frontmatter, edited as text ------------------------------------------------------------

# A top-level key: no indentation, not a list item, not a comment. Anything indented belongs
# to the value above it and is left alone.
KEY_RE = re.compile(r"^(?P<key>[^\s#\-][^:]*?)(?P<sep>:)(?P<gap>[ \t]*)(?P<value>.*)$")
FENCES = ("---", "...")
# Characters that make a plain YAML scalar mean something other than itself.
INDICATORS = "-?:,[]{}#&*!|>'\"%@`"


def frontmatter_span(text: str) -> tuple[int, int] | None:
    """Line indices ``(first, close)`` of the frontmatter, or None when there is none.

    ``first`` is the first line inside it and ``close`` the line holding the closing fence.
    The rule is the parser's (``parse.markdown.split_frontmatter``): the opening fence is on
    line 1 and a closing fence exists, or it is not frontmatter at all.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() in FENCES:
            return 1, index
    return None


def _plain_is_safe(value: str) -> bool:
    """Whether *value* can be written unquoted and still read back as the same string."""
    if not value or value != value.strip():
        return False
    if value[0] in INDICATORS:
        return False
    return ": " not in value and " #" not in value and "\n" not in value


def _formatted(value: str, previous: str) -> str:
    """Render *value*, keeping the quoting style the previous value used.

    A note whose author wrote ``estado: "pendiente"`` gets ``estado: "en-curso"`` back. The
    point is not tidiness: an unnecessary change of style is a change, and a change is a diff
    delivered to every device.
    """
    old = previous.strip()
    if len(old) >= 2 and old[0] == old[-1] and old[0] in "\"'":
        quote = old[0]
        if quote == "'":
            return "'" + value.replace("'", "''") + "'"
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if _plain_is_safe(value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _top_level_keys(lines: list, first: int, close: int) -> list:
    """(index, match) for every top-level key line in the frontmatter, in order."""
    found = []
    for index in range(first, close):
        match = KEY_RE.match(lines[index])
        if match:
            found.append((index, match))
    return found


def set_frontmatter(text: str, key: str, value: str) -> str:
    """Return *text* with frontmatter *key* set to *value*, and nothing else touched.

    The YAML is never parsed and re-emitted, so key order, comments, quoting, indentation and
    blank lines all survive (ADR-0007). Only the one line holding the key is rewritten.

    When a key appears more than once, the **last** occurrence is the one edited, because that
    is the one the app reads (ADR-0004). A key that is not there is appended just above the
    closing fence.
    """
    if "\n" in value:
        raise WriteError(f"cannot set {key!r} to a value spanning several lines")

    span = frontmatter_span(text)
    if span is None:
        raise WriteError(
            "this note has no frontmatter, so there is no property to set. Refusing to invent "
            "one: a note whose first line changes is a note whose whole file changed."
        )

    first, close = span
    lines = text.split("\n")
    keys = _top_level_keys(lines, first, close)
    matching = [(index, match) for index, match in keys if match.group("key").strip() == key]

    if not matching:
        lines.insert(close, f"{key}: {_formatted(value, '')}")
        return "\n".join(lines)

    index, match = matching[-1]
    # A value can run past its own line -- a list, or a folded block. Everything up to the
    # next top-level key belongs to it and goes away with it.
    following = next((at for at, _ in keys if at > index), close)
    rewritten = f"{match.group('key')}{match.group('sep')}{match.group('gap') or ' '}" \
                f"{_formatted(value, match.group('value'))}"
    return "\n".join(lines[:index] + [rewritten] + lines[following:])
