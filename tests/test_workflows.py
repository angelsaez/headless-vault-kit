"""The CI workflows have to parse, and their shell has to be shell.

This exists because of a specific failure. A `run:` block was written with a raw newline inside
a single-quoted shell string:

    printf '# One

    Links to [[Two]].
    ' > /tmp/uv-vault/One.md

which is not valid YAML at all. GitHub answered with **"No jobs were run"** and a red mark on
every push — not one failing job, *no* jobs: not the tests, not the package check, nothing. The
file that reports whether this project is healthy had stopped being able to report anything, and
the only signal was an email that did not say why.

A workflow cannot test itself once it is broken. So it is checked from here, where the suite
runs on a laptop before anything is pushed, and `ruamel.yaml` is already a dependency.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from ruamel.yaml import YAML, YAMLError

WORKFLOWS = sorted((Path(__file__).resolve().parent.parent / ".github" / "workflows").glob("*.yml"))


def load(path: Path) -> dict:
    return YAML(typ="safe").load(path.read_text(encoding="utf-8"))


def test_there_are_workflows_to_check():
    """A glob that quietly matches nothing would make every test below pass forever."""
    assert [p.name for p in WORKFLOWS] == ["ci.yml", "release.yml"]


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_a_workflow_parses(path):
    """The whole of the failure this file exists for. Everything else here is a detail."""
    try:
        document = load(path)
    except YAMLError as exc:
        pytest.fail(f"{path.name} is not valid YAML, so GitHub will run no jobs at all:\n{exc}")
    assert isinstance(document, dict)


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_a_workflow_has_jobs_with_steps(path):
    document = load(path)
    jobs = document.get("jobs")
    assert jobs, f"{path.name} defines no jobs"
    for name, job in jobs.items():
        assert job.get("runs-on"), f"{path.name}: {name} says nothing about where it runs"
        assert job.get("steps"), f"{path.name}: {name} has no steps"


def _steps(document: dict):
    for name, job in document.get("jobs", {}).items():
        for step in job.get("steps", []):
            yield name, step


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_a_step_is_either_an_action_or_a_command(path):
    for job, step in _steps(load(path)):
        assert ("uses" in step) != ("run" in step), \
            f"{path.name}: a step of {job} is neither an action nor a command, or is both"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_something(path):
    """`uses: foo/bar` with no ref is whatever the default branch holds today. Every reference
    here names a version, and the ones that matter most name an exact one."""
    for job, step in _steps(load(path)):
        if "uses" not in step:
            continue
        assert "@" in step["uses"], f"{path.name}: {job} uses {step['uses']} with no version"


def test_the_release_workflow_pins_exact_versions():
    """It ends in `id-token: write` and publishes something other people install. A floating
    major is whatever was pushed under that tag this morning.

    `pypa/gh-action-pypi-publish@release/v1` is the exception its own documentation asks for.
    """
    exact = re.compile(r"@v\d+\.\d+\.\d+$")
    allowed = {"pypa/gh-action-pypi-publish@release/v1"}
    for job, step in _steps(load(Path(__file__).resolve().parent.parent
                                / ".github" / "workflows" / "release.yml")):
        uses = step.get("uses")
        if uses is None or uses in allowed:
            continue
        if uses.startswith("actions/checkout") or uses.startswith("actions/setup-python"):
            continue        # GitHub's own, floating majors they do maintain
        assert exact.search(uses), f"release.yml: {job} uses {uses}, which is not an exact version"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_command_is_valid_shell(path):
    """`bash -n` on each `run:`, which is what the `scripts` job already does to `deploy/`.
    A workflow's shell deserves the same reading its scripts get.

    Note what this does *not* do: count quotes. A first version of this file did, and it failed
    on an apostrophe inside a shell comment while catching nothing -- the quotes in the bug that
    started all this balanced perfectly, across the lines they should not have spanned. The
    parser above is the check that matters; this one is for shell that parses as YAML and still
    is not shell.
    """
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if bash is None:                                    # pragma: no cover - platform-specific
        pytest.skip("no bash on this machine; CI is Linux and always has one")

    for job, step in _steps(load(path)):
        command = step.get("run")
        if not command:
            continue
        # ${{ ... }} is GitHub's own substitution and means nothing to a shell, so it is
        # replaced with a harmless word rather than making every matrix step fail to parse.
        script = re.sub(r"\$\{\{[^}]*\}\}", "x", command)
        done = subprocess.run([bash, "-n"], input=script, text=True, capture_output=True)
        assert done.returncode == 0, \
            f"{path.name}: a command in {job} is not valid shell:\n{done.stderr}"
