"""One step of ``make check-changed``, run as the leader of a process group of its own.

``python -m scripts.step_guard <fd> <argv...>`` runs ``argv`` in this process's group and exits
with its code. ``fd`` is the read end of a pipe whose write end only the run holds, open while
the step may go on. When the pipe ends first (the run stopped the step, or the run itself ended,
even by SIGKILL, which closes its files), the guard ends the whole group: SIGTERM, then SIGKILL
once the step is gone or after GRACE_S, so nothing the step started (pytest's or Vitest's
workers) outlives the run. A process group of its own lets the run stop one step without its
own group; the pipe keeps the Stop gate's kill of the run's group reaching the step anyway.
"""

import contextlib
import os
import select
import signal
import subprocess
import sys
from collections.abc import Sequence

GRACE_S = 5.0
POLL_S = 0.2


def main(argv: Sequence[str]) -> int:
    """Run the step ``argv[1:]`` while the pipe ``argv[0]`` stays open; the step's exit code."""
    keep, *command = argv
    os.setpgid(0, 0)
    step = subprocess.Popen(command, stdin=subprocess.DEVNULL)
    # After the step started, which keeps the default: SIGTERM to the group spares the guard.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with os.fdopen(int(keep), "rb", buffering=0) as pipe:
        while step.poll() is None:
            ready, _, _ = select.select([pipe], [], [], POLL_S)
            if ready and not pipe.read(1):
                _end_group(step)
    return step.returncode


def _end_group(step: subprocess.Popen[bytes]) -> None:
    """SIGTERM to the group; SIGKILL to what is left, this guard included, once the step is
    gone or after GRACE_S."""
    os.killpg(0, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        step.wait(timeout=GRACE_S)
    os.killpg(0, signal.SIGKILL)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
