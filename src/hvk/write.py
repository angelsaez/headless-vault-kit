"""The only way anything in this project writes to a vault (ADR-0007).

Until phase 4 every line of code here only read, which meant a bug could produce a wrong
answer but never destroy anything. That is no longer true, so every write goes through this
module and obeys the same rules: atomic replacement, no write at all when nothing changed,
refusal when the file moved underneath, and the file's own line endings, final newline and
byte-order mark preserved exactly.

Frontmatter survives because it is never parsed here. Editing a note edits its text; the YAML
is never reserialised, so key order, comments and quoting stay as the author wrote them.
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
# ever seeing it while it exists.
TEMP_PREFIX = ".hvk-tmp-"

BLOCK_RE_TEMPLATE = (
    r"(?P<open><!--[ \t]*hvk:begin{selector}[^>]*-->)"
    r"(?P<body>.*?)"
    r"(?P<close><!--[ \t]*hvk:end[ \t]*-->)"
)


class WriteError(Exception):
    """Raised when a write cannot be made safely. Never raised for 'nothing to do'."""


class ConflictError(WriteError):
    """The file changed since it was read. The caller should re-read and decide again."""


@dataclass(frozen=True)
class Original:
    """What a file looked like when it was read, and what it needs to look like again."""

    text: str                 # decoded, newlines normalised to \n, BOM and final newline stripped
    newline: str = "\n"
    final_newline: bool = True
    bom: bool = False
    digest: str | None = None  # sha256 of the bytes on disk; None when the file was absent
    mixed_newlines: bool = False

    @property
    def exists(self) -> bool:
        return self.digest is not None


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inside(vault: Path, path: Path) -> bool:
    """True when *path* really is inside *vault*, symlinks resolved.

    A note is untrusted input, so a generated path that escapes the vault is exactly the shape
    a prompt injection would take.
    """
    vault = vault.resolve()
    try:
        candidate = path.resolve()
    except OSError:
        return False
    return candidate == vault or candidate.is_relative_to(vault)


def _require_inside(vault: Path, path: Path) -> Path:
    # The parent is resolved rather than the file, so a path that does not exist yet can still
    # be checked -- and so a symlinked directory cannot be used to escape.
    target = path if path.exists() else path.parent
    if not inside(vault, target):
        raise WriteError(
            f"refusing to touch {path}: it resolves outside the vault at {vault}"
        )
    return path


def read(path: Path, *, vault: Path) -> Original:
    """Read a file, remembering everything a round trip would otherwise destroy."""
    _require_inside(vault, path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return Original(text="")
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
    newline = "\r\n" if crlf > lf else "\n"
    text = decoded.replace("\r\n", "\n")

    final_newline = text.endswith("\n")
    if final_newline:
        text = text[:-1]

    return Original(
        text=text,
        newline=newline,
        final_newline=final_newline,
        bom=bom,
        digest=digest_bytes(raw),
        mixed_newlines=crlf > 0 and lf > 0,
    )


def render(text: str, original: Original) -> bytes:
    """Turn edited text back into bytes shaped like the file it came from."""
    body = text
    if original.final_newline and not body.endswith("\n"):
        body += "\n"
    elif not original.final_newline and body.endswith("\n"):
        body = body[:-1]
    if original.newline != "\n":
        body = body.replace("\n", original.newline)
    if original.bom:
        body = BOM + body
    return body.encode("utf-8")


def write(path: Path, text: str, original: Original, *, vault: Path) -> bool:
    """Write *text* to *path*, atomically. Returns True when the file actually changed.

    The write is refused if the file no longer matches the digest recorded in *original*:
    sync delivering an edit from a phone mid-operation is normal, and overwriting it would be
    the one unrecoverable mistake this module exists to prevent.
    """
    _require_inside(vault, path)
    data = render(text, original)

    current: bytes | None
    try:
        current = path.read_bytes()
    except FileNotFoundError:
        current = None
    except OSError as exc:
        raise WriteError(f"cannot read {path}: {exc}") from exc

    actual = digest_bytes(current) if current is not None else None
    if actual != original.digest:
        raise ConflictError(
            f"{path} changed since it was read"
            f"{' (it now exists)' if original.digest is None else ''}"
            f"{' (it has been deleted)' if actual is None else ''}. "
            f"Nothing was written. Read it again and decide with the new content."
        )

    # Nothing changed: do not open the file, do not touch its mtime. This is what keeps a view
    # regenerated every half hour from waking the watcher and sync every half hour (ADR-0007).
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
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def trash(path: Path, *, vault: Path) -> Path:
    """Move a file to the vault's ``.trash/``, keeping its relative path.

    Nothing in this project unlinks a vault file. Obsidian's own trash works this way, so
    what was removed turns up where its owner already knows to look.
    """
    _require_inside(vault, path)
    if not path.exists():
        raise WriteError(f"cannot trash {path}: it does not exist")

    relative = path.resolve().relative_to(vault.resolve())
    target = vault / TRASH_DIR / relative
    if target.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = target.with_name(f"{target.stem} {stamp}{target.suffix}")

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(path, target)
    except OSError as exc:
        raise WriteError(f"cannot move {path} to the trash: {exc}") from exc
    return target


# -- generated blocks ---------------------------------------------------------------------

def _block_pattern(selector: str = "") -> re.Pattern:
    return re.compile(BLOCK_RE_TEMPLATE.format(selector=selector), re.DOTALL)


def find_blocks(text: str) -> list[dict]:
    """Every ``hvk:begin`` / ``hvk:end`` block, with the attributes of its opening marker."""
    blocks = []
    for match in _block_pattern().finditer(text):
        attributes = dict(
            re.findall(r'([A-Za-z_][\w-]*)\s*=\s*"([^"]*)"', match.group("open"))
        )
        blocks.append({
            "open": match.group("open"),
            "body": match.group("body"),
            "close": match.group("close"),
            "attributes": attributes,
            "start": match.start(),
            "end": match.end(),
        })
    return blocks


def replace_block(text: str, body: str, *, index: int = 0) -> str:
    """Replace the body of the *index*-th generated block, leaving everything else alone.

    Idempotent by construction: replacing a block with what it already contains returns the
    string unchanged, which is what makes "regenerate twice, get no diff" true rather than
    hoped for.
    """
    blocks = find_blocks(text)
    if not blocks:
        _check_unclosed(text)
        raise WriteError("no <!-- hvk:begin ... --> block found")
    if index >= len(blocks):
        raise WriteError(f"asked for block {index}, but only {len(blocks)} are present")

    block = blocks[index]
    # The markers keep their own lines, so an empty body still leaves a well-formed block
    # rather than collapsing the two markers together.
    inner = body.strip("\n")
    rebuilt = block["open"] + "\n" + inner + "\n" + block["close"] if inner else block["open"] + "\n" + block["close"]
    return text[: block["start"]] + rebuilt + text[block["end"]:]


def _check_unclosed(text: str) -> None:
    if re.search(r"<!--[ \t]*hvk:begin", text):
        raise WriteError(
            "found <!-- hvk:begin ... --> with no matching <!-- hvk:end -->. Refusing to "
            "guess where the generated block ends: the rest of the file is not ours to replace."
        )
