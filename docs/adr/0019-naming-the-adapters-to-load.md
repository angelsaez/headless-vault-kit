# 0019 — Naming the adapters to load

**Status:** accepted
**Date:** 2026-08-25
**Phase:** 7

## Context

[ADR-0017](0017-a-parser-interface-extracted-from-two.md) published a parser interface and
claimed an adapter could live outside this repository, registering itself by being imported. The
claim was true and useless, because it left out the part that matters: **something has to import
it.**

An adapter in this repository is one line in `hvk.parse.BUILT_IN`. An adapter in somebody else's
package calls `register()` at import time — and nothing in `hvk scan`, or in any other command,
ever imports it. So the only way to reach one was to stop using the `hvk` command and drive the
package from Python code of your own. For a tool whose entire surface is a CLI, that is not an
extension point. It is a gap with documentation in front of it.

The failure it produces is the quiet kind. A file whose format nothing claims is not an error:
it is indexed as an attachment, with a name, a size and a hash, exactly as a PNG is. So the
symptom of "my adapter never loaded" is a vault that indexes cleanly, reports no errors, and is
missing everything that adapter would have contributed.

ADR-0017 also refused entry-point discovery, and that refusal stands. It refused it on trust, not
on cost — fifteen lines of standard library — and the reasoning has not changed. What changed is
that refusing discovery while providing no alternative left nothing at all.

## Alternatives

- **Entry points**, the standard Python mechanism: a package declares `[project.entry-points
  ."hvk.parsers"]`, and `hvk scan` sweeps the installed distributions and imports whatever it
  finds. Best ergonomics by a distance — `pip install` and it works, no configuration. It also
  means every scan imports and executes any package that has claimed the group name, on a
  machine where an agent works over somebody's notes around the clock. The thing being installed
  need not even be a parser to get that reach. Rejected again, and for the same reason.
- **A `--parser` command-line flag.** Fits the pattern of `--protect` and `--dir`. It is also
  per-invocation, and which formats an installation can read is not a per-invocation fact: it
  would have to be repeated on `scan`, `rebuild`, `watch`, `verify`, `views`, `mcp` and every
  ad-hoc command, and forgetting it once produces an index missing rows rather than an error.
- **A configuration file.** This project has no configuration file, deliberately, and one
  introduced to hold a single list would then attract everything else.
- **Leave it.** Defensible right up to the first person who writes an adapter, at which point
  the answer is "write a Python wrapper around our CLI", which nobody does.

## Decision

**`HVK_PARSERS` names the modules to import, and nothing else is loaded.** A comma- or
space-separated list, read once per command, before anything reads the vault:

```bash
HVK_PARSERS=hvk_excalidraw,hvk_sketch hvk scan
```

Each name is imported, which runs its `register()` calls. Nothing is searched for, and nothing
loads that a person did not name. That is the whole difference from entry points: the operator
declares what may run, rather than the machine's package list declaring it.

**No default**, exactly as with `HVK_JOBS_DIR`, `HVK_JOBS_PROFILES` and `HVK_PROTECTED`: unset
means no adapter loads, never that one is guessed at. Unset also costs nothing — one
`os.environ.get` and no imports — which matters because this runs in front of the guard hook,
on every tool call the agent makes.

**A module that cannot be imported stops the command**, with the module named and the variable
named. The quiet alternative was considered and is worse: an adapter misspelled by one letter
would load nothing, the vault would index cleanly, and every file of that format would be
silently missing what the adapter contributes. Somebody who names a module means it.

**`hvk doctor` reports which parsers are registered**, and fails if a declared one will not
load. This is the check that exists because of how the variable is scoped: it is read per
process, so one set in the watcher's systemd unit and not in your interactive shell means the
two disagree about what a file even *is* — and without somewhere to ask, that difference is
invisible.

## Consequences

**An adapter author's install instructions are two lines, not one.** `pip install` the package,
then add its module name to `HVK_PARSERS` wherever hvk runs — which on a server means editing a
systemd unit. Entry points would have made it one line. That second line is the price of not
executing code nobody asked for, and it is the right way round.

**The variable is per process, and processes disagree.** A watcher unit with `HVK_PARSERS` set
and a cron `hvk verify` without it will genuinely produce different index contents from the same
files, with no error from either. `hvk doctor` can be asked, and the deployment documentation
says to set it in one place — but nothing *enforces* agreement, and this is the sharpest edge
here. If it ever bites, the fix is to record the declared parsers in the index's `meta` table and
refuse to run against an index built with a different set, the way the schema version already
works.

**Nothing validates that a declared module is a parser.** Naming any importable module in
`HVK_PARSERS` imports it, whatever it does. That is inherent — the mechanism *is* "import this,
it will register itself" — and it is why the variable is an operator's decision and not
something a note, a job or an MCP client can influence. None of them can set it.

**Discovery is still available later.** If publishing ever makes entry points worth the trust
question, they can be added beside this without changing the interface: this ADR would be
superseded, not undone.
