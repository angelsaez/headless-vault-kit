# Hooks

Three rules that cannot be enforced from inside `hvk`, because the tool that would break them
is the agent's, not ours: deleting with `rm` instead of moving to `.trash/`, reaching into a
folder that is none of its business, and writing to a path outside the vault altogether.
`hvk guard` answers all three as a `PreToolUse` hook
([ADR-0012](../../docs/adr/0012-a-hook-in-front-of-the-agent.md),
[ADR-0014](../../docs/adr/0014-blocked-and-written-down.md)).

The third needs no configuration: the vault is already known, and a `Write`, `Edit` or
`NotebookEdit` whose path resolves outside it is refused. Reads are not — an agent reading a
man page is doing its job. `Bash` is not judged on where it might write either, because a
redirection cannot be found reliably in a command line and a rule that caught only the easy
spellings would read as protection while providing none.

**Nothing here installs itself.** The agent's `settings.json` belongs to whoever runs the
agent; this is the snippet to paste, and the paths in it are yours to fill in.

## The snippet

In `~/.claude/settings.json`, merged with whatever is already there — replacing that file
wholesale would drop the settings the machine already depends on:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Write|Edit|Read|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "hvk --vault /home/CHANGE-ME/vault guard --protect _PRIVATE"
          }
        ]
      }
    ]
  }
}
```

`--protect` takes one folder and can be repeated; `HVK_PROTECTED` takes a comma-separated list
instead. There is no default: unset means the rule does not apply, because which folders are
private is nobody's business but yours.

Use the absolute path to `hvk` if the agent's `PATH` does not include it — `command -v hvk`
gives you the value. A hook that cannot be found is a hook that silently does nothing.

## Checking it before trusting it

The command is the whole thing, so it can be tried by hand:

```sh
echo '{"tool_name":"Bash","tool_input":{"command":"rm note.md"}}' | hvk --vault ~/vault guard
echo '{"tool_name":"Read","tool_input":{"file_path":"_PRIVATE/keys.md"}}' \
    | hvk --vault ~/vault guard --protect _PRIVATE
echo '{"tool_name":"Bash","tool_input":{"command":"mv note.md .trash/"}}' | hvk --vault ~/vault guard
```

The first two print a refusal with its reason. The third prints **nothing**, which is how a
hook allows something.

## What this is not

A speed bump, not a sandbox. An agent with a shell can write a script that deletes a file
without any of the words this looks for. A real boundary is the operating system's — a user
without write access, or a container. This stops the ordinary mistake and points it at the
trash, which is worth having and is not the same thing as safety.

## What it leaves behind

Two files, both in the index directory — outside the vault, so they neither sync nor wake the
watcher (ADR-0002). `hvk doctor` prints where that is.

| File | What it is |
|---|---|
| `hvk.log` | One line per refusal: the rule that fired and what it matched. Rotates at 256 KB, one generation |
| `guard-last-run` | Empty. Its timestamp is the last time the hook ran at all |

```sh
tail -5 ~/.local/share/hvk/<vault>-<hash>/hvk.log
2026-08-25T04:41:09Z guard deny rule=outside-vault tool=Write match=/home/you/.ssh/authorized_keys
2026-08-25T04:41:22Z guard deny rule=delete tool=Bash match=rm
```

**The command itself is never recorded** — a command line can carry a token, and a log that
holds secrets is a second thing to guard. What is recorded is which rule fired and what it
matched, which is what an audit actually needs.

`guard-last-run` exists because the log cannot answer the question people actually have. A
guard that has refused nothing and a guard that was never wired in look identical from the
log, and pasting a snippet into a settings file is exactly the kind of step that gets half
done. If that file is missing, the hook has never run.

## What this does *not* bound

The interactive session's own permissions. Which tools it may use, what it asks about before
doing, whether it runs with `--dangerously-skip-permissions` at all: those live in the agent's
settings, they belong to whoever runs the agent, and this project does not edit that file
(ADR-0006). The hook is what hvk contributes to that session — a boundary the vault's own
content cannot talk its way past — and it is worth being clear that it is not a substitute for
the rest. The runner's side of that question is answered instead by the permission profiles in
[`../profiles/`](../profiles/), which every order-note must name (ADR-0009, ADR-0011).
