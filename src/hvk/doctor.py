"""Is this installation actually working? (phase 6)

Built to be *called* by whatever monitoring a machine already has, not to replace it. The
server this was written for already checks its own services and messages Telegram when one
falls over; it had no way to ask whether the index still describes the vault. So this reports
the things only hvk can know, in one command, with an exit code a cron line can branch on.

Two rules shape what is in here:

* **Only what hvk can answer.** Whether a systemd unit is alive is a question for systemd, and
  every machine already asks it differently. Whether the index has drifted from the files is a
  question nothing else can answer.
* **A check that cannot fail is noise.** Each one has a threshold, and the ones that are merely
  interesting are warnings, so a non-zero exit means something is actually wrong.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from hvk import paths, query
from hvk import scan as scanner

OK, WARN, FAIL = "ok", "warn", "fail"

# How stale the index may be before it is a failure rather than a note. Generous on purpose:
# the watcher only writes when something changes, so a quiet vault has an old timestamp and
# that is not a fault.
DEFAULT_MAX_DRIFT = 0          # files counted on disk vs in the index; any difference matters
DEFAULT_STUCK_HOURS = 6        # a job claimed this long ago has no runner behind it


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {"check": self.name, "status": self.status, "detail": self.detail}


@dataclass
class Report:
    checks: list

    @property
    def failures(self) -> int:
        return sum(1 for check in self.checks if check.status == FAIL)

    @property
    def warnings(self) -> int:
        return sum(1 for check in self.checks if check.status == WARN)


def _count_notes_on_disk(vault) -> int:
    """Markdown files the scanner would index, counted without parsing any of them."""
    return sum(1 for path in scanner.iter_vault_files(vault) if path.suffix.lower() == ".md")


def _index_matches_disk(conn: sqlite3.Connection, location: paths.Locations) -> Check:
    """The check the machine's own monitoring cannot make.

    Freshness by timestamp would be the obvious thing and it is the wrong thing: the watcher
    writes only when something changes, so a vault nobody touched for a week has a week-old
    `last_scan` and is perfectly healthy. Counting the notes says whether the index still
    describes the vault, which is the question actually being asked.
    """
    indexed = conn.execute("SELECT count(*) FROM files WHERE kind='note'").fetchone()[0]
    on_disk = _count_notes_on_disk(location.vault)
    drift = abs(indexed - on_disk)
    if drift > DEFAULT_MAX_DRIFT:
        missing = on_disk - indexed
        way = f"{missing} not indexed" if missing > 0 else f"{-missing} indexed but gone"
        return Check(
            "index matches the vault", FAIL,
            f"{on_disk} notes on disk, {indexed} in the index ({way}). "
            f"Is the watcher running? `hvk scan` catches it up.",
        )
    return Check("index matches the vault", OK, f"{indexed} notes")


def _parse_errors(conn: sqlite3.Connection) -> Check:
    rows = conn.execute(
        "SELECT path, parse_error FROM files WHERE parse_error IS NOT NULL LIMIT 3"
    ).fetchall()
    total = conn.execute(
        "SELECT count(*) FROM files WHERE parse_error IS NOT NULL"
    ).fetchone()[0]
    if not total:
        return Check("notes parse cleanly", OK)
    named = ", ".join(row["path"] for row in rows)
    # A warning, not a failure: one note with broken YAML is the vault's problem to fix, and
    # nobody should be woken up for it.
    return Check("notes parse cleanly", WARN, f"{total} with invalid frontmatter: {named}")


def _stuck_jobs(location: paths.Locations, jobs_dir: str | None, hours: int) -> Check | None:
    """Jobs claimed long ago and never settled. ADR-0009 leaves these for a person on purpose."""
    if not jobs_dir:
        return None
    from hvk import jobs as order_notes
    from hvk import write

    vault = write.Vault(location.vault)
    try:
        directory = vault.resolve(jobs_dir, allow_hidden=True)
        notes = order_notes.find_jobs(vault, directory)
    except (order_notes.JobError, write.WriteError) as exc:
        return Check("no job is stuck", FAIL, str(exc))

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    stuck = []
    for note in notes:
        job = order_notes.read_job(vault, note)
        if job is None or job.status != "running":
            continue
        _, started = order_notes._lookup(job.front, order_notes.KEYS["started"])
        when = _as_datetime(started)
        if when is None or when < cutoff:
            stuck.append(note)
    if stuck:
        return Check(
            "no job is stuck", FAIL,
            f"claimed over {hours}h ago and never finished: {', '.join(stuck[:3])}. "
            f"A runner died mid-flight; nothing retries it by design (ADR-0009).",
        )
    return Check("no job is stuck", OK, f"{len(notes)} note(s) in the jobs directory")


def _as_datetime(value) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    return None


def _broken_links(conn: sqlite3.Connection) -> Check:
    counts = query.info(conn)
    broken = counts["broken_links"]
    if not broken:
        return Check("links resolve", OK)
    return Check("links resolve", WARN, f"{broken} unresolved (see `hvk links --broken`)")


def run(location: paths.Locations, *, jobs_dir: str | None = None,
        stuck_hours: int = DEFAULT_STUCK_HOURS) -> Report:
    """Everything hvk can check about its own installation, in one pass."""
    from hvk import db

    checks: list[Check] = []
    try:
        conn = db.connect(location.db_path)
    except Exception as exc:                             # pragma: no cover - unreadable index
        return Report([Check("index is readable", FAIL, str(exc))])

    try:
        try:
            db.check_schema(conn)
            db.check_vault(conn, location.vault)
            checks.append(Check("index is readable", OK, str(location.index_dir)))
        except db.IndexError_ as exc:
            return Report([Check("index is readable", FAIL, str(exc))])

        checks.append(_index_matches_disk(conn, location))
        checks.append(_parse_errors(conn))
        checks.append(_broken_links(conn))
    finally:
        conn.close()

    stuck = _stuck_jobs(location, jobs_dir, stuck_hours)
    if stuck is not None:
        checks.append(stuck)
    return Report(checks)
