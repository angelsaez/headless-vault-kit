# kanban

A vault for the example parser adapter (ADR-0017), holding the three cases that matter:

- `Boards/Roadmap.md` — a real Kanban board, written the way the plugin writes one: the
  frontmatter marker, lists as headings, cards as tasks, dates as `@{...}`, and the settings
  block at the bottom in Obsidian's comment syntax.
- `Notes/Design.md` — an ordinary note with headings and tasks. The adapter must not claim it,
  and its tasks must keep their text exactly as written.
- `Notes/Writing about Kanban.md` — a note *about* the format, with the marker line quoted in
  its body. Claiming this one would put an example card in the index as a real task, which is
  the kind of wrong answer nobody thinks to check for.
