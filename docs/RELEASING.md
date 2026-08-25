# Releasing

How a version of `headless-vault-kit` reaches PyPI, and the one thing about it that cannot be
undone.

## The rule that shapes everything else

**A version number is never reusable.** Publish `0.1.0` with a bug and you cannot replace it: you
publish `0.1.1`, and the bad one stays downloadable for anyone who pinned it. Deleting a release
is possible and is not an undo — whoever installed it has it.

Everything below exists because of that sentence. The suite runs before the build, the build is
installed into a clean environment and asked a real question before anything is uploaded, and the
tag has to agree with `pyproject.toml`.

## Once, before the first release

PyPI is told which workflow may publish, instead of this repository being told a password.
That is [trusted publishing](https://docs.pypi.org/trusted-publishers/): GitHub hands the
workflow a short-lived identity over OIDC, scoped to this repository, this file and this
environment. **There is no API token in this repository and there is not meant to be** — a token
in a secret is a long-lived credential that can be copied, protecting something other people
install.

1. On PyPI, go to *Your projects → Publishing → Add a pending publisher* (a *pending* publisher
   is how a project that does not exist yet is claimed).
2. Fill it in exactly:

   | Field | Value |
   |---|---|
   | PyPI project name | `headless-vault-kit` |
   | Owner | `angelsaez` |
   | Repository name | `headless-vault-kit` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

3. On GitHub, *Settings → Environments → New environment*, named `pypi`. Adding yourself as a
   required reviewer there means a release waits for you to press a button, which is worth it
   for something irreversible.

The distribution is named `headless-vault-kit` and the command it installs is `hvk`. Those are
two different names on purpose: the long one is descriptive and is what `pip` and `uv` resolve;
the short one is what you type.

## Rehearsing, which is not optional

[ADR-0013](adr/0013-a-backup-is-what-you-restored.md) settled this project's view of untested
procedures: *a backup is what you restored*. A release is what you built and installed.

Run the workflow by hand — *Actions → release → Run workflow* — on `main`. Without a tag it
runs the suite, builds, checks the metadata PyPI will render, **installs the wheel into a clean
virtual environment and asks it a question about a vault it has never seen**, and stops. Nothing
is uploaded and no name is claimed.

Locally, the same thing:

```bash
.venv/bin/pip install build twine
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

## Publishing

1. Decide the version and put it in `pyproject.toml`. Below `1.0.0`, a minor bump is where
   anything user-visible changes — a command, a flag, an MCP tool name, the index schema.
2. Add the entry in [`CHANGELOG.md`](CHANGELOG.md), which is the repository's journal and is
   written for a reader, not for a tool.
3. Commit, then tag and push:

   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```

The workflow runs the suite, builds, checks the tag against `pyproject.toml`, installs the wheel
and asks it a question, and only then publishes. If the environment has a required reviewer it
waits for you at the last step.

## Afterwards

Change the install instructions in [`README.md`](../README.md), [`README.es.md`](../README.es.md)
and both guides, which currently say *"not on PyPI yet"* and give the `git+` route. What replaces
them is:

```bash
uv tool install headless-vault-kit
```

`uv tool upgrade headless-vault-kit` updates it; `uv tool uninstall headless-vault-kit` removes
it. Installing from a git URL keeps working and stays documented for anyone who wants an
unreleased commit.

## What is not automated, deliberately

**Bumping the version.** Deciding that a change is a minor rather than a patch is a judgement
about what other people's scripts depend on, and a tool that reads commit prefixes would be
making it by counting words.

**Publishing on every push to `main`.** A tag is a deliberate act, and this is the one operation
here with no undo.
