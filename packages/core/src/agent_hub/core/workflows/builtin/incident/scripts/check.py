# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Run each hypothesis's read-only check; print the results as one JSON object.

A check is an argv list that an agent wrote after reading untrusted text, so it runs only when
``refusal`` finds nothing: no shell; ``argv[0]`` one of ``PROGRAMS``; for git, ``argv[1]`` one of
``GIT_SUBCOMMANDS`` (no global option before it) and no option starting with one of
``GIT_OPTIONS`` (nor an abbreviation of one, nor ``O`` in a short-option cluster:
``git grep -O`` runs a pager);
for tail, no follow option; every argument, and its part after the first ``=``, relative and
inside the checkout (no leading ``/`` or ``~``, no ``..`` segment, no ``/`` or ``~`` in a
short-option cluster); 1 to ``MAX_ELEMENTS`` elements of at most ``MAX_ELEMENT`` characters,
none holding a control character. git runs with ``GIT_PREFIX`` (no pager, fsmonitor, hooks or
external diff), and its diff family without ext-diff or textconv. ``child_env`` builds the
child's environment from nothing, so no token or credential of the parent passes.

Residual risk (accepted; the repos are the project's own and the record stays local): cat, head
and grep follow a symlink committed in the repo to outside the checkout, and the repo's own
``.git/config`` still applies.
"""

from __future__ import annotations

import re
import sys

PROGRAMS = frozenset({"git", "grep", "test", "ls", "cat", "head", "tail", "wc"})
GIT_SUBCOMMANDS = frozenset(
    {
        "log",
        "show",
        "diff",
        "grep",
        "blame",
        "ls-files",
        "ls-tree",
        "cat-file",
        "rev-parse",
        "merge-base",
        "rev-list",
    }
)
# Options that run another program, write a file or leave the repository.
GIT_OPTIONS = (
    "output",
    "open-files-in-pager",
    "ext-diff",
    "textconv",
    "filters",
    "exec",
    "upload-pack",
    "git-dir",
    "work-tree",
    "no-index",
)
GIT_PREFIX = (
    "git",
    "-c",
    "core.pager=cat",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "diff.external=",
    "--no-pager",
)
# Turned off explicitly where git turns them on by default.
GIT_DEFAULTS_OFF = {
    "log": ("--no-ext-diff", "--no-textconv"),
    "show": ("--no-ext-diff", "--no-textconv"),
    "diff": ("--no-ext-diff", "--no-textconv"),
    "blame": ("--no-textconv",),
}
MAX_ELEMENTS = 16
MAX_ELEMENT = 256
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _long_name(argument: str) -> str | None:
    """A long option's name (``--name[=value]``), else ``None``; ``--`` alone has none."""
    if not argument.startswith("--") or argument == "--":
        return None
    return argument[2:].split("=", 1)[0]


def _cluster(argument: str) -> str | None:
    """A short-option cluster's letters and attached value (``-nO``), else ``None``."""
    if argument.startswith("-") and not argument.startswith("--") and len(argument) > 1:
        return argument[1:]
    return None


def _outside(argument: str) -> bool:
    """Whether ``argument``, or its part after the first ``=``, may leave the checkout."""
    parts = [argument]
    if "=" in argument:
        parts.append(argument.split("=", 1)[1])
    for part in parts:
        if part.startswith(("/", "~")) or ".." in part.split("/"):
            return True
    cluster = _cluster(argument)
    return cluster is not None and ("/" in cluster or "~" in cluster)


def _shape_refusal(argv: object) -> str | None:
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        return "refused: the check is not an argv list of strings"
    if not 1 <= len(argv) <= MAX_ELEMENTS:
        return f"refused: the check has {len(argv)} elements, not 1 to {MAX_ELEMENTS}"
    for item in argv:
        if len(item) > MAX_ELEMENT:
            return f"refused: an element is over {MAX_ELEMENT} characters"
        if CONTROL.search(item):
            return "refused: an element holds a control character"
    return None


def _git_refusal(argv: list[str]) -> str | None:
    if len(argv) < 2 or argv[1] not in GIT_SUBCOMMANDS:
        return "refused: not an allowed git subcommand (log, show, diff, grep, blame, ...)"
    for argument in argv[2:]:
        name = _long_name(argument)
        if name and any(
            option.startswith(name) or name.startswith(option) for option in GIT_OPTIONS
        ):
            return f"refused: git option {argument.split('=', 1)[0][:60]!r}"
        cluster = _cluster(argument)
        if cluster is not None and "O" in cluster:
            return "refused: git option -O (runs a pager)"
    return None


def _tail_refusal(argv: list[str]) -> str | None:
    for argument in argv[1:]:
        name = _long_name(argument)
        cluster = _cluster(argument)
        if (name and "follow".startswith(name)) or (cluster and ("f" in cluster or "F" in cluster)):
            return "refused: tail may not follow a file"
    return None


def refusal(argv: object) -> str | None:
    """Why the check ``argv`` may not run, or ``None`` when it may (at most 200 characters)."""
    shaped = _shape_refusal(argv)
    if shaped is not None or not isinstance(argv, list):
        return shaped
    if argv[0] not in PROGRAMS:
        return f"refused: program {argv[0][:40]!r} is not one of {', '.join(sorted(PROGRAMS))}"
    if argv[0] == "git" and (refused := _git_refusal(argv)) is not None:
        return refused
    if argv[0] == "tail" and (refused := _tail_refusal(argv)) is not None:
        return refused
    for argument in argv[1:]:
        if _outside(argument):
            return f"refused: path {argument[:60]!r} leaves the checkout"
    return None


def command(argv: list[str]) -> list[str]:
    """The argv to run for an allowed check: git with its safe prefix, others as they are."""
    if argv[0] != "git":
        return list(argv)
    return [*GIT_PREFIX, argv[1], *GIT_DEFAULTS_OFF.get(argv[1], ()), *argv[2:]]


def child_env(path: str, home: str) -> dict[str, str]:
    """The check's whole environment, built from nothing: no token or credential passes."""
    return {
        "PATH": path,
        "LANG": "C.UTF-8",
        "HOME": home,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "PAGER": "cat",
    }


def main(argv: list[str]) -> int:
    print("check.py: not implemented yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
