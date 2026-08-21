"""Incremental indexing driven by filesystem events.

The plan asks for a watcher with debounce and a stability check, because Obsidian Headless
writes files in several steps while sync delivers them and parsing one mid-write puts garbage
in the index.

The decision logic lives in :class:`ChangeQueue`, which knows nothing about watchdog, threads
or clocks it does not receive. That is what makes the interesting behaviour -- when a path is
released, and when it is held back -- testable without sleeping.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from hvk import db
from hvk import scan as scanner
from hvk.paths import Locations

# List B of ADR-0002: excluded from watching on top of everything excluded from indexing.
UNSTABLE_SUFFIXES = (".tmp", ".partial", ".crswap", "~")
UNSTABLE_PREFIXES = ("~$", ".~")

DEBOUNCE_SECONDS = 1.0
POLL_SECONDS = 0.25
# A batch this large almost always means a folder was moved, renamed or synced wholesale, and
# a full scan is both cheaper and more correct than reasoning about each path.
FULL_SCAN_THRESHOLD = 200


def is_watchable(vault: Path, path: Path) -> bool:
    """Whether an event on *path* is worth acting on (ADR-0002, lists A and B)."""
    try:
        relative = path.relative_to(vault)
    except ValueError:
        return False

    parts = relative.parts
    if not parts:
        return False
    # Any dot-directory, which covers .obsidian/ (workspace files included), .git/ and .trash/.
    if any(part.startswith(".") for part in parts[:-1]):
        return False

    name = parts[-1]
    if name.startswith(".") or name in scanner.LITTER:
        return False
    if name.startswith(UNSTABLE_PREFIXES) or name.endswith(UNSTABLE_SUFFIXES):
        return False
    return True


@dataclass
class _Pending:
    last_event: float
    signature: tuple | None = None


@dataclass
class ChangeQueue:
    """Holds changed paths until they have been quiet *and* still for long enough.

    Two separate conditions, and both matter. Debounce absorbs the burst of events a single
    save produces. The stability check then refuses to release a path whose size or mtime is
    still moving, which is the case the plan cares about: a large file arriving over sync.
    """

    debounce: float = DEBOUNCE_SECONDS
    pending: dict[Path, _Pending] = field(default_factory=dict)

    def record(self, path: Path, now: float) -> None:
        entry = self.pending.get(path)
        if entry is None:
            self.pending[path] = _Pending(last_event=now)
        else:
            entry.last_event = now
            entry.signature = None  # it moved again; whatever we measured is stale

    @staticmethod
    def _signature(path: Path) -> tuple | None:
        try:
            stat = path.stat()
        except OSError:
            return None  # gone: a deletion is settled by definition
        return (stat.st_size, stat.st_mtime_ns)

    def release(self, now: float) -> list[Path]:
        """Return the paths ready to index, leaving the rest for a later round."""
        ready: list[Path] = []
        for path, entry in list(self.pending.items()):
            if now - entry.last_event < self.debounce:
                continue
            signature = self._signature(path)
            if signature is None:  # deleted, or never existed
                ready.append(path)
                del self.pending[path]
                continue
            if entry.signature == signature:
                ready.append(path)
                del self.pending[path]
            else:
                # Still growing. Measure again next round rather than parsing half a file.
                entry.signature = signature
        return ready


class _Handler:
    """Adapts watchdog events onto the queue. Imported lazily so watchdog stays optional."""

    def __init__(self, vault: Path, queue: ChangeQueue, on_directory: Callable[[], None]):
        self.vault = vault
        self.queue = queue
        self.on_directory = on_directory

    def dispatch(self, event) -> None:
        if event.is_directory:
            # Folder moves and deletions touch many paths at once; a full scan settles them
            # correctly and is not worth reimplementing here.
            self.on_directory()
            return
        now = time.monotonic()
        for attribute in ("src_path", "dest_path"):
            raw = getattr(event, attribute, None)
            if not raw:
                continue
            path = Path(raw if isinstance(raw, str) else raw.decode())
            if is_watchable(self.vault, path):
                self.queue.record(path, now)


def watch(
    loc: Locations,
    *,
    debounce: float = DEBOUNCE_SECONDS,
    poll: float = POLL_SECONDS,
    on_batch: Callable[[scanner.ScanStats], None] | None = None,
    stop: Callable[[], bool] | None = None,
) -> None:
    """Watch the vault and index changes as they settle. Runs until interrupted.

    *on_batch* is called after every batch that changed anything, and *stop* lets a caller --
    a test, or a future supervisor -- end the loop without a signal.
    """
    try:
        from watchdog.observers import Observer
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise db.IndexError_(
            "watching needs the watchdog package. Install hvk with its dependencies, or run "
            "'hvk scan' from cron instead."
        ) from exc

    queue = ChangeQueue(debounce=debounce)
    needs_full_scan = False

    def request_full_scan() -> None:
        nonlocal needs_full_scan
        needs_full_scan = True

    handler = _Handler(loc.vault, queue, request_full_scan)
    observer = Observer()
    observer.schedule(handler, str(loc.vault), recursive=True)
    observer.start()
    try:
        while not (stop and stop()):
            time.sleep(poll)
            ready = queue.release(time.monotonic())
            if needs_full_scan or len(ready) >= FULL_SCAN_THRESHOLD:
                needs_full_scan = False
                stats = scanner.scan(loc)
            elif ready:
                stats = scanner.apply_changes(loc, ready)
            else:
                continue
            if on_batch and (stats.added or stats.changed or stats.removed):
                on_batch(stats)
    finally:
        observer.stop()
        observer.join(timeout=5)


def drain(loc: Locations, paths: Iterable[Path]) -> scanner.ScanStats:
    """Index a known set of paths straight away, skipping the ones we never watch."""
    wanted = [p for p in paths if is_watchable(loc.vault, p)]
    return scanner.apply_changes(loc, wanted)
