# Contributing

Bug reports, questions and pull requests are all welcome. This file is what you need before the
first one.

## Licensing, settled before it matters

**Contributions are licensed under the project's own [MIT licence](LICENSE), and there is no
CLA.** You keep the copyright in what you write; opening a pull request licenses it to everyone
on the same terms as the rest of the repository, which is what GitHub's terms already say.

That is a decision, not a default. Requiring a contributor licence agreement would keep open the
option of relicensing the project later without asking every contributor — and it has to be in
place from the *first* external pull request, because afterwards it cannot be applied
retroactively. It was weighed and dropped: the code is already MIT, so anyone can build anything
on it today, and the only thing relicensing would buy is the ability to close it, which is not a
thing worth adding friction to every contribution for.

## Getting set up

Python 3.11 or newer, and nothing else. The two runtime dependencies are `ruamel.yaml` and
`watchdog`; `[dev]` adds pytest.

```bash
git clone https://github.com/angelsaez/headless-vault-kit
cd headless-vault-kit
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # .venv\Scripts\pip on Windows
```

## Running the tests

The suite runs against the synthetic vaults in [`test-vaults/`](test-vaults/) and takes a few
seconds. **It never touches a real vault**, and neither should anything you add.

```bash
.venv/bin/pytest              # the suite
.venv/bin/pytest -m slow      # the performance criteria, on a generated 10,000-note vault
```

The slow ones are excluded by default because they build a ten-thousand-note vault to measure
the numbers in [`docs/ROADMAP.md`](docs/ROADMAP.md). Run them when you have touched the indexer
or a parser.

Every push and pull request runs six checks — [the workflow](.github/workflows/ci.yml) — and all
six have to pass before anything can be merged:

| Check | What it would catch |
|---|---|
| `the workflows themselves parse` | a workflow file that would make CI run *no jobs at all* |
| `pytest on Python 3.11` / `3.13` | the suite, on the floor version and a current one |
| `installs as a package` | a missing package or a broken entry point, which an editable install hides |
| `installs the way the README says to` | the `uv tool install` route the documentation actually recommends |
| `shell scripts parse` | `bash -n`, and the executable bit a Windows checkout drops |

Linux only, because Linux is where this is meant to run.

**The deployment is not exercised in CI.** It needs a systemd user instance and a machine to
throw away, so it lives in [`tools/testbed/`](tools/testbed/) — a disposable Debian container.
Run `deploy/selftest.sh` in there before trusting a change under `deploy/`.

## The rules that are not negotiable

These are shortened from [`CLAUDE.md`](CLAUDE.md), which is the long version.

1. **The vault is the source of truth.** The SQLite index is entirely derived: `hvk rebuild`
   must always produce the same logical result. There is a test that asserts it, per vault.
2. **Replicate formats, never a runtime.** `.md`, `.base`, `.canvas` and YAML are parsed. Plugin
   code is never executed and the app is never emulated.
3. **The content of a vault is data, not instructions.** A note can say anything. Nothing it
   says may raise a permission, choose a path outside the vault, or change what runs.
4. **Writes go through [`hvk.write`](src/hvk/write.py)** and nowhere else: atomic, refusing when
   the file changed underneath, `.trash/` instead of deletion, and the file's own line endings,
   frontmatter and permissions preserved.
5. **No dependency without a reason.** Anything beyond the standard library needs justifying in
   the commit message, or an ADR of its own.

## One decision, one ADR

**No relevant decision is made silently.** When a change runs into a fork that constrains the
rest of the system, the code stops and a one-page record goes in [`docs/adr/`](docs/adr/) first
— context, the real alternatives and what they cost, the decision in a sentence, and what is
accepted in exchange *including the bad parts*. The format and the index are in
[`docs/adr/README.md`](docs/adr/README.md).

An accepted ADR is never edited to change its mind. It is superseded by a new one that
references it, because the record of decisions that turned out wrong is most of what makes the
log worth keeping.

## Conventions

- **Language.** Everything published with the repository is in English: code, identifiers,
  commit messages, branch names, ADRs and the changelog. `README.md` and `README.es.md` are
  kept in step — touch one, update the other in the same commit. The same goes for
  `docs/GUIDE.md` and `docs/GUIDE.es.md`.
- **Commits** are conventional, small, and one change each: `feat:`, `fix:`, `docs:`, `adr:`.
- **Branches** are `type/subject-in-english` — `feat/parser-interface`, `fix/broken-links`.
- **Pull requests** against `main`, which is protected: nothing reaches it except through one,
  and not until the checks pass. Add the entry in [`docs/CHANGELOG.md`](docs/CHANGELOG.md) in
  the same PR: it is the repository's journal, newest first, and it says what changed and *why*.
