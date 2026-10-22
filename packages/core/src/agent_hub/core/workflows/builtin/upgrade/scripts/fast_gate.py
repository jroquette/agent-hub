# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Print the run's repo's fast gate, ``repos[].check_fast`` of the hub's ``hub.json``.

``fast_gate.py --repo <dir> --full <command>``: the cwd is the hub (a script node's default), and
the step runs before any agent of the run, so ``hub.json`` is the one the owner wrote. ``--full``
is the repo's full gate as ``hub step worktree`` printed it. The output is
``{"check_fast", "source", "reason"}``: the repo's ``check_fast`` with ``source`` ``check_fast``
and a blank ``reason``; or, when ``hub.json`` gives none (missing, blank, not text) or cannot be
read (absent, larger than 1 MiB, not JSON, no such repo), the full gate with ``source``
``check`` and the reason, so the run goes on with the slower gate and says why. A blank
``--repo`` or ``--full`` exits 2.
"""

import argparse
import json
import sys
from pathlib import Path

HUB_JSON = "hub.json"
MAX_BYTES = 1024 * 1024
FALLBACK = ": the full check runs instead"


class UnreadableError(Exception):
    """``hub.json`` gives no fast gate; the message is why."""


def read_entry(hub: Path, repo: str) -> dict[str, object]:
    """The ``repos[]`` entry whose ``dir`` is ``repo``."""
    try:
        with (hub / HUB_JSON).open("rb") as handle:
            data = handle.read(MAX_BYTES + 1)
    except OSError as error:
        raise UnreadableError(f"{HUB_JSON} cannot be read") from error
    if len(data) > MAX_BYTES:
        raise UnreadableError(f"{HUB_JSON} is larger than 1 MiB")
    try:
        config = json.loads(data)
    except ValueError as error:
        raise UnreadableError(f"{HUB_JSON} is not JSON") from error
    repos = config.get("repos") if isinstance(config, dict) else None
    if not isinstance(repos, list):
        raise UnreadableError(f"{HUB_JSON} has no repos list")
    for entry in repos:
        if isinstance(entry, dict) and entry.get("dir") == repo:
            return entry
    raise UnreadableError(f"{HUB_JSON} lists no repo {repo}")


def fast_gate(hub: Path, *, repo: str, full: str) -> dict[str, str]:
    try:
        command = read_entry(hub, repo).get("check_fast")
    except UnreadableError as error:
        return {"check_fast": full, "source": "check", "reason": f"{error}{FALLBACK}"}
    if isinstance(command, str) and command.strip():
        return {"check_fast": command, "source": "check_fast", "reason": ""}
    reason = f"{HUB_JSON} gives {repo} no check_fast{FALLBACK}"
    return {"check_fast": full, "source": "check", "reason": reason}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="fast_gate.py")
    parser.add_argument("--repo", required=True, help="The repo's dir in hub.json.")
    parser.add_argument("--full", required=True, help="The repo's full gate (hub step worktree).")
    args = parser.parse_args(argv)
    if not args.repo.strip() or not args.full.strip():
        parser.error("--repo and --full must not be blank")
    print(json.dumps(fast_gate(Path.cwd(), repo=args.repo, full=args.full)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
