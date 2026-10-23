# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Say whether the release tag is on origin, annotated, on the release commit, as JSON.

``tagged.py --version X.Y.Z --sha <40 hex>`` runs in the platform repo's checkout (the node's
cwd) after the owner says the platform repo's release workflow made the tag. It reads origin with
``git ls-remote origin refs/tags/vX.Y.Z refs/tags/vX.Y.Z^{}`` (``LS_REMOTE_TIMEOUT``
seconds, at most ``MAX_READ`` bytes read); it writes no ref and creates no tag. Only an annotated
tag has a peeled (``^{}``) entry, and that entry must be the release commit: a squash merge
leaves that commit off the default branch, so the tag would be on another one.

Prints ``{"ok", "found", "annotated", "peeled", "reason"}``; ``ok`` only when the peeled entry
equals ``--sha``. A failed read (network, credentials) is ``ok: false`` with the reason, exit 0,
so the run asks again. A malformed version or SHA exits 2.
"""

import argparse
import json
import re
import subprocess
import sys

PROG = "tagged.py"
LS_REMOTE_TIMEOUT = 60
MAX_READ = 64 * 1024
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
SHA = re.compile(r"[0-9a-f]{40}")
NEVER_MOVED = "a tag is never moved: the fix is a new patch release"


def verdict(listed: str, version: str, sha: str) -> dict[str, object]:
    """The verdict on ``git ls-remote``'s lines for the tag ``v<version>`` and the commit."""
    ref = f"refs/tags/v{version}"
    pairs = (line.split("\t") for line in listed.splitlines())
    entries = {pair[1]: pair[0] for pair in pairs if len(pair) == 2}
    found, peeled = ref in entries, entries.get(f"{ref}^{{}}", "")
    if not found:
        reason = f"no tag v{version} on origin yet"
    elif not peeled:
        reason = f"v{version} is a lightweight tag (no peeled entry); {NEVER_MOVED}"
    elif peeled != sha:
        reason = (
            f"v{version} is on {peeled}, not on the release commit {sha}: the release PR was"
            f" squash merged or the tag names another commit; {NEVER_MOVED}"
        )
    else:
        reason = f"v{version} is an annotated tag on {sha}"
    return {
        "ok": found and peeled == sha,
        "found": found,
        "annotated": bool(peeled),
        "peeled": peeled,
        "reason": reason,
    }


def read_origin(version: str) -> tuple[str, str]:
    """``ls-remote``'s lines for the tag, or an empty text and why the read failed."""
    ref = f"refs/tags/v{version}"
    try:
        done = subprocess.run(  # noqa: S603 - git from PATH, arguments the script built
            ["git", "ls-remote", "origin", ref, f"{ref}^{{}}"],  # noqa: S607
            capture_output=True,
            check=False,
            timeout=LS_REMOTE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return "", f"git ls-remote failed: {error}"
    if done.returncode != 0:
        why = done.stderr[:MAX_READ].decode(errors="replace").strip().splitlines()
        return "", f"git ls-remote failed: {why[-1] if why else done.returncode}"
    return done.stdout[:MAX_READ].decode(errors="replace"), ""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha", required=True)
    given = parser.parse_args(argv)
    if not VERSION.fullmatch(given.version) or not SHA.fullmatch(given.sha):
        print(f"{PROG}: --version must be X.Y.Z and --sha a full commit SHA", file=sys.stderr)
        return 2
    listed, failure = read_origin(given.version)
    found = verdict(listed, given.version, given.sha)
    if failure:
        found["reason"] = failure
    print(json.dumps(found))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
