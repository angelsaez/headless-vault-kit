# Hooks

Two rules that cannot be enforced from inside `hvk`, because the tool that would break them is
the agent's, not ours: deleting with `rm` instead of moving to `.trash/`, and reaching into a
folder that is none of its business. `hvk guard` answers both as a `PreToolUse` hook
([ADR-0012](../../docs/adr/0012-a-hook-in-front-of-the-agent.md)).

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
