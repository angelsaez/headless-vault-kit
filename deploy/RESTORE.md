# Backup, and the restore that was rehearsed

A backup nobody has restored is a hypothesis. This is the procedure, and it has been run
end to end once — on the server, from the archive, into a directory beside the live vault
(the numbers are at the bottom).

## What already protects the vault, and what it does not

Three copies exist before any of this, and it is worth being exact about which failure each
one answers, because the gaps are not where people expect.

| Copy | Answers | Does not answer |
|---|---|---|
| Obsidian Sync, and your other devices | the machine dying, the disk failing | **a deletion.** Sync replicates one as faithfully as it replicates a note, to every device, in seconds |
| git checkpoints in the vault, every 30 minutes | a bad edit, a deletion, an agent that went wrong — up to half an hour back | **the machine.** The repository is local, with no remote ([ADR-0006](../docs/adr/0006-deployment-leaves-the-system-alone.md)), so the history dies with the disk |
| the daily archive, off the machine | both of the above, as of last night | anything written since last night |

The first two overlap almost perfectly and both miss the same thing: an agent with write
access, an `rm -rf` in the wrong directory, or a filesystem that goes. That is what the
archive is for, and it is why it holds the git history too — a copy of the damage is not a
recovery, a copy plus its history is.

## Turning the daily backup on

The destination is the switch. With `BACKUP_DIR` empty nothing is scheduled at all; set it,
re-run the installer, and there is a nightly entry ([ADR-0013](../docs/adr/0013-a-backup-is-what-you-restored.md)).

```sh
$EDITOR ~/.config/hvk/deploy.env      # BACKUP_DIR, and BACKUP_OFFSITE_HOOK to get it off here
./deploy/install.sh                   # or --only watch,schedules,backup -- see below
crontab -l | grep vault-backup        # 41 3 * * * ... by default
~/.local/share/hvk/deploy-bin/vault-backup.sh    # once, by hand, rather than waiting for 03:41
```

If this machine only ever had *some* of the parts installed, name them all: `--only` rewrites
the managed crontab block rather than adding to it, so `--only backup` on a server already
running the views and the order-note runner would leave it scheduling nothing else. The
installer says what it is about to drop, but reading it afterwards is the wrong time.

`BACKUP_DIR` must be outside the vault, and the script refuses if it is not: inside, the
archive would sync to every device, be indexed by the watcher, and tomorrow's copy would
contain today's.

**The local copy is not the backup.** A machine that loses its disk loses `~/backups` with
everything else. `BACKUP_OFFSITE_HOOK` names an executable that receives the archive and its
checksum and puts them somewhere else — rclone to a cloud drive, scp to another machine,
whatever this server already does. It fails, the backup fails, and cron says so. A worked
example is in `deploy.env.example`, including the part that is easy to skip: **check the file
is really at the far end**, because an upload command's exit code is a claim about the
command, not about the destination.

## What is in the archive

`vault-YYYY-MM-DD.tar.gz`, plus a `.sha256` beside it, holding the vault as it stood:

- every note and attachment, `.obsidian/` included, so what comes back is a vault and not a
  folder of Markdown;
- `.trash/`, because that is where a deleted note went, and a backup that skipped it would
  omit exactly what you came for;
- `.git/`, the checkpoints, so the restored copy can be walked backwards as well as opened;
- **private folders too.** The checkpoints leave `_PRIVATE/` out on purpose — a commit is an
  audit trail — but a backup that quietly omits something is a trap sprung at the worst
  moment. The consequence: wherever the archive lands is exactly as sensitive as the vault.

Left out: Obsidian's UI state (`workspace*`), its own recovery snapshots
(`file-recovery*` — large, and already a recovery mechanism of its own), and the half-written
`*.tmp` / `*.partial` / `~$*` files editors and sync leave behind. Add more with
`BACKUP_EXCLUDE`.

## The restore

Never over the live vault. The script refuses that, and refuses a directory that is not
empty; making a restored copy *become* the vault is the separate, manual procedure below.

```sh
~/.local/share/hvk/deploy-bin/vault-restore.sh ~/backups/vault-2026-08-24.tar.gz ~/restore-test
```

It checks the archive against its checksum, extracts, and then — the part that matters —
checks that what came back is a working vault rather than a directory of files. This is the
rehearsal, verbatim apart from the paths:

