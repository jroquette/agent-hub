"""Release check (ADR 0013): agent-hub-cli and the agent-hub meta-package share one version.

With ``--tag=<name>``, the tag must also be ``v`` + that version. Stdlib only and no
``scripts``/``agent_hub`` import, so the release job runs it by path without syncing the
workspace: ``uv run --no-project python scripts/check_release.py --tag="$TAG"``. ``make lockstep``
runs it as ``python -m scripts.check_release``. It reads files only: no network, no git.
"""

import argparse
import json
import re
import sys
import tomllib
from collections.abc import Sequence
from itertools import accumulate
from pathlib import Path

CLI_PYPROJECT = "packages/cli/pyproject.toml"
META_PYPROJECT = "packages/agent-hub/pyproject.toml"
# ASCII digits only (``\d`` also matches other scripts' digits); ``fullmatch``, because ``$``
# also matches before a final newline.
RELEASE_TAG = re.compile(r"v([0-9]+\.[0-9]+\.[0-9]+)")
# The most characters of an untrusted value that a line repeats.
ECHO_LIMIT = 80
REPO_ROOT = Path(__file__).resolve().parent.parent
_TAG_FORM_PROBLEM = "must be v<major>.<minor>.<patch> with ASCII digits"
# One character of escaped text, an escape sequence (``\n``, ``\u00e9``) counting as one. The
# same rule as agent_hub.core.hub_config.versions, copied to stay stdlib only.
_ESCAPED_CHARACTER = re.compile(r"\\(?:u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|U[0-9a-fA-F]{8}|.)|.", re.S)
_BOTH_FILES = f"{CLI_PYPROJECT} and {META_PYPROJECT}"


class _CheckFailedError(Exception):
    """A failed check; the message is the line to print."""


def shown(value: str | None) -> str:
    """An untrusted value on one line, JSON-quoted and escaped; cut to ECHO_LIMIT with ``…``."""
    text = json.dumps(value)
    if len(text) <= ECHO_LIMIT:
        return text
    characters = _ESCAPED_CHARACTER.findall(text)
    ends = accumulate(len(character) for character in characters)
    kept = (
        character for character, end in zip(characters, ends, strict=True) if end <= ECHO_LIMIT - 1
    )
    return "".join(kept) + "…"


def read_version(path: Path) -> str | None:
    """``project.version`` of a ``pyproject.toml`` when it is a string, else None."""
    with path.open("rb") as file:
        document = tomllib.load(file)
    project = document.get("project")
    if not isinstance(project, dict):
        return None
    version = project.get("version")
    return version if isinstance(version, str) else None


def lockstep_problem(*, cli: str | None, meta: str | None) -> str | None:
    """Why the cli and meta versions are not one version, or None when they are."""
    if cli is not None and cli == meta:
        return None
    return (
        f"version lockstep: {CLI_PYPROJECT} {_has(cli)}, {META_PYPROJECT} {_has(meta)};"
        " they must be equal"
    )


def tag_problem(tag: str, *, version: str) -> str | None:
    """Why ``tag`` does not name the release of ``version``, or None when it does."""
    match = RELEASE_TAG.fullmatch(tag)
    if match is None:
        return _TAG_FORM_PROBLEM
    if match.group(1) != version:
        return f"must be v + the version {shown(version)} of {_BOTH_FILES}"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Check the versions under ``--root`` and the ``--tag``; print one line, 1 on a problem."""
    arguments = _parser().parse_args(argv)
    tag: str | None = arguments.tag
    try:
        version = _checked_version(Path(arguments.root), tag=tag)
    except _CheckFailedError as problem:
        prefix = "" if tag is None else f"tag {shown(tag)}: "
        print(f"{prefix}{problem}", file=sys.stderr)
        return 1
    if tag is None:
        print(f"version lockstep ok: {_BOTH_FILES} are {shown(version)}")
    else:
        print(f"tag {shown(tag)} ok: equals the version {shown(version)} of {_BOTH_FILES}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="the pushed tag; pass it as --tag=<name>")
    parser.add_argument("--root", default=str(REPO_ROOT), help="repo root (default: this repo)")
    return parser


def _checked_version(root: Path, *, tag: str | None) -> str:
    """The version cli and meta share (and the tag names); raises _CheckFailedError otherwise."""
    # The form first: a malformed tag fails the same way whatever the files hold.
    if tag is not None and RELEASE_TAG.fullmatch(tag) is None:
        raise _CheckFailedError(_TAG_FORM_PROBLEM)
    cli = _read(root, CLI_PYPROJECT)
    meta = _read(root, META_PYPROJECT)
    problem = lockstep_problem(cli=cli, meta=meta)
    if problem is not None or cli is None:
        raise _CheckFailedError(problem)
    problem = None if tag is None else tag_problem(tag, version=cli)
    if problem is not None:
        raise _CheckFailedError(problem)
    return cli


def _read(root: Path, relative: str) -> str | None:
    try:
        return read_version(root / relative)
    except OSError as error:
        reason = error.strerror or type(error).__name__
        raise _CheckFailedError(f"{relative}: cannot read: {shown(reason)}") from error
    except ValueError as error:  # tomllib.TOMLDecodeError, or UnicodeDecodeError on bad UTF-8
        raise _CheckFailedError(f"{relative}: cannot read: {shown(str(error))}") from error


def _has(version: str | None) -> str:
    return "has no project.version" if version is None else f"has {shown(version)}"


if __name__ == "__main__":
    sys.exit(main())
