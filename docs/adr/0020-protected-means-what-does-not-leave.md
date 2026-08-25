# 0020 — Protected means what does not leave

**Status:** accepted
**Date:** 2026-08-25
**Phase:** 7

## Context

[ADR-0018](0018-an-mcp-server-that-writes.md) said the MCP server applies the guard's rules
itself, reusing `guard.decide()`, so that "a folder that is protected from the agent is protected
from any client that speaks this protocol". The first time a real client was pointed at a real
vault with `--protect` set, that turned out to be false.

With `--protect "700 - DIARIO"`, this was refused:

```
search  {"query": "el path:\"700 - DIARIO\""}     → protected folder
```

and this was not:

```
search  {"query": "el path:700"}
  → 700 - DIARIO/2026-03-30.md
    "…Terminé de revisar el borrador del informe trimestral…"
```

Neither was `backlinks {"target": "2026-03-30"}`, which resolved a bare note name into the same
folder and reported what linked there.

The cause is not a bug in a rule; it is the rule being the wrong shape for this surface.
[ADR-0012](0012-a-hook-in-front-of-the-agent.md) was written for a `PreToolUse` hook, where
every tool call **names a path** — a `Read`, a `Write`, an `rm`. Refusing calls that name a
protected path was therefore complete there. A query surface reaches a file three other ways:

- a **substring filter** (`path:700`), which names nothing and selects everything containing it;
- a **bare name that resolves** (`backlinks 2026-03-30`), where the path only exists after the
  call has run;
- a **full-text search with no path in it at all** (`search "borrador trimestral"`), which is
  the one no rule about arguments could ever have caught.

The third is what settles the decision. Closing the first two and leaving the third would have
been worse than closing none: `path:700` refused while `search "borrador"` still hands over the
diary is precisely the "protection-that-only-looks-like-protection this project keeps refusing
to ship" — a phrase that is in `guard.py`, about a different rule, written by the same hand that
then shipped this.

## Alternatives

- **Document the limit and change nothing.** Honest, cheap, and consistent with the hook: the
  guard refuses a call that *names* a protected folder and never claimed to redact one that
  stumbles in. It also leaves `--protect` far weaker than its name, on the one surface that
  hands whole snippets of a vault to a language model. The guides would have had to say "this
  will not keep your diary out of an agent's context", at which point the flag is decoration.
- **Filter inside the query layer**, passing protected folders down into `query.py`, the Bases
  runner and DQL. The most thorough option and the most invasive: it changes the CLI too, where
  nobody asked for it and where whoever typed the command already has a shell.
- **Filter what the MCP layer returns.** Chosen. One place, every tool at once, and the CLI
  keeps behaving exactly as it did.

## Decision

**Checking the arguments is not enough, so what leaves is checked too.** After a tool runs, the
answer is walked and every row naming a file inside a protected folder is removed, using the same
`guard.touches()` that decides the argument case. The two questions get one definition of
"inside a protected folder", which is the only way they can agree.

**A row is anything naming a file**, at any depth, under one of a listed set of keys — `path`,
`source`, `target`, `file`, `resolved`, `note`. Deliberately blunt: dropping one row too many is
a far better failure here than letting one through, and a rule written per tool is a rule that
gets forgotten the next time a tool is added. The walk is recursive because rows are not always
at the top — a `dql` answer holds a list of results, each holding its own.

**When the answer *is* the protected thing, the call is refused rather than emptied.** A bare
name that resolves into a protected folder gets the same refusal `note_read` would have given,
naming the reason: *"whichever name it is reached by"*.

**Counters are corrected and the drop is declared.** `total` and `shown` come down with the rows
they count, and the answer gains `hidden: n`. A total still saying ten beside eight rows is the
table that looks right and is not, which [ADR-0005](0005-bases-subset.md) and
[ADR-0016](0016-a-subset-of-a-query-language.md) both refused to ship. And an answer that quietly
hides two matches invites a model to conclude there is nothing there — `hidden: 2` admits that
something exists without saying what, which is a much smaller thing to give away than the answer.

**Every filtered call leaves a line in `hvk.log`**, as every refusal already does (ADR-0014):
`mcp filtered rule=protected tool=search match=1`.

**This makes the MCP surface stricter than the command line, on purpose.** `hvk search` still
returns everything, because the person who typed it has a shell and could have used `grep`. The
difference is who is asking.

## Consequences

**Aggregate counts are not filtered.** `info` reports every note in the vault, protected ones
included, and `tags` counts files without saying which. Recomputing them would mean a second
query on every call, and a count says that something exists without saying anything about it —
which is what `hidden` already says out loud. If that is ever not good enough, the fix is to pass
the protected list into `query.info` and count with a `NOT LIKE`.

**Nothing is protected by default, still.** Unset means the rule does not apply, exactly as in
ADR-0012. This ADR changes what protection *means*, not when it happens.

**The key list will go stale**, like the bypass flags of ADR-0011 and the function map of
ADR-0016. A tool added later that names its file under some new key would return it unfiltered.
There is a test asserting the current keys, which turns "somebody remembers" into "somebody
changes a list a test points at", and that is the most that can be said for it.

**A row is dropped even when only its *link target* is protected.** `links` rows carry
`resolved`, so a link from an ordinary note into a protected folder disappears from the answer
entirely rather than appearing with the target blanked. That hides one true fact about an
unprotected note. It is the safe direction, and it is a real loss of information.

**The scrub runs on every answer when protected folders are set.** Payloads are bounded by the
limits the tools already impose, so the cost is small, but it is not nothing and it grows with
the size of a result set rather than with the number of protected folders.

**This ADR exists because a claim in ADR-0018 was checked and was wrong.** That is worth leaving
in the record: the boundary was described accurately in the abstract and implemented against the
wrong shape of call, and nothing but pointing a real client at a real vault with a real protected
folder would have shown it.
