"""Link resolution, implementing ADR-0003.

Two things happen here, and keeping them apart is the whole point:

* **Choosing a target** uses the most specific rule that matches — exact path, then path
  suffix, then basename — and breaks remaining ties deterministically.
* **Counting candidates** uses the union of *all* rules, not just the winning one. A link
  where several files could plausibly have been meant is flagged even when the winner was
  obvious, because that is what makes ``hvk links --ambiguous`` a usable validation list
  rather than a false all-clear.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from urllib.parse import unquote


@dataclass(frozen=True)
class FileEntry:
    id: int
    path: str      # vault-relative, '/' separators
    parent: str    # vault-relative folder, '' at the root
    name: str      # basename with extension
    stem: str      # basename without extension
    ext: str       # lowercased, no dot

    def __hash__(self) -> int:  # identity is the row id; the rest is derived from the path
        return self.id


@dataclass
class Resolution:
    target: FileEntry | None
    candidates: int


def _normalise(target: str) -> str:
    return target.replace("\\", "/").strip().strip("/")


def _fold(text: str) -> str:
    """Fold a name for comparison: Unicode-normalised to NFC, then lowercased.

    macOS stores filenames in NFD and Linux stores whatever it is given, so a vault synced
    between the two ends up with both forms in play. Comparing raw code points would break
    every link written on one platform and read on the other.
    """
    return unicodedata.normalize("NFC", text).lower()


class FileIndex:
    """In-memory lookup tables over every file in the vault, notes and attachments alike."""

    def __init__(self, entries=()):
        self.by_path: dict[str, list[FileEntry]] = {}
        self.by_name: dict[str, list[FileEntry]] = {}
        self.by_stem: dict[str, list[FileEntry]] = {}   # notes only
        for entry in entries:
            self.add(entry)

    def add(self, entry: FileEntry) -> None:
        self.by_path.setdefault(_fold(entry.path), []).append(entry)
        self.by_name.setdefault(_fold(entry.name), []).append(entry)
        if entry.ext == "md":
            self.by_stem.setdefault(_fold(entry.stem), []).append(entry)

    # -- the three matching rules of ADR-0003 -------------------------------------------

    def _exact_path(self, target: str, source: FileEntry) -> set[FileEntry]:
        found: set[FileEntry] = set()
        bases = {"", source.parent}
        for base in bases:
            for candidate in (target, target + ".md"):
                key = _fold(f"{base}/{candidate}") if base else _fold(candidate)
                found.update(self.by_path.get(key, ()))
        return found

    def _path_suffix(self, target: str) -> set[FileEntry]:
        last = _fold(target.rsplit("/", 1)[-1])
        pool = self.by_name.get(last, []) + self.by_stem.get(last, [])
        folded = _fold(target)
        suffixes = ("/" + folded, "/" + folded + ".md")
        return {e for e in pool if _fold(e.path).endswith(suffixes)}

    def _basename(self, target: str) -> set[FileEntry]:
        if "/" in target:
            return set()
        key = _fold(target)
        # Notes match without their extension; anything else has to be named in full, so
        # [[diagram.png]] finds the attachment and [[diagram]] does not.
        return set(self.by_stem.get(key, ())) | set(self.by_name.get(key, ()))

    # -- selection ----------------------------------------------------------------------

    @staticmethod
    def _rank(entry: FileEntry, target: str, source: FileEntry):
        last = unicodedata.normalize("NFC", target.rsplit("/", 1)[-1])
        exact_case = last in (
            unicodedata.normalize("NFC", entry.stem),
            unicodedata.normalize("NFC", entry.name),
        )
        return (
            0 if entry.ext == "md" else 1,          # a bare name overwhelmingly means a note
            0 if exact_case else 1,
            0 if entry.parent == source.parent else 1,
            entry.path.count("/"),                  # closest to the vault root
            entry.path,                             # deterministic backstop
        )

    def resolve(self, target_raw: str, source: FileEntry, *, decode: bool = False) -> Resolution:
        """Resolve a link target written in *source* to a file, following ADR-0003."""
        target = _normalise(unquote(target_raw) if decode else target_raw)
        if not target:
            # A bare subpath such as [[#Heading]] points at the containing file.
            return Resolution(source, 1)

        by_rule = (
            self._exact_path(target, source),
            self._path_suffix(target),
            self._basename(target),
        )
        candidates = set().union(*by_rule)
        if not candidates:
            return Resolution(None, 0)

        winners = next(matches for matches in by_rule if matches)
        best = min(winners, key=lambda e: self._rank(e, target, source))
        return Resolution(best, len(candidates))