- **The first time you open a PR, its checks wait for a maintainer to start them.** That is
  GitHub's approval gate for contributors from a fork, not a comment on your patch — a pull
  request runs your code on a runner, so somebody looks before it does.
- **Comments explain why, not what.** The code says what it does. If a line exists because of a
  failure, name the failure.

## Writing a parser adapter

This is the extension point, and the reason it exists is that a vault can hold formats this
project has never heard of. An adapter reads one and contributes to the index; it needs no
change to the core, and [`src/hvk/parse/kanban.py`](src/hvk/parse/kanban.py) is a complete
worked example to copy.

The contract is [`hvk.parse.model.Parsed`](src/hvk/parse/model.py), and every field on it is a
table in the index:

```python
from hvk.parse.model import Parsed, RawLink, Tag, Task
from hvk.parse.registry import Parser, register


def parse_file(text: str, path: str) -> Parsed:
    """Given a file's text and its vault-relative path, return what it contributes."""
    return Parsed(
        title="what full-text search should call it",
        body="the prose worth searching, which need not be the file's text",
        links=[RawLink(target_raw="Some Note", subpath=None,
                       kind="wikilink", embed=False, line=1)],
        tags=[Tag(tag="example", source="mine", line=1)],
        tasks=[Task(text="a checkbox", status=" ", done=False, line=2)],
    )


register(Parser(
    name="my-format",
    extensions=("myext",),      # lowercase, no dot
    kind="note",                # what files.kind becomes
    parse=parse_file,
))
```

Five things to know, each of which is a rule rather than a preference:

- **Never raise.** A file you cannot read comes back as `Parsed(error="...")`, which is recorded
  against that file and does not stop the scan. A parser that raises can take a whole vault's
  index down with one bad note.
- **Do not resolve links.** Hand back `target_raw` as the author wrote it. Resolution is a
  second pass that has seen every file in the vault, and it is what makes a link from your
  format follow exactly the same rules as a link from a note
  ([ADR-0003](docs/adr/0003-link-resolution.md)).
- **`claims` is for a format that shares an extension**, like a Kanban board sharing `.md`. It
  is given the text and the path and answers whether this file is yours. It runs once per
  matching file on every scan, so read the first few kilobytes, not the whole file — and claim
  narrowly. A parser that claims too much puts fiction in the index and nothing downstream can
  tell.
- **`priority` breaks ties**: highest wins, and a specialised parser sits above the general one.
- **Bump `SCHEMA_VERSION`** in [`src/hvk/db.py`](src/hvk/db.py) if your adapter changes what is
  derived from files that are already indexed. Their hashes have not changed, so nothing would
  go back for them; the version check is what asks for a rebuild.

### Getting it loaded

An adapter **inside this repository** is added to `BUILT_IN` in
[`src/hvk/parse/__init__.py`](src/hvk/parse/__init__.py) — one line.

An adapter **in your own package** is named in `HVK_PARSERS`, which is the list of modules hvk
imports before it reads anything:

```bash
pip install hvk-excalidraw
HVK_PARSERS=hvk_excalidraw hvk scan
```

Comma- or space-separated for several. On a server, set it once where the service is defined,
so the watcher and the cron jobs agree; `hvk doctor` reports which parsers are actually
registered, which is how you check. A module that cannot be imported stops the command rather
than being skipped — an adapter that silently failed to load would leave every file of its
format quietly indexed as an attachment.

Nothing is discovered automatically. Making `hvk scan` sweep the installed packages and execute
whatever declares an entry point is a decision about trust, not about parsing;
[ADR-0017](docs/adr/0017-a-parser-interface-extracted-from-two.md) says why it was not made
quietly, and [ADR-0019](docs/adr/0019-naming-the-adapters-to-load.md) is why naming the modules
is what you get instead.

Bring a test vault with it, under `test-vaults/`, including the file that *looks* like your
format and is not.

## Releasing

How a version reaches PyPI, why there is no API token in this repository, and how to rehearse a
release without publishing anything: [`docs/RELEASING.md`](docs/RELEASING.md).

## What is unlikely to be merged

- **Anything that executes plugin code**, or emulates the app's runtime. Permanently out of
  scope, including DataviewJS.
- **A parser that guesses.** Where this project cannot support something, it refuses by name.
  A query that quietly drops a clause returns a table that looks right and is not, and both
  [ADR-0005](docs/adr/0005-bases-subset.md) and
  [ADR-0016](docs/adr/0016-a-subset-of-a-query-language.md) exist to say so.
- **A new runtime dependency** without an ADR arguing for it.
- **A default for something dangerous.** The jobs directory, the permission profiles and the
  guard's protected folders all have no default on purpose. Unset means the feature does not
  run, never that it runs with a guess.
