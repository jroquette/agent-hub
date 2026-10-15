# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Run the repo's check in the cwd and print its result as one JSON object; exit 0 either way.

``check.py <command> [<previous round>]``: ``command`` runs through ``bash -c`` (it is the
repo's ``check`` from ``hub.json``), its stdout and stderr together; the output is
``{"passed", "exit_code", "round", "tail"}``, ``round`` one past the previous round (1 when it is
blank) and ``tail`` the output's last ``TAIL_CHARS`` characters, so a red check is data the next
round reads, not a failed node. The output goes to a temporary file, so memory stays bounded.
A bad round exits 2.
"""

import json
import subprocess
import sys
import tempfile

TAIL_CHARS = 4000
# A UTF-8 character is at most 4 bytes: this many bytes always hold the last TAIL_CHARS.
TAIL_BYTES = 4 * TAIL_CHARS


def main(argv: list[str]) -> int:
    if len(argv) not in {1, 2}:
        print("usage: check.py <command> [<previous round>]", file=sys.stderr)
        return 2
    previous = argv[1] if len(argv) == 2 else ""
    if previous and not (previous.isascii() and previous.isdecimal()):
        print(f"check.py: the previous round is not a count: {previous!r}", file=sys.stderr)
        return 2
    with tempfile.TemporaryFile() as output:
        # The repo's own gate, as hub run runs it: a shell command line from hub.json.
        done = subprocess.run(  # noqa: S603 - the repo's configured check, by design
            ["bash", "-c", argv[0]],  # noqa: S607 - bash from PATH, as hub run's gate
            stdout=output,
            stderr=subprocess.STDOUT,
            check=False,
        )
        size = output.seek(0, 2)
        output.seek(max(0, size - TAIL_BYTES))
        tail = output.read().decode(errors="replace")[-TAIL_CHARS:]
    result = {
        "passed": done.returncode == 0,
        "exit_code": done.returncode,
        "round": int(previous or "0") + 1,
        "tail": tail,
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
