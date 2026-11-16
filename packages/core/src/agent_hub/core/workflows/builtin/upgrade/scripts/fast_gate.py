# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Print the run's repo's fast gate, ``repos[].check_fast`` of the hub's ``hub.json``.

``fast_gate.py --config <json> --repo <dir> --full <command>``: ``--config`` is what ``hub step
config`` printed (the workflow's ``config`` node, which reads ``hub.json`` before any agent of the
run, so the values are the ones the owner wrote; this script opens no file). ``--full`` is the
repo's full gate as ``hub step worktree`` printed it. The output is
``{"check_fast", "source", "reason"}``: the repo's ``check_fast`` with ``source`` ``check_fast``
and a blank ``reason``; or, when ``hub.json`` gives none (missing, blank, not text) or the config
cannot be read (larger than 1 MiB, not JSON, no such repo), the full gate with ``source``
``check`` and the reason, so the run goes on with the slower gate and says why. A blank
``--config``, ``--repo`` or ``--full`` exits 2.
"""

import argparse
import json
import sys

MAX_BYTES = 1024 * 1024
FALLBACK = ": the full check runs instead"


class UnreadableError(Exception):
    """``hub.json`` gives no fast gate; the message is why."""


def read_entry(config: str, repo: str) -> dict[str, object]:
    """The ``repos[]`` entry whose ``dir`` is ``repo``, from ``hub step config``'s output."""
    if len(config.encode()) > MAX_BYTES:
        raise UnreadableError("the config is larger than 1 MiB")
    try:
        document = json.loads(config)
    except ValueError as error:
        raise UnreadableError("the config is not JSON") from error
    repos = document.get("repos") if isinstance(document, dict) else None
    if not isinstance(repos, list):
        raise UnreadableError("the config has no repos list")
    for entry in repos:
        if isinstance(entry, dict) and entry.get("dir") == repo:
            return entry
    raise UnreadableError(f"hub.json lists no repo {repo}")


def fast_gate(config: str, *, repo: str, full: str) -> dict[str, str]:
    try:
        command = read_entry(config, repo).get("check_fast")
    except UnreadableError as error:
        return {"check_fast": full, "source": "check", "reason": f"{error}{FALLBACK}"}
    if isinstance(command, str) and command.strip():
        return {"check_fast": command, "source": "check_fast", "reason": ""}
    reason = f"hub.json gives {repo} no check_fast{FALLBACK}"
    return {"check_fast": full, "source": "check", "reason": reason}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="fast_gate.py")
    parser.add_argument("--config", required=True, help="What hub step config printed.")
    parser.add_argument("--repo", required=True, help="The repo's dir in hub.json.")
    parser.add_argument("--full", required=True, help="The repo's full gate (hub step worktree).")
    args = parser.parse_args(argv)
    if not (args.config.strip() and args.repo.strip() and args.full.strip()):
        parser.error("--config, --repo and --full must not be blank")
    print(json.dumps(fast_gate(args.config, repo=args.repo, full=args.full)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