```
archive
  ~/backups/vault-2026-08-24.tar.gz (39M)
  checksum ok
  1745 entries

restoring into ~/restore-rehearsal
  588 files on disk, 47M
  .obsidian/ is there, so it is a vault and not just a folder of notes

git history
  intact (16 checkpoints)
  last checkpoint: 6e9c139 2026-08-24 auto: 2026-08-24 19:00
  in the archive but not in that history: 0 files

against the live vault
  0 changed since the backup, 0 added since, 0 gone from the vault

indexing the restored copy
  files            585
  notes            278
  attachments      307
  links            928
  broken_links     9
  tasks            170
  headings         2746
  parse_errors     1
```

`hvk` indexing the restored copy is the real assertion. Files on disk prove tar worked; 278
notes, 928 links and 170 tasks coming back out of a fresh index prove the vault did — and
those are the live index's numbers to the digit, including the nine broken links and the one
note with invalid frontmatter that the vault has had all along. A restore that quietly fixed
them would be the more worrying result.

If the archive came from off-site, fetch it **and** its `.sha256`, and let the script compare
them. A truncated download extracts far enough to look convincing.

## Making a restored copy the live vault

The dangerous one, and deliberately by hand. Order matters more than speed: **stop the syncer
first**, or Sync will carry every step of this to every device while you are still deciding
whether it worked.

```sh
systemctl --user stop obsidian-headless hvk-watch hvk-agent   # sudo systemctl, if --system
mv ~/vault ~/vault.broken          # keep it. It is evidence, and it may hold the newest copy
mv ~/restore-test ~/vault
hvk --vault ~/vault rebuild        # the index describes a vault that no longer exists
systemctl --user start obsidian-headless hvk-watch hvk-agent
```

Then watch the first sync rather than walking away: it reconciles a vault that has just moved
backwards in time against a service holding the newer state, and how that lands is Sync's
decision, not this project's. Keep `~/vault.broken` until you are sure — a restore of last
night's archive gives up everything written since, and some of it may only exist there.

## The everyday case: one note, one bad half-hour

Most of what looks like a disaster is not, and does not need the archive at all. The
checkpoints are right there in the vault:

```sh
git -C ~/vault log --oneline -20                    # what the last ten hours looked like
git -C ~/vault log --diff-filter=D --name-only      # when did that note disappear
git -C ~/vault show <sha>:"Some/Note.md" > /tmp/x   # read it without changing anything
git -C ~/vault restore --source <sha> -- "Some/Note.md"
```

`--source <sha>` on one path is the tool for this. Resetting the whole vault is not: sync
would then propagate a mass reversion, which is the failure you were recovering from.

## What has not been rehearsed

**Obsidian Sync's own version history.** It is a real fourth copy, kept by Obsidian, and it
can restore a deleted note or roll a vault back from the app — but reaching it needs the
credentials and a GUI or the beta CLI, and exercising it on this server means asking a live
syncer to re-register or re-download a vault it is currently serving. That is a rehearsal
that can break the thing it is rehearsing, so it has not been run. Treat it as a fourth
option, not as one of the three above.

## Noticing that it stopped

The newest file in `BACKUP_DIR` is when the backup last worked; nothing else needs to be
written down. Any monitoring already on the machine can say so out loud:

```sh
find ~/backups -name 'vault-*.tar.gz' -mtime -2 | grep -q . || echo "no vault backup in 2 days"
```

Failures are already loud — the script exits non-zero and cron mails whatever it printed —
but only if cron can mail. That check does not care.

## The rehearsal

Run on the deployment server (Ubuntu 24.04, ARM64) on **2026-08-24**, against the live vault
while sync, the watcher and the agent were all running, into a directory beside it:

| | |
|---|---|
| Archive | 39 MB gzip, 1745 entries — 1043 of them the git history — from a 47 MB vault |
| Backup took | 2.1 s, with sync and the watcher running |
| Restore took | 2.4 s, indexing included |
| Came back | 588 files, 16 checkpoints, history intact under `git fsck` |
| Indexed to | 585 files, 278 notes, 307 attachments, 928 links, 170 tasks — the live index's numbers exactly |
| Compared to the live vault | `diff -rq` over both trees: no difference at all |
| Left behind | nothing. The restored copy and the archive were removed, the crontab and the configuration untouched |

What it does **not** show is the off-site half: at the time of the rehearsal no destination was
configured, so the archive was restored from the same disk it was written to. Restoring one
that has made the round trip is the next thing worth doing, and the only thing that tests the
hook.

One rehearsal is not a schedule. The value expires: the next time this procedure changes, or
the next time the vault does something new — a folder that stops syncing, an attachment store
that grows past what a nightly tar can carry — it is worth an hour to run it again.
