# Claude Code skills

Skills that teach an agent how to work with a vault through this toolkit. They ship here so
they can be versioned with the commands they describe; Claude Code loads them from its own
skills directory, so installing one means putting it where the agent will look.

| Skill | What it is for |
|---|---|
| [`vault-queries`](vault-queries/SKILL.md) | Answering questions about a vault through the `hvk` index instead of reading notes one by one |

## Installing

Copy or symlink the skill into the agent's skills directory. A symlink is preferable on the
server, so that a `git pull` updates the skill without a second step:

```bash
mkdir -p ~/.claude/skills
ln -s "$PWD/skills/vault-queries" ~/.claude/skills/vault-queries
```

To scope it to one project instead of the whole account, use `.claude/skills/` inside that
project. Either way, `hvk` has to be on the agent's `PATH`.

## Writing another one

A skill is a directory holding a `SKILL.md` whose frontmatter carries a `name` and a
`description`. The description is what decides whether the skill gets loaded at all, so it
should name the situations that call for it — the questions a user would actually ask — not
just the tool it wraps.

Keep the body about *when* to reach for something and *what to be careful about*. The
commands themselves already have `--help`; a skill that only restates it earns nothing.
