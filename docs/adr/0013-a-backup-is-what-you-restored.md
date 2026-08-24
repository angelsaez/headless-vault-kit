# 0013 — A backup is what you restored

**Status:** accepted
**Date:** 2026-08-24
**Phase:** 6

## Context

The vault on the server had three copies and no backup.

Obsidian Sync holds it, and so does every other device Ángel owns. The vault is a git
repository with a checkpoint every thirty minutes. Between them they cover a disk failure and
a bad edit, and the server's own operations notes recorded the conclusion that follows from
that: *triple protection, no further action needed.*

Both halves of that miss the same failure. **Sync replicates a deletion as faithfully as it
replicates a note**, to every device, in seconds — the three copies are one copy with three
addresses, and the agent this project runs against the vault can write to it. The git
checkpoints do answer that, and only until the machine is gone: ADR-0006 chose a local
repository with no remote, deliberately, and deferred surviving the loss of the server to
this phase.

So the plan's phase 6 asks for two things — a daily copy off the machine, and a restore
rehearsed once into an alternative directory — and the second is the one that turns the first
from an assertion into a fact.

## Alternatives

- **Rely on Sync and the other devices.** Free, already there, and already the status quo. It
  answers hardware and not mistakes, which is the failure mode a 24/7 agent adds.
- **Give the vault's git repository a private remote.** Cheap, incremental, and it would carry
  the history off the machine. It also carries what git deliberately does not commit — the
  trash, the private folders — nowhere at all, needs a deploy key on the server, and turns
  every network blip into a failing cron job. ADR-0006 weighed exactly this and said no; nothing
  since has changed the reasoning.
- **A dated archive of the whole vault, handed to a hook that takes it off the machine, and a
  restore script that refuses to touch the live vault.** Chosen.

## Decision

`vault-backup.sh` writes `vault-YYYY-MM-DD.tar.gz` and a `.sha256` beside it, containing the
vault as it stands — notes, attachments, `.obsidian/`, `.trash/`, the git history and the
private folders — and hands both to `BACKUP_OFFSITE_HOOK`, an executable of the operator's
own, if one is configured. `vault-restore.sh` puts an archive into a directory that is not the
vault, verifies it, and indexes it with `hvk` to prove that what came back is a vault.

Three rules fall out of that and are enforced rather than documented:

**The destination is the switch.** No `BACKUP_DIR`, no cron entry — the same shape as
ADR-0009's jobs directory, and for the same reason: nobody should get a nightly copy of a
40 GB vault onto a disk they did not choose. But the asymmetry with ADR-0009 is deliberate.
A runner that does not run is safe; a backup that does not run is discovered on the day it was
needed. So once the destination is set, every failure is loud, and the script that finds itself
running without one exits non-zero rather than quietly doing nothing.

**A backup contains everything or it is a surprise.** The checkpoints leave `_PRIVATE/` out
because a commit is an audit trail; the archive takes it, because the folder someone most
wants back is the one they were most careful with. The cost is stated where it lands: the
archive is exactly as sensitive as the vault, and so is wherever the hook puts it.

**A restore never writes over the live vault.** The script refuses the vault, anything inside
it, any directory containing it, and any directory that is not empty. Promoting a restored
copy is a manual procedure in `deploy/RESTORE.md`, whose first step is stopping the syncer —
a script that did this while Sync was running would carry a local recovery to every device
mid-flight.

## Consequences

**The off-site half cannot be proven by any script here.** The hook's exit code is a claim
about the command, not about the destination — the same trap the server's other backup script
already learned to check for. What proves it is fetching the archive back and restoring it,
which is what the rehearsal does and what makes it worth repeating rather than reading.

**A daily archive of a whole vault does not scale forever.** At 47 MB it is nothing. A vault
with a large attachment store will eventually want something incremental, and `BACKUP_EXCLUDE`
is a delaying tactic rather than an answer. The signal to revisit is the backup taking long
enough to notice.

**Recovery is to last night, not to the last minute.** Between the archive and now, the git
checkpoints are the finer-grained answer — thirty minutes — and Sync's own version history is
finer still. The document names all three and which failure each one answers, because reaching
for the archive when a single note was deleted is how a small mistake becomes a mass reversion.

**Obsidian Sync's own history stays unrehearsed.** Testing it means asking a live syncer to
re-register or re-download a vault it is currently serving; the rehearsal would risk the thing
it rehearses. It is recorded as untested rather than counted as a fourth copy that works.

**One rehearsal expires.** It says the procedure worked on 2026-08-24, on one vault, on one
machine. It is evidence about that day, and the document says so rather than implying the
question is permanently settled.
