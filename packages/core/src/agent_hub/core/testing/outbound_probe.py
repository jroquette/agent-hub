"""A probe that catches the outbound network calls of a child process, for no-network tests.

A test makes a folder, writes the probe's stand-in tools there (``write_stubs``), serves its
recording proxy (``recording_proxy``) and runs a child (a rendered hook, a ``hub`` command) in
``outbound_env``, an environment built from scratch that loads ``SITECUSTOMIZE`` in every Python
child, points every proxy variable at the recorder and puts the stand-ins first on ``PATH``.
``outbound_calls`` then lists what the child tried. Standard library only; ``SITECUSTOMIZE`` runs
inside the child, so it stays Python 3.9 code.

Not written yet: every function raises ``NotImplementedError``.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# The text each Python child imports at start-up: it records and refuses every non-loopback
# socket call to the folder's ``calls.jsonl`` and appends a marker (pid, ppid, argv) to its
# ``loaded.jsonl``.
SITECUSTOMIZE = ""


@contextmanager
def recording_proxy(folder: Path) -> Iterator[int]:
    """Serve a loopback listener that logs the request line of each connection under ``folder``
    and closes it; yield its port."""
    raise NotImplementedError


def write_stubs(folder: Path) -> None:
    """Write the probe's files under ``folder`` (an existing, empty folder): stand-ins for gh,
    uv, uvx, claude, curl, wget, ssh and git's proxy command, each logging its arguments and its
    parent's process id, then exiting 1."""
    raise NotImplementedError


def outbound_env(folder: Path, port: int, path: str) -> dict[str, str]:
    """A child's environment from scratch: the stand-ins, then ``path``, on ``PATH``; ``HOME``
    under ``folder``; ``SITECUSTOMIZE`` on ``PYTHONPATH``; the six proxy variables at
    ``port``; nothing of this process's environment."""
    raise NotImplementedError


def outbound_calls(folder: Path) -> list[str]:
    """Every call recorded under ``folder``, one line each, naming the call (its target, request
    line or arguments) and the process that made it; empty when nothing called out."""
    raise NotImplementedError
