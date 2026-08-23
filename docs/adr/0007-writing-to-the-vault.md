# 0007 — Writing to the vault

**Status:** accepted
**Date:** 2026-08-23
**Phase:** 4

## Context

Every line of this project so far only reads. That has been a quiet safety net: the index is
derived, so the worst a bug could do was produce a wrong answer, and `hvk rebuild` fixed it.
Phase 4's materialised views and phase 5's order-notes both write into the vault, and from
that point a bug can destroy something that exists nowhere else.

`CLAUDE.md` already fixes the principles — atomic writes, trash rather than delete, preserve
frontmatter and line endings, never leave the vault — but each of them hides a decision that
has to be made before any code exists, because the vault is not an ordinary directory:

* **Something else is writing at the same time.** Obsidian Sync delivers changes whenever it
  likes, and the person may have the note open on their phone. A read-modify-write that takes
  a second is a second in which the file can change underneath.
* **Something else is watching.** Our own watcher and Sync both react to every touched file. A
  cron job that rewrites a view every thirty minutes, changing nothing, would wake both of
  them every thirty minutes, forever, on every device.
* **Not everything survives a round trip.** Read a file as text and write it back and you can
  silently change its line endings, its final newline, or its byte-order mark. On a vault
  synced across devices, that turns into a conflict, or into a diff of the whole file.

## Alternatives

- **Write in place** (open, truncate, write). Simplest, and the one thing that must never
  happen: a crash or a full disk halfway through leaves a truncated note, and truncation is
  not recoverable from the file itself.
- **Lock the file.** Advisory locks are honoured by neither Obsidian nor Sync, so a lock would
  give the comforting appearance of safety without any of it.
- **Write a temporary file and rename it, refusing when the original moved underneath.**
  Chosen.

## Decision

A single module, `src/hvk/write.py`, through which every write to the vault passes. Nothing
else in the codebase opens a vault file for writing. Its entry point is a `Vault` object: the
path check lives on the object you need in order to write at all, the same way the
index-inside-the-vault check lives on `paths.Locations`. A safety rule that can be reached
around is not a safety rule.

### Atomic, and invisible while it happens

Write to a temporary file in the same directory, `fsync` it, then `os.replace` onto the
target — atomic within a filesystem on both POSIX and Windows. Same directory because a rename
across filesystems is not atomic and would silently degrade into a copy.

The temporary file is named `.hvk-tmp-<random>`, which is a dotfile: the exclusion rules of
ADR-0002 already ignore it, so neither our watcher nor the index ever sees it. It is removed
on any failure.

### Never write when nothing changed

If the bytes to be written are identical to the bytes already there, **do nothing at all** —
do not open the file, do not touch its mtime. This is not an optimisation. It is what stops a
materialised view regenerating every thirty minutes from waking the watcher and Sync every
thirty minutes on every device, and it is what makes the plan's exit criterion
("regenerating twice with no changes produces no diff") true by construction rather than by
luck.

### Refuse when the file moved underneath

Every write states the digest the caller believed the file had. If the file on disk no longer
matches, the write is refused and says so. Sync delivering a change from a phone mid-edit is
normal, not exceptional, and the correct answer is to fail and let the caller retry against
the new content — never to overwrite an edit that arrived while we were thinking.

A file that did not exist is expressed as an expected digest of `None`, so "create only if
still absent" is the same mechanism rather than a special case.

This is not a lock, and it does not pretend to be one: it closes the window between reading
and writing, not the instant of the rename itself. Closing that one would need cooperation
from software that will not cooperate.

### Preserve what a round trip would otherwise eat

The original bytes are inspected before editing and restored afterwards:

- **Line endings.** Whatever the file predominantly used, it keeps. A mixed file keeps its
  majority ending, and the fact that it was mixed is reported rather than silently normalised.
- **The final newline**, present or absent, stays as it was.
- **A byte-order mark**, if there was one, is written back. Obsidian tolerates them and some
  Windows editors add them; removing one rewrites the first line of a file for no reason.
- **Encoding.** UTF-8 only. A file that is not valid UTF-8 is refused rather than repaired: we
  do not know what it was meant to be, and guessing would corrupt it irreversibly.

Frontmatter is preserved by never reserialising it. Editing a note means editing its text; the
YAML is not parsed and re-emitted, so key order, comments, quoting style, indentation and even
the duplicate keys that ADR-0004 had to reason about all survive, because nothing ever touched
them. Phase 5 will need to change a value *inside* frontmatter; when it does, it will edit
those lines as text for the same reason, and a YAML round trip stays out of this codebase.

### Delete means trash

Removing a file moves it to `.trash/` inside the vault, **keeping its path relative to the
vault root** and appending a timestamp if something is already there. Nothing in this project
calls `unlink` on a vault file.

Keeping the relative path is a deliberate divergence from what the app appears to do, which is
to flatten everything into `.trash/`: two notes called `Index.md` in different folders would
then collide, and a flattened file no longer says where it came from. The cost is that a
person restoring by hand finds a folder tree rather than a flat list.

### Never outside the vault, and never into the hidden files

Every path is resolved — symlinks included — and checked to be inside the vault before
anything is opened. The path itself is resolved, not merely its parent: a *broken* symlink
pointing outside the vault is exactly what a parent-only check waves through and then follows
on `open()`. A note is untrusted input (`CLAUDE.md`), and a generated path that escapes the
vault is the shape a prompt-injection attack would take.

Beyond that, this module refuses to write anything under a path component starting with `.` —
`.obsidian/`, `.git/`, `.trash/`, `.smart-env/`. It writes notes, not the machinery around
them. Rewriting `app.json` would change link resolution under the index's feet; writing inside
`.git/` needs no explanation. If a later phase has to touch configuration, it gets its own
decision rather than a quiet exception here.

### Generated blocks

Content this project generates lives between two markers, and only what is between them is
ever replaced. The splicing machinery takes both markers as arguments and knows nothing about
what they say: naming a block belongs to the feature that generates it. Phase 4's materialised
views use the markers the plan fixes, `<!-- vista:inicio -->` and `<!-- vista:fin -->`, and
record that choice in their own ADR.

Two shapes are refused rather than guessed at: an opening marker with no closing one — the
rest of the file is not ours to replace — and a second opening marker before the first has
closed.

Replacing a block with the content it already holds returns the file byte for byte, which is
where the "no write when nothing changed" rule above gets the chance to do its job.

## Consequences

**Concurrent writes surface as refusals rather than as lost edits.** Callers have to handle
that, and a cron job that fails once because Sync was mid-delivery is correct behaviour, not a
fault to be silenced.

**Idempotence becomes a property of the writer, not of each feature.** Materialised views,
order-note status changes and anything written later all get "unchanged means untouched" for
free, and none of them can forget it.

**A file that is not valid UTF-8 stops the operation.** That will be somebody's scanned note
with a stray byte, and they will have to fix it before this project will write to it. Refusing
is the right side to fail on: the alternative is silently rewriting bytes we could not read.

**`.trash/` grows and nothing here empties it.** That is deliberate for now — an automatic
cleaner is a deletion path, and deletion paths are what this ADR exists to constrain. If it
becomes a problem, it gets its own decision.

**Writing configuration is now a decision, not an oversight.** Anything that needs to touch
`.obsidian/` will hit a refusal with a message saying so, which is the point: it should stop
and be argued for.
