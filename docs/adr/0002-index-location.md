# 0002 — Index location and exclusion rules

**Status:** accepted
**Date:** 2026-08-21
**Phase:** 2

## Context

The v2 plan (§4) fixes the hard requirement — the index lives **outside the vault**, so that
Obsidian Sync never touches it and no watcher ever fires on it — but leaves the concrete path
as "`~/.nexus-index/` by convention" and the exclusion list unspecified (annex, decision 3).

Three things force this to be pinned down before the scanner is written:

1. `nexus` is the name of the author's personal vault, not of this project. A tool meant to be
   published cannot scatter someone else's vault name across its users' home directories.
2. A user may have **several vaults**. A single index directory collides them.
3. "Exclusions" is really **two different lists** that the plan mentions as one: what is not
   indexed as content, and what is not watched. They do not coincide — `.obsidian/` is never
   indexed, yet it *is* read by explicit path to obtain the vault's configuration.

## Alternatives

- **Index inside the vault** (e.g. `.hvk/`). Ruled out by the plan, and rightly: Sync would
  replicate it to every device, the watcher would chase its own tail, and a SQLite database in
  WAL mode syncing between machines is corruption waiting to happen.
- **Literal `~/.nexus-index/`.** Meets the requirement but carries a foreign name and does not
  support multiple vaults.
- **`$XDG_CACHE_HOME`** (`~/.cache/hvk/`). Semantically defensible, since the index is 100%
  derived and rebuildable. Rejected because on servers `~/.cache` sometimes lands on `tmpfs`
  or under automatic cleaners, and losing the index costs a full rebuild. Derived does not
  mean cheap.

## Decision

Default path, one directory per vault, following the XDG base directory spec:

```text
${XDG_DATA_HOME:-~/.local/share}/hvk/<vault-name>-<8-char-hash-of-real-path>/
├── index.sqlite      (plus -wal, -shm)
└── hvk.log
```

The identifier combines the vault's readable name with the first 8 characters of a hash of its
resolved path: it is obvious at a glance which vault a directory belongs to, and two vaults
with the same name in different places do not collide.

**Configuration precedence**, highest first:

| What | How | Meaning |
|---|---|---|
| Index | `--index PATH` | Exact index directory, for this invocation only |
| Index | `HVK_INDEX_DIR` | Replaces `~/.local/share/hvk` as the **root**; per-vault directories still live underneath |
| Vault | `--vault PATH` | Exact vault path |
| Vault | `HVK_VAULT` | The same, through the environment |
| Vault | *(nothing)* | Walk up from the working directory until a `.obsidian/` is found; error if there is none |

**Safety rule, non-negotiable:** after resolving symlinks, if the index directory falls inside
the vault, `hvk` aborts with an error. This is not a warning that can be ignored — it is the
one condition that prevents the sync → watcher → index → sync loop.

The database keeps a `meta` table holding the vault's resolved path, the schema version and
the `hvk` version. If the recorded path does not match the vault being queried, the command
fails with a message that says exactly what happened and points at `hvk rebuild`.

SQLite runs in **WAL** mode with `synchronous=NORMAL`, so the index stays queryable while it
is being rewritten — which is the normal case when the agent is working and Sync is delivering
changes at the same time.

### List A — what is not indexed as content

- Any directory whose name starts with `.`, at any depth. One rule covers `.obsidian/`,
  `.git/`, `.trash/`, `.smart-env/` and whatever plugins invent next, without maintaining a
  blocklist that ages.
- Operating-system litter: `.DS_Store`, `Thumbs.db`, `desktop.ini`.
- The index directory itself, in case someone forces it inside the vault with `--index` (the
  safety rule above already refuses to run in that case).

**Explicit exception:** `.obsidian/app.json` and `.obsidian/*-plugins.json` are **read** by
direct path, because that is where the vault's configuration and the phase 1 inventory come
from. Reading them is not indexing them: they never enter `files` or FTS.

Every other file — attachments, `.canvas`, `.base`, PDFs, images — **is** inventoried in the
`files` table with its type, even though tier 0 does not parse it. This is not optional:
without those rows, a link to an attachment would be reported as broken.

### List B — what is not watched (incremental indexing)

Everything in list A, plus:

- `.obsidian/workspace*`, which changes every time someone moves a pane and carries no
  information worth indexing.
- Temporary files and half-written saves: `*.tmp`, `*.partial`, `*~`, `~$*`.
- Any file whose size or `mtime` is still changing between two checks: the watcher waits for
  it to settle. Obsidian Headless writes large files in several steps, and parsing one
  mid-write puts garbage in the index.

### Extensibility

The declared extension point is a `.hvkignore` file at the vault root using `.gitignore`
syntax. It is **not implemented yet**: the fixed rules cover the real case, and adding a
pattern engine before a user asks for it is exactly the over-engineering the plan flags as a
risk (§7). It is recorded here so that, when the need appears, it is obvious where it goes.

## Consequences

**Moving a vault invalidates its index.** The resolved path changes, the hash changes, the
directory changes, and the moved vault is reindexed from scratch. That is correct — the index
is derived — but it has to be stated in the documentation so nobody thinks they lost data. The
orphaned directory is left behind taking up disk; a future `hvk gc` will clean it up.

**Multiple vaults work with no configuration**, which is what makes "test against
`test-vaults/` while the real vault stays indexed" possible.

**Diverging from the plan on the concrete path is accepted** (`~/.nexus-index/` →
`~/.local/share/hvk/`). The requirement the plan protects — outside the vault, invisible to
Sync — is met just as well; what changes is the name, for neutrality, and the structure, to
support several vaults.

**Hiding everything that starts with a dot has a cost:** if content inside a hidden directory
ever needs indexing, the exception will have to be carved out by hand, as `.obsidian/` already
is. That is preferable to a blocklist that has to be chased forever.
