"""``make live``: serve this checkout's ``hub web`` and restart it whenever its Python code changes.

The playground API of the live loop: it runs ``hub web --port <port>`` from this checkout and polls
the mtimes of ``packages/*/src/**/*.py`` once a second; on a change it stops the server (SIGTERM,
then SIGKILL after a grace period) and starts it again. No Claude session runs in it (the stable
``hub web`` on 7420 drives them), so a restart loses nothing. Ctrl C stops it. ``--token-file``
goes to every start, so the browser's cookie (the playground shares it with 7420) still opens the
restarted server.
"""

import argparse
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from types import FrameType

ROOT = Path(__file__).resolve().parent.parent
POLL_SECONDS = 1.0
STOP_SECONDS = 5.0


def snapshot(root: Path) -> dict[Path, float]:
    """The mtime of every Python source file of the workspace packages."""
    stamps: dict[Path, float] = {}
    for path in root.glob("packages/*/src/**/*.py"):
        try:
            stamps[path] = path.stat().st_mtime
        except OSError:
            continue
    return stamps


def changed(before: dict[Path, float], after: dict[Path, float]) -> list[Path]:
    """The files added, removed or modified between two snapshots."""
    return sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))


def server_command(port: int, db: str | None, token_file: str | None) -> list[str]:
    """The ``hub web`` argv of every start: the same port, database and token file each time."""
    command = [sys.executable, "-m", "agent_hub.cli", "web", "--port", str(port)]
    if db is not None:
        command += ["--db", db]
    if token_file is not None:
        command += ["--token-file", token_file]
    return command


def start(port: int, db: str | None, token_file: str | None = None) -> subprocess.Popen[bytes]:
    command = server_command(port, db, token_file)
    return subprocess.Popen(command, cwd=ROOT)  # noqa: S603 -- a fixed argv, no shell


def stop(server: subprocess.Popen[bytes]) -> None:
    if server.poll() is not None:
        return
    server.terminate()
    try:
        server.wait(timeout=STOP_SECONDS)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=7421)
    parser.add_argument("--db", default=None)
    parser.add_argument("--token-file", default=None)
    args = parser.parse_args(argv)

    server = start(args.port, args.db, args.token_file)

    def on_signal(_signum: int, _frame: FrameType | None) -> None:
        stop(server)
        sys.exit(0)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    stamps = snapshot(ROOT)
    while True:
        time.sleep(POLL_SECONDS)
        current = snapshot(ROOT)
        files = changed(stamps, current)
        if not files and server.poll() is None:
            continue
        stamps = current
        if files:
            shown = ", ".join(str(p.relative_to(ROOT)) for p in files[:3])
            print(f"live: {shown}{' …' if len(files) > 3 else ''} changed, restarting", flush=True)
        else:
            print("live: hub web exited, restarting", flush=True)
            time.sleep(POLL_SECONDS)
        stop(server)
        server = start(args.port, args.db, args.token_file)


if __name__ == "__main__":
    sys.exit(main())
