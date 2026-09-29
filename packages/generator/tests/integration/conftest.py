"""Rendered hubs on disk and the interpreters that run their hooks and scripts.

Every rendered ``.py`` runs on the system ``python3``, which is 3.9 on macOS (AC-4.24): each test
that runs one takes ``hook_python`` and so runs twice, on this interpreter and on a real 3.9.
Children get an environment built from scratch and ``-I``, so nothing of this process leaks in.
The golden file harness of the characterization cases (AC-4.22) follows, behind the ``golden``
fixture, and then the workspace a case runs in, behind ``char_workspace``.
"""

import contextlib
import copy
import datetime
import difflib
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

type HubRenderer = Callable[[HubConfig], Path]

# The interpreters of ``hook_python``: this one, and the hooks' floor.
CURRENT = "current"
PYTHON39 = "3.9"
# A child that has not answered by then is hung (a FIFO read, a lost timeout), not slow.
CHILD_TIMEOUT = 60.0
# The golden harness's modes (read from this process's environment only) and make's variables.
UPDATE_VARIABLE = "GOLDEN_UPDATE"
KEEP_VARIABLE = "GOLDEN_KEEP"
DROPPED_VARIABLES = frozenset(
    {
        UPDATE_VARIABLE,
        KEEP_VARIABLE,
        "MAKEFLAGS",
        "MFLAGS",
        "MAKELEVEL",
        "GNUMAKEFLAGS",
        "MAKEFILES",
    }
)


def runs_python39(executable: str) -> bool:
    completed = subprocess.run(  # noqa: S603 - an interpreter found on PATH, fixed script
        [executable, "-I", "-c", "import sys; print(sys.version_info[:2] == (3, 9))"],
        capture_output=True,
        text=True,
        check=False,
        env=child_env(),
    )
    return completed.stdout.strip() == "True"


def find_python39() -> str | None:
    """The first of ``python3.9`` and ``python3`` on ``PATH`` that is Python 3.9."""
    for name in ("python3.9", "python3"):
        executable = shutil.which(name)
        if executable is not None and runs_python39(executable):
            return executable
    return None


def require_python39() -> str:
    """A Python 3.9 interpreter; skips the test without one, fails it under CI (which has one)."""
    executable = find_python39()
    if executable is None:
        message = "no Python 3.9 interpreter on PATH"
        if os.environ.get("CI"):
            pytest.fail(f"{message}, and CI must install one (.github/workflows/ci.yml)")
        pytest.skip(message)
    return executable


@pytest.fixture(params=[CURRENT, PYTHON39])
def hook_python(request: pytest.FixtureRequest) -> str:
    """The interpreter a rendered hook or script runs on: this one, then a real 3.9."""
    if request.param == CURRENT:
        return sys.executable
    return require_python39()


@pytest.fixture
def python39() -> str:
    """A real Python 3.9 (skips without one, fails under CI)."""
    return require_python39()


@pytest.fixture
def rendered_hub(tmp_path: Path, rendered_tree: Callable[..., Path]) -> HubRenderer:
    """Write ``render_hub(config)``, links included, to ``tmp_path/ws/<hub repo name>``.

    Returns that hub folder; the workspace ``ws`` beside it holds the hub the way a real one does.
    """

    def render(config: HubConfig) -> Path:
        name = config.project.hub_repo.rsplit("/", 1)[-1]
        return rendered_tree(render_hub(config), root=tmp_path / "ws" / name)

    return render


def child_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """A child's environment from scratch: ``PATH`` only, plus ``extra``.

    The harness mode variables and make's own are dropped even from ``extra``: a child never
    updates goldens, keeps roots or joins a make jobserver because this run does.
    """
    env = {"PATH": os.environ.get("PATH", os.defpath)} | dict(extra or {})
    return {name: value for name, value in env.items() if name not in DROPPED_VARIABLES}


def run_child(
    python: str,
    code: str,
    *,
    path: Path,
    args: Sequence[str] = (),
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = CHILD_TIMEOUT,
) -> Any:
    """Run ``code`` on ``python`` with ``path`` first on ``sys.path``; return its stdout as JSON.

    ``-I`` keeps the environment, the user site and the working directory out of ``sys.path``;
    ``env`` is added to a from-scratch environment (``child_env``). A non-zero exit fails the test
    with the child's stderr.
    """
    prelude = f"import sys\nsys.path.insert(0, {str(path)!r})\n"
    completed = subprocess.run(  # noqa: S603 - an interpreter from hook_python, fixed script
        [python, "-I", "-c", prelude + code, *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=child_env(env),
        timeout=timeout,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.fixture
def run_python() -> Callable[..., Any]:
    """``run_child``: run a snippet on an interpreter with a rendered folder on ``sys.path``."""
    return run_child


# The golden harness: a port of AGH-7's ``support/golden.py`` and the compare part of its
# ``support/harness.py``. A case's golden is ``golden/<file>/<case>.golden``: five sections in
# ``STREAMS`` order, each a header ``--- <stream> (<n> bytes) ---``, exactly those n bytes, then
# one ``\n``. Only those exact bytes parse. Output is compared after two rewrites only: the case
# root becomes ``<ROOT>``, and a traceback keeps its first and last lines around ``  ...``.

REPO_ROOT = Path(__file__).resolve().parents[4]
GOLDEN_ROOT = Path(__file__).resolve().parent / "golden"
STREAMS = ("rc", "stdout", "stderr", "fs", "calls")
GOLDEN_SUFFIX = ".golden"
# At most 18 digits: a count stays far below int()'s digit limit, so a huge one is a format error.
HEADER = re.compile(rb"--- ([a-z]+) \((0|[1-9][0-9]{0,17}) bytes\) ---\n")
TRACEBACK_HEAD = b"Traceback (most recent call last):"
NO_FINAL_NEWLINE = "\\ no newline at end of file"
# ``<ROOT>/bin`` (fakes and their answers) and ``<ROOT>/log`` (calls) belong to the harness.
FS_EXCLUDED_TOP = frozenset({"bin", "log"})
FS_EXCLUDED_ANYWHERE = frozenset({".git", "__pycache__"})
UPDATE_HINT = (
    f"Update: {UPDATE_VARIABLE}=1 uv run --locked --all-packages pytest -m integration "
    "packages/generator/tests/integration -q, then review and commit the golden diff"
)

type Streams = Mapping[str, bytes]
type TreeEntry = tuple[str, str | bytes | None]
type Tree = dict[str, TreeEntry]


class GoldenFormatError(ValueError):
    """A golden that does not parse: a bad header or count, a section out of order, extra bytes."""


def shown(path: Path) -> str:
    """A path as messages show it: repo-relative when inside this repo."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def normalize_root(data: bytes, *, root: Path | str, given: Path | str) -> bytes:
    """The case root becomes ``<ROOT>``: the resolved form first, then the given one.

    The order matters when one form holds the other (macOS: ``/var/…`` inside ``/private/var/…``).
    """
    for form in (str(root), str(given)):
        if form:
            data = data.replace(form.encode(), b"<ROOT>")
    return data


def normalize(data: bytes, *, root: Path | str, given: Path | str) -> bytes:
    """``normalize_root``, then each traceback's indented frame lines become one ``  ...`` line."""
    out: list[bytes] = []
    skipping = False
    for line in normalize_root(data, root=root, given=given).splitlines(keepends=True):
        if skipping and line.startswith(b" "):
            continue
        skipping = False
        out.append(line)
        if line.rstrip(b"\r\n") == TRACEBACK_HEAD:
            out.append(b"  ...\n")
            skipping = True
    return b"".join(out)


def case_streams(
    *, root: Path, returncode: int, stdout: bytes, stderr: bytes, fs: bytes, calls: bytes
) -> dict[str, bytes]:
    """A case's five streams as its golden holds them; ``root`` is the case root as given."""
    forms = {"root": root.resolve(), "given": root}
    return {
        "rc": f"{returncode}\n".encode(),
        "stdout": normalize(stdout, **forms),
        "stderr": normalize(stderr, **forms),
        "fs": normalize_root(fs, **forms),
        "calls": normalize_root(calls, **forms),
    }


def tree_entry(path: Path) -> TreeEntry:
    """A path's kind and content; only a regular file is read (a FIFO would block the read)."""
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        return ("link", os.readlink(path))
    if stat.S_ISDIR(mode):
        return ("dir", None)
    if stat.S_ISREG(mode):
        return ("file", path.read_bytes())
    return ("other", None)


def snapshot(root: Path) -> Tree:
    """``{posix path under root: entry}``; symlinks are never followed.

    Excluded: every ``.git`` and ``__pycache__``, and ``bin``/``log`` directly under ``root``.
    """
    tree: Tree = {}
    for folder, dirnames, filenames in os.walk(root):
        relative = Path(folder).relative_to(root).as_posix()
        prefix = "" if relative == "." else f"{relative}/"
        excluded = FS_EXCLUDED_ANYWHERE | (FS_EXCLUDED_TOP if not prefix else frozenset())
        dirnames[:] = [name for name in dirnames if name not in excluded]
        for name in [*dirnames, *filenames]:
            if name not in FS_EXCLUDED_ANYWHERE:
                tree[prefix + name] = tree_entry(Path(folder) / name)
    return tree


def text_lines(head: str, text: str) -> list[str]:
    lines = [head]
    if text:
        body = text.split("\n")
        if body[-1] == "":
            body.pop()
        lines += [f"| {line}" if line else "|" for line in body]
        if not text.endswith("\n"):
            lines.append(NO_FINAL_NEWLINE)
    return lines


def change_lines(operation: str, path: str, entry: TreeEntry) -> list[str]:
    kind, value = entry
    head = f"{operation} <ROOT>/{path}"
    if kind == "dir":
        return [f"{head}/"]
    if kind == "other":  # a FIFO, socket or device: listed, never read
        return [f"{head} other"]
    if isinstance(value, str):  # only a link holds a str: its target
        return [f"{head} -> {value}"]
    if operation == "D" or value is None:
        return [head]
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        text = "\0"
    if "\0" in text:
        return [f"{head} sha256={hashlib.sha256(value).hexdigest()}"]
    return text_lines(head, text)


def fs_changes(before: Tree, after: Tree) -> bytes:
    """The ``fs`` stream: added, modified and deleted paths, sorted; modes and times never show."""
    lines: list[str] = []
    for path in sorted(before.keys() | after.keys()):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        if new is None:
            lines += change_lines("D", path, old or ("file", None))
        else:
            lines += change_lines("A" if old is None else "M", path, new)
    return "".join(f"{line}\n" for line in lines).encode()


def render_golden(streams: Streams) -> bytes:
    """Each stream in ``STREAMS`` order: its counted header, its bytes, one ``\\n``."""
    return b"".join(
        f"--- {stream} ({len(streams[stream])} bytes) ---\n".encode() + streams[stream] + b"\n"
        for stream in STREAMS
    )


def section_end(data: bytes, *, start: int, stream: str, path: Path) -> tuple[int, int]:
    """The ``(start, end)`` of ``stream``'s content, whose header begins at ``start``."""
    where = f"{shown(path)}: byte {start}"
    match = HEADER.match(data, start)
    if match is None:
        found = data[start : start + 40]
        message = f"expected the header `--- {stream} (<n> bytes) ---`, found {found!r}"
        raise GoldenFormatError(f"{where}: {message}")
    if match.group(1).decode() != stream:
        order = ", ".join(STREAMS)
        message = f"section {match.group(1).decode()} where {stream} is expected (order: {order})"
        raise GoldenFormatError(f"{where}: {message}")
    begin, size = match.end(), int(match.group(2))
    end = begin + size
    if end > len(data):
        left = len(data) - begin
        message = f"section {stream} declares {size} bytes, the file has {left} left"
        raise GoldenFormatError(f"{shown(path)}: byte {begin}: {message}")
    if data[end : end + 1] != b"\n":
        message = f"section {stream}: its {size} bytes are not followed by the \\n separator"
        raise GoldenFormatError(f"{shown(path)}: byte {end}: {message} (wrong byte count?)")
    return begin, end


def parse_golden(data: bytes, path: Path = Path("<golden>")) -> dict[str, bytes]:
    """The streams of a golden; ``GoldenFormatError`` unless ``data`` is exactly rendered."""
    streams: dict[str, bytes] = {}
    position = 0
    for stream in STREAMS:
        begin, end = section_end(data, start=position, stream=stream, path=path)
        streams[stream] = data[begin:end]
        position = end + 1
    if position != len(data):
        extra = len(data) - position
        raise GoldenFormatError(
            f"{shown(path)}: byte {position}: {extra} bytes after the last section"
        )
    return streams


def diff_lines(data: bytes) -> list[str]:
    lines = data.decode("utf-8", "backslashreplace").splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += f"\n{NO_FINAL_NEWLINE}\n"
    return lines


def section_diffs(expected: Streams, actual: Streams, *, path: Path) -> list[str]:
    """One unified diff per section of the golden at ``path`` that differs from ``actual``."""
    return [
        "".join(
            difflib.unified_diff(
                diff_lines(expected[stream]),
                diff_lines(actual[stream]),
                f"{shown(path)} [{stream}]",
                "actual",
            )
        )
        for stream in STREAMS
        if expected[stream] != actual[stream]
    ]


def compare_case(golden_root: Path, case: str, actual: Streams, *, update: bool) -> list[str]:
    """The problems of ``actual`` against ``<golden_root>/<case>.golden``; none when equal.

    With ``update``, a missing or differing golden is rewritten whole, its path printed to stderr.
    """
    path = golden_root / f"{case}{GOLDEN_SUFFIX}"
    if not path.resolve().is_relative_to(golden_root.resolve()):
        return [f"{case}: golden path {shown(path.resolve())} is outside {shown(golden_root)}"]
    new = render_golden(actual)
    old = path.read_bytes() if path.is_file() else None
    if old == new:
        return []
    if update:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(new)
        sys.stderr.write(f"wrote {shown(path)}\n")
        return []
    if old is None:
        return [f"missing golden {shown(path)}\n{UPDATE_HINT}"]
    try:
        expected = parse_golden(old, path)
    except GoldenFormatError as error:
        return [f"corrupt golden {error}\n{UPDATE_HINT}"]
    return [*section_diffs(expected, actual, path=path), UPDATE_HINT]


def missing_goldens(golden_root: Path, cases: Iterable[str]) -> list[str]:
    """Each case without its ``<file>/<case>.golden``."""
    paths = {case: golden_root / f"{case}{GOLDEN_SUFFIX}" for case in cases}
    return [
        f"{case}: missing golden {shown(path)}"
        for case, path in paths.items()
        if not path.is_file()
    ]


def file_folder_orphans(folder: Path, cases: Collection[str]) -> list[str]:
    problems: list[str] = []
    for path in sorted(folder.iterdir()):
        stem = path.name.removesuffix(GOLDEN_SUFFIX)
        case = f"{folder.name}/{stem}"
        if not path.name.endswith(GOLDEN_SUFFIX) or not stem or not path.is_file():
            problems.append(f"{shown(path)}: not a <case>{GOLDEN_SUFFIX} file")
        elif case not in cases:
            problems.append(f"{shown(path)}: no case {case}")
        else:
            try:
                parse_golden(path.read_bytes(), path)
            except GoldenFormatError as error:
                problems.append(f"corrupt golden {error}")
    return problems


def golden_orphans(golden_root: Path, cases: Collection[str]) -> list[str]:
    """Entries of ``golden_root`` that are not the parsing golden of a listed ``<file>/<case>``.

    Nothing is deleted.
    """
    if not golden_root.is_dir():
        return []
    problems: list[str] = []
    for entry in sorted(golden_root.iterdir()):
        if entry.is_dir() and not entry.is_symlink():
            problems += file_folder_orphans(entry, cases)
        else:
            problems.append(f"{shown(entry)}: not a <file> directory")
    return problems


def update_mode() -> bool:
    """Whether ``GOLDEN_UPDATE=1`` asks to rewrite goldens; fails the test when ``CI`` is set."""
    if os.environ.get(UPDATE_VARIABLE) != "1":
        return False
    if os.environ.get("CI"):
        pytest.fail(
            f"{UPDATE_VARIABLE}=1 is refused when CI is set: goldens are regenerated locally, "
            "reviewed and committed"
        )
    return True


def assert_matches_golden(golden_root: Path, case: str, actual: Streams) -> None:
    """Fail with every problem of ``actual`` against its golden (update mode rewrites it)."""
    problems = compare_case(golden_root, case, actual, update=update_mode())
    if problems:
        pytest.fail(f"{case}:\n" + "\n".join(problems))


class GoldenHarness:
    """The harness, as the ``golden`` fixture hands it to tests (a conftest is not importable)."""

    STREAMS = STREAMS
    GOLDEN_ROOT = GOLDEN_ROOT
    GoldenFormatError = GoldenFormatError
    render = staticmethod(render_golden)
    parse = staticmethod(parse_golden)
    normalize = staticmethod(normalize)
    case_streams = staticmethod(case_streams)
    snapshot = staticmethod(snapshot)
    fs_changes = staticmethod(fs_changes)
    compare = staticmethod(compare_case)
    missing = staticmethod(missing_goldens)
    orphans = staticmethod(golden_orphans)
    update_mode = staticmethod(update_mode)
    assert_matches = staticmethod(assert_matches_golden)


@pytest.fixture
def golden() -> GoldenHarness:
    """The golden file harness: format, normalization, ``fs`` stream, compare, update mode."""
    return GoldenHarness()


# The characterization workspace: a port of AGH-7's ``support/workspace.py``, ``fixtures.py``,
# ``commands.py`` and the run part of ``harness.py``. A case's ``<ROOT>`` is ``tmp_path/root``
# (nested, never directly under the temp folder, whose other hubs the hooks' workspace scan would
# find): ``ws/demo-hub`` (hub copy), ``ws/<repo>``, ``origins/<repo>.git``, ``home/`` (``HOME``),
# ``bin/`` (fakes), ``log/``, ``elsewhere/``. Its child scripts are written from the string
# constants below to ``tmp_path/support``, outside ``<ROOT>``.

FIXED = 1768473000  # 2026-01-15T10:30:00Z: the frozen instant, also written into SITECUSTOMIZE
# The only entry of a case child's PYTHONPATH, so ``site`` imports it in every Python child and
# grandchild. Kept 3.9-compatible and byte-for-byte AGH-7's ``support/clock/sitecustomize.py``
# apart from this docstring.
SITECUSTOMIZE = """\
\"\"\"Frozen clock for every Python child of a case: its folder is the child's PYTHONPATH.

The instant is built from UTC, never from the local zone, so the parent's TZ cannot leak in. Only
the no-argument forms are frozen: localtime(secs), gmtime(secs) and strftime(fmt, t) still convert
what they are given (localtime as UTC). Imported under any other name it patches nothing.
\"\"\"
import datetime
import time

FIXED = 1768473000  # 2026-01-15T10:30:00Z

_real_datetime = datetime.datetime
_gmtime, _strftime, _asctime = time.gmtime, time.strftime, time.asctime


def _frozen(secs=None):
    return _gmtime(FIXED if secs is None else secs)


class FrozenDate(datetime.date):
    @classmethod
    def today(cls):
        return cls(2026, 1, 15)


class FrozenDatetime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        v = _real_datetime.fromtimestamp(FIXED, datetime.timezone.utc)
        v = v.astimezone(tz) if tz is not None else v.replace(tzinfo=None)
        return cls(v.year, v.month, v.day, v.hour, v.minute, v.second, tzinfo=v.tzinfo)

    @classmethod
    def today(cls):
        return cls.now()

    @classmethod
    def utcnow(cls):
        return cls.now(datetime.timezone.utc).replace(tzinfo=None)


if __name__ == "sitecustomize":
    time.time = lambda: float(FIXED)
    time.time_ns = lambda: FIXED * 10**9
    time.gmtime = time.localtime = _frozen  # localtime is UTC-based: TZ is ignored
    time.strftime = lambda fmt, t=None: _strftime(fmt, _frozen() if t is None else t)
    time.asctime = lambda t=None: _asctime(_frozen() if t is None else t)
    time.ctime = lambda secs=None: _asctime(_frozen(secs))
    datetime.date, datetime.datetime = FrozenDate, FrozenDatetime
"""
# The one program behind every fake tool (gh, claude, ruff, prettier, eslint): AGH-7's
# ``support/fake_tool.py``.
FAKE_TOOL = """\
\"\"\"The one program behind every fake tool (gh, claude, ruff, prettier, eslint).

Usage: fake_tool.py <tool> <answers.json> <calls.jsonl> <invoked path> [args...]
Logs the call as one JSON line, then answers with the first rule of answers[tool] whose argv_has
items are all arguments and whose env_has values are substrings of those variables. With no match
it prints nothing and exits 1.
\"\"\"
import json
import os
import sys


def matches(rule, args):
    return (all(a in args for a in rule.get("argv_has", []))
            and all(sub in os.environ.get(var, "") for var, sub in rule.get("env_has", {}).items()))


def main(tool, answers_path, log_path, invoked, *args):
    call = {"tool": tool, "cwd": os.getcwd(), "argv": [invoked, *args]}
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(json.dumps(call, ensure_ascii=False) + "\\n")
    try:
        with open(answers_path, encoding="utf-8") as f:
            rules = json.load(f).get(tool, [])
    except FileNotFoundError:
        rules = []
    rule = next((r for r in rules if matches(r, args)), None)
    if rule is None:
        return 1
    for rel, text in rule.get("write", {}).items():
        os.makedirs(os.path.dirname(os.path.abspath(rel)), exist_ok=True)
        with open(rel, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    sys.stdout.buffer.write(rule.get("stdout", "").encode())
    sys.stderr.buffer.write(rule.get("stderr", "").encode())
    return rule.get("rc", 0)


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
"""
HUB_DIR = "demo-hub"
# The rendered files a hub copy holds (AGH-7 copied the hub's own by the same globs, E7).
HUB_GLOBS = ("scripts/*.py", "plugin/hub-workflow/hooks/*.py")
SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
# AGH-7's case hub.json, written byte-for-byte as each hub copy's ``hub.json``. It is not a valid
# HubConfig (no platform, repos without checks): ``char_config`` is what renders the hub.
CASE_HUB_JSON: dict[str, Any] = {
    "project": {
        "name": "demo",
        "hub_repo": "acme/demo-hub",
        "branch_prefix": "dev/",
        "default_branch": "trunk",
        "author_name": "Test User",
        "author_email": "t@example.com",
    },
    "tracker": {"kind": "linear", "team": "TST"},
    "repos": [{"dir": "api", "github": "acme/api"}, {"dir": "web", "github": "acme/web"}],
}
REPO_IGNORES = (".claude/worktrees/", ".venv/", "node_modules/", "__pycache__/")
HUB_IGNORES = (
    *REPO_IGNORES,
    ".agent-runs/",
    "brain/_inbox/sessions/",
    "brain/auto/workspace/session-snapshot.md",
)
# Newer git runs auto-maintenance in the background after commits; every case turns it off.
NO_MAINTENANCE = (
    ("maintenance.auto", "false"),
    ("maintenance.autoDetach", "false"),
    ("gc.auto", "0"),
    ("gc.autoDetach", "false"),
)
REPO_FAKE_DIRS = {
    "ruff": ".venv/bin",
    "prettier": "node_modules/.bin",
    "eslint": "node_modules/.bin",
}
# The one table that names the files under test; ``{hub}`` is the case's hub copy.
COMMANDS = {
    "retro_metrics": "scripts/retro_metrics.py",
    "post_edit": "plugin/hub-workflow/hooks/post_edit.py",
    "session_start": "plugin/hub-workflow/hooks/session_start.py",
    "session_end": "plugin/hub-workflow/hooks/session_end.py",
    "pre_compact": "plugin/hub-workflow/hooks/pre_compact.py",
}
# AGH-7's per-case budget: from the workspace's creation through setup, run and compare (the
# session-scoped render is not counted). The child gets what is left, at least the floor.
CASE_TIME_CAP = 10.0
MIN_CHILD_TIMEOUT = 0.5
# How long the killed process group may take to close its output before the case fails.
KILL_GRACE = 5.0

# The brief workspace of the session start cases (AGH-7's ``fixtures.py``): the hub copy (with an
# origin at the same commit) holding ``now.md`` and four journal days, ``api`` (2 dirty files, 1
# commit behind its origin), ``web`` (detached, no origin); ``ui`` is listed but absent.
BRIEF_HUB_JSON = copy.deepcopy(CASE_HUB_JSON)
BRIEF_HUB_JSON["repos"].append({"dir": "ui", "github": "acme/ui"})
NOW_MD = "---\nlast_verified: 2026-01-12\n---\n# Now\nShip the collector.\nThen the CLI.\n"


def _titles(day: int, count: int, width: int) -> str:
    return "".join(f"## Day {day} topic {i}: " + "x" * width + "\n" for i in range(1, count + 1))


JOURNAL = {  # T-1 and T-2 are shown; T-5 is inside the week but only 2 days kept; T-9 is outside
    "brain/journal/2026/01/14.md": (
        "---\ntype: journal\n---\n# 2026-01-14\n"
        + _titles(14, 4, 80)
        + "### not a title\nbody text\n"
    ),
    "brain/journal/2026/01/13.md": (
        "# 2026-01-13\n## Fixed the loader\nnotes\n## Reviewed slice A\n"
    ),
    "brain/journal/2026/01/10.md": "## Older day in the week\n",
    "brain/journal/2026/01/06.md": "## Outside the week\n",
}
PRS = (
    "#41 Add login endpoint\n"
    "#40 Refactor the session storage layer so that every adapter shares one connection pool "
    "and retry policy\n"
    "#38 Fix pagination\n"
    "#37 Bump dependencies\n"
    "#35 Fifth PR is never shown\n"
)
BRIEF_GH: dict[str, list[dict[str, Any]]] = {
    "gh": [
        {"argv_has": ["pr", "acme/api"], "stdout": PRS},
        {"argv_has": ["run", "acme/api"], "stdout": "lint\nbuild\nlint\n"},
        {"argv_has": ["acme/web"], "stdout": ""},
    ]
}

type FileContents = Mapping[str, str | bytes]


def at(days_before: int = 0, hhmm: str = "10:30") -> str:
    """An ISO instant ``days_before`` days before the frozen day, at ``hhmm`` UTC."""
    frozen = datetime.datetime.fromtimestamp(FIXED, datetime.UTC)
    day = frozen - datetime.timedelta(days=days_before)
    return f"{day:%Y-%m-%d}T{hhmm}:00Z"


def write_exe(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


def case_collisions(base: Path, rels: Iterable[str]) -> list[str]:
    """Paths under ``base`` (``rels``, their parents, what exists) that differ only by case."""
    seen: dict[str, str] = {}
    problems: list[str] = []
    for rel in rels:
        parts = PurePosixPath(rel).parts
        for index, name in enumerate(parts, start=1):
            prefix = "/".join(parts[:index])
            other = seen.setdefault(prefix.casefold(), prefix)
            if other != prefix:
                problems.append(f"{prefix} vs {other}")
                continue
            parent = base.joinpath(*parts[: index - 1])
            existing = os.listdir(parent) if parent.is_dir() else ()
            problems += [
                f"{prefix} vs existing {'/'.join((*parts[: index - 1], found))}"
                for found in existing
                if found != name and found.casefold() == name.casefold()
            ]
    return sorted(set(problems))


def write_files(base: Path, files: FileContents) -> None:
    """Write ``{relative path: text or bytes}`` under ``base``.

    Refuses, before writing anything, two paths that differ only by case (among ``files`` or
    against what exists): the owner's macOS filesystem is case-insensitive.
    """
    clashes = case_collisions(base, files)
    if clashes:
        raise ValueError(
            f"paths under {base} differ only by case ({'; '.join(clashes)}): the owner's macOS "
            "filesystem is case-insensitive, so one would overwrite the other there"
        )
    for rel, content in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())


def hub_candidates(folder: Path) -> list[Path]:
    """What the hooks' ``find_hub`` could take at ``folder``: itself when it holds ``hub.json``,
    then its child folders holding ``hub.json`` and ``brain/`` (the workspace scan)."""
    found = [folder] if (folder / "hub.json").is_file() else []
    try:
        children = sorted(child for child in folder.iterdir() if child.is_dir())
    except OSError:  # missing or unreadable: nothing to scan, as in find_hub
        children = []
    return found + [c for c in children if (c / "hub.json").is_file() and (c / "brain").is_dir()]


def release_root(root: Path, *, keep: bool, say: Callable[[str], None]) -> None:
    """Remove a case root, or keep it and say where it is (``GOLDEN_KEEP=1``)."""
    if keep:
        say(f"{KEEP_VARIABLE} {root}")
    else:
        shutil.rmtree(root, ignore_errors=True)


class CaseWorkspace:
    """One case's ``<ROOT>``, its environment, git repos, fakes and hub copy; runs the case."""

    FIXED = FIXED
    HUB_JSON = CASE_HUB_JSON
    BRIEF_HUB_JSON = BRIEF_HUB_JSON
    BRIEF_GH = BRIEF_GH
    COMMANDS = COMMANDS
    at = staticmethod(at)
    write_files = staticmethod(write_files)

    time_cap = CASE_TIME_CAP

    def __init__(self, *, root: Path, support: Path, python: str, render: RenderedHub) -> None:
        self.started = time.monotonic()
        self.root = root  # as given: the harness also replaces its resolved form
        self.support = support
        self.python = python
        self.render = render
        for folder in ("ws", "origins", "home/.config", "bin", "log", "elsewhere"):
            (self.root / folder).mkdir(parents=True)
        write_exe(self.root / "bin" / "python3", f'#!/bin/sh\nexec "{python}" "$@"\n')
        write_files(
            self.support,
            {"clock/sitecustomize.py": SITECUSTOMIZE, "fake_tool.py": FAKE_TOOL},
        )

    def env(self, hub_json: Mapping[str, Any] | None = None) -> dict[str, str]:
        """The child environment, built from scratch: nothing is copied from ``os.environ``."""
        root, home = self.root, self.root / "home"
        env = {
            "PATH": os.pathsep.join([str(root / "bin"), *SYSTEM_PATH]),
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "TZ": "UTC",
            "PYTHONUTF8": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(self.support / "clock"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
            "GIT_ALLOW_PROTOCOL": "file",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CEILING_DIRECTORIES": str(root),
        }
        for role in ("AUTHOR", "COMMITTER"):
            env |= {
                f"GIT_{role}_NAME": "Test User",
                f"GIT_{role}_EMAIL": "t@example.com",
                f"GIT_{role}_DATE": at(),
            }
        return env | self.git_config(hub_json or {})

    def git_config(self, hub_json: Mapping[str, Any]) -> dict[str, str]:
        """``GIT_CONFIG_*``: no maintenance, and each GitHub URL of ``hub_json`` to its origin."""
        urls = [(repo["dir"], repo["github"]) for repo in hub_json.get("repos", [])]
        hub_repo = hub_json.get("project", {}).get("hub_repo")
        if hub_repo:
            urls.append((HUB_DIR, hub_repo))
        pairs = [
            *NO_MAINTENANCE,
            *(
                (
                    f"url.{self.root}/origins/{name}.git.insteadOf",
                    f"https://github.com/{github}.git",
                )
                for name, github in urls
            ),
        ]
        config = {"GIT_CONFIG_COUNT": str(len(pairs))}
        for index, (key, value) in enumerate(pairs):
            config |= {f"GIT_CONFIG_KEY_{index}": key, f"GIT_CONFIG_VALUE_{index}": value}
        return config

    def git(
        self, *args: str, cwd: Path, date: str | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """Run git with the case env; ``date`` (from ``at``) sets both commit dates."""
        env = self.env()
        executable = shutil.which("git", path=env["PATH"])
        assert executable is not None, f"git not found on {env['PATH']}"
        if date:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
        done = subprocess.run(  # noqa: S603 - git found on the case PATH, harness arguments
            [executable, *args], cwd=cwd, env=env, capture_output=True, text=True, check=False
        )
        if check and done.returncode:
            pytest.fail(f"git {' '.join(args)} failed in {cwd}: {done.stderr}")
        return done

    def make_repo(
        self,
        path: Path,
        *,
        files: FileContents | None = None,
        commits: Sequence[tuple[int, str, FileContents]] = (),
        origin: bool = False,
        ignores: Sequence[str] = REPO_IGNORES,
    ) -> Path:
        """A repo on ``trunk`` at ``path``: an ``init`` commit at T-30 (what is in ``path``,
        ``files`` and ``.gitignore``), then each ``(days_before, message, files)`` of ``commits``.
        With ``origin``, a bare origin in ``<ROOT>/origins``."""
        path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "trunk", cwd=path)
        write_files(path, {**(files or {}), ".gitignore": "".join(f"{i}\n" for i in ignores)})
        for index, (days_before, message, more) in enumerate([(30, "init", {}), *commits]):
            write_files(path, more)
            self.git("add", "-A", cwd=path)
            self.git(
                "commit", "-q", "-m", message, cwd=path, date=at(days_before, f"09:{index:02d}")
            )
        if origin:
            self.bare_origin(path)
        return path

    def bare_origin(self, repo: Path) -> Path:
        """A bare clone of ``repo`` at ``<ROOT>/origins/<name>.git``, its fetched ``origin``."""
        bare = self.root / "origins" / f"{repo.name}.git"
        self.git("clone", "-q", "--bare", str(repo), str(bare), cwd=self.root)
        self.git("remote", "add", "origin", str(bare), cwd=repo)
        self.git("fetch", "-q", "origin", cwd=repo)
        return bare

    def hub_copy(
        self,
        hub_json: Mapping[str, Any] = CASE_HUB_JSON,
        *,
        extra_files: FileContents | None = None,
        origin: bool = False,
    ) -> Path:
        """``<ROOT>/ws/demo-hub``: the rendered files ``HUB_GLOBS`` selects, as regular files with
        their executable bit, plus ``hub.json`` (AGH-7's bytes) and ``extra_files``, committed."""
        hub = self.root / "ws" / HUB_DIR
        for file in self.render.files:
            if any(PurePosixPath(file.path).full_match(glob) for glob in HUB_GLOBS):
                target = hub / file.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(file.content)
                target.chmod(0o755 if file.executable else 0o644)
        files = {**(extra_files or {}), "hub.json": json.dumps(hub_json, indent=2) + "\n"}
        return self.make_repo(hub, files=files, origin=origin, ignores=HUB_IGNORES)

    def add_worktree(
        self, repo: Path, name: str, *, detach: bool = False, branch: str | None = None
    ) -> Path:
        """A git worktree of ``repo`` at ``<repo>/.claude/worktrees/<name>``."""
        path = repo / ".claude" / "worktrees" / name
        args = ["--detach"] if detach else ["-b", branch or name]
        self.git("worktree", "add", "-q", *args, str(path), cwd=repo)
        return path

    def fake(self, path: Path, tool: str) -> None:
        """An ``sh`` wrapper at ``path`` running the fake tool as ``tool``."""
        answers, calls = self.root / "bin" / "answers.json", self.root / "log" / "calls.jsonl"
        write_exe(
            path,
            f'#!/bin/sh\nexec "{sys.executable}" "{self.support / "fake_tool.py"}" {tool} '
            f'"{answers}" "{calls}" "$0" "$@"\n',
        )

    def install_fakes(self, answers: Mapping[str, Any]) -> None:
        """``gh`` and ``claude`` in ``<ROOT>/bin``, answering from ``{tool: [rule, ...]}``."""
        (self.root / "bin" / "answers.json").write_text(json.dumps(answers, indent=2) + "\n")
        for tool in ("gh", "claude"):
            self.fake(self.root / "bin" / tool, tool)

    def install_repo_fakes(self, repo: Path, tools: Iterable[str]) -> None:
        """ruff/prettier/eslint fakes where post_edit looks for them: in the repo, not on PATH."""
        for tool in tools:
            self.fake(repo / REPO_FAKE_DIRS[tool] / tool, tool)

    def hubs_above(self, start: Path) -> list[Path]:
        """Every folder a hub lookup walking up from ``start`` could take (stricter than
        ``find_hub``: all candidates, worktrees included). A no-hub case needs none."""
        found: list[Path] = []
        for folder in [start, *start.parents]:
            found += hub_candidates(folder)
        return found

    def command(self, name: str, *, hub: Path) -> list[str]:
        """The argv that runs the file under test ``name`` against the hub at ``hub``."""
        return [self.python, f"{hub}/{COMMANDS[name]}"]

    def brief_workspace(self) -> None:
        """The session start cases' workspace (see ``BRIEF_HUB_JSON``)."""
        ws, root = self.root / "ws", self.root
        extra = {**JOURNAL, "brain/now.md": NOW_MD}
        self.hub_copy(BRIEF_HUB_JSON, extra_files=extra, origin=True)
        api = self.make_repo(
            ws / "api",
            files={"README.md": "api\n"},
            commits=[(3, "add app", {"app.py": "x = 1\n"})],
            origin=True,
        )
        pusher = root / "elsewhere" / "api-pusher"
        self.git("clone", "-q", str(root / "origins" / "api.git"), str(pusher), cwd=root)
        write_files(pusher, {"app.py": "x = 2\n"})
        self.git("commit", "-q", "-am", "upstream change", cwd=pusher, date=at(1, "09:00"))
        self.git("push", "-q", "origin", "trunk", cwd=pusher)
        self.git("fetch", "-q", "origin", cwd=api)
        write_files(api, {"README.md": "api, edited\n", "notes.txt": "untracked\n"})
        web = self.make_repo(
            ws / "web",
            files={"index.html": "<p>web</p>\n"},
            commits=[(2, "style", {"a.css": "p{}\n"})],
        )
        self.git("checkout", "-q", "--detach", cwd=web)

    def commit_hub(self, files: Mapping[str, str | None], *, repo: Path | None = None) -> None:
        """Write (text) or delete (``None``) ``files`` in the hub copy (or ``repo``), committed
        at T-0 09:30."""
        repo = repo or self.root / "ws" / HUB_DIR
        for rel, text in files.items():
            if text is None:
                (repo / rel).unlink()
            else:
                write_files(repo, {rel: text})
        self.git("add", "-A", cwd=repo)
        self.git("commit", "-q", "-m", "case change", cwd=repo, date=at(0, "09:30"))

    def run(
        self,
        argv: Sequence[str],
        *,
        stdin: bytes = b"",
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        answers: Mapping[str, Any] | None = None,
        hub: Path | None = None,
        hub_json: Mapping[str, Any] | None = None,
        no_hub: bool = False,
    ) -> dict[str, bytes]:
        """Run ``argv`` in this root and return its five streams as a golden holds them.

        ``hub`` (default: the hub copy) may be a hub worktree. ``cwd`` defaults to ``hub``, or to
        ``<ROOT>/elsewhere`` with ``no_hub`` (which first checks that no hub is above it). ``env``
        adds to the case env; ``answers`` feeds the fakes; ``hub_json`` (default: ``hub``'s
        ``hub.json``, else the hub copy's) sets the ``insteadOf`` pairs. The child gets what is
        left of the case's time budget.
        """
        assert Path(argv[0]).is_absolute(), argv
        hub = hub or self.root / "ws" / HUB_DIR
        if no_hub:
            above = self.hubs_above(self.root / "elsewhere")
            if above:
                pytest.fail(f"a hub above <ROOT>/elsewhere: {', '.join(map(str, above))}")
            cwd = cwd or self.root / "elsewhere"
        if hub_json is None:
            hub_json = self.hub_json_of(hub)
        self.install_fakes(answers or {})
        log = self.root / "log" / "calls.jsonl"
        log.unlink(missing_ok=True)
        case_env = self.env(hub_json) | dict(env or {})
        before = snapshot(self.root)
        returncode, stdout, stderr = run_capped(
            argv,
            stdin=stdin,
            cwd=cwd or hub,
            env=child_env(case_env),
            timeout=max(self.time_cap - self.elapsed(), MIN_CHILD_TIMEOUT),
            cap=self.time_cap,
        )
        return case_streams(
            root=self.root,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            fs=fs_changes(before, snapshot(self.root)),
            calls=log.read_bytes() if log.exists() else b"",
        )

    def hub_json_of(self, hub: Path) -> Any:
        """``hub``'s ``hub.json``, else the hub copy's, else ``{}``."""
        for path in (hub / "hub.json", self.root / "ws" / HUB_DIR / "hub.json"):
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def run_case(
        self,
        case: str,
        *,
        argv: Sequence[str] = (),
        hub: Path | None = None,
        golden_root: Path = GOLDEN_ROOT,
        **run: Any,
    ) -> None:
        """Run ``<file>/<name>``'s file under test against ``hub`` (default: the hub copy) and
        compare it with its golden; fail when setup, run and compare took over the time cap.

        Update mode is read (and refused under ``CI``) before anything runs.
        """
        update = update_mode()
        name = case.split("/", 1)[0]
        hub = hub or self.root / "ws" / HUB_DIR
        streams = self.run([*self.command(name, hub=hub), *argv], hub=hub, **run)
        problems = compare_case(golden_root, case, streams, update=update)
        if self.elapsed() > self.time_cap:
            problems.insert(
                0,
                f"{case} exceeded the case time cap of {self.time_cap} s after "
                f"{self.elapsed():.1f} s (setup, run and compare)",
            )
        if problems:
            pytest.fail(f"{case}:\n" + "\n".join(problems))

    def release(self, *, keep: bool, say: Callable[[str], None]) -> None:
        release_root(self.root, keep=keep, say=say)


def run_capped(
    argv: Sequence[str],
    *,
    stdin: bytes,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
    cap: float,
) -> tuple[int, bytes, bytes]:
    """Run ``argv`` in its own session; past ``timeout``, kill its whole process group (so no
    grandchild keeps the output open) and fail."""
    with subprocess.Popen(  # noqa: S603 - an absolute interpreter or file under test
        list(argv),
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    ) as process:
        try:
            stdout, stderr = process.communicate(stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            command = " ".join(argv[:2])
            try:
                process.communicate(timeout=KILL_GRACE)
            except subprocess.TimeoutExpired:
                pytest.fail(f"{command}: its output was still open {KILL_GRACE} s after the kill")
            pytest.fail(
                f"{command} exceeded the case time cap of {cap} s (killed after {timeout:.1f} s)"
            )
        return process.returncode, stdout, stderr


@pytest.fixture(scope="session")
def char_config() -> HubConfig:
    """The valid config the characterization hub is rendered from (project ``demo``).

    Only the render uses it: each case hub's ``hub.json`` is AGH-7's ``CASE_HUB_JSON``.
    """
    document = a_hub_document()
    document["project"] |= {"branch_prefix": "dev/", "default_branch": "trunk"}
    document["repos"] = [
        {"dir": name, "github": f"acme/{name}", "check_fast": "make fast", "check": "make check"}
        for name in ("api", "web")
    ]
    document["guard"]["ask_before_edit"] = ["api/docs/adr"]
    return HubConfig.model_validate(document)


@pytest.fixture(scope="session")
def char_render(char_config: HubConfig) -> RenderedHub:
    return render_hub(char_config)


@pytest.fixture
def char_workspace(
    tmp_path: Path, request: pytest.FixtureRequest, char_render: RenderedHub
) -> Iterator[Callable[..., CaseWorkspace]]:
    """Make a ``CaseWorkspace`` (``python=`` the interpreter under test, default this one).

    The first root is ``tmp_path/root``, later ones ``root-2``, ``root-3``… Each is removed
    afterwards, or kept and printed with ``GOLDEN_KEEP=1``.
    """
    made: list[CaseWorkspace] = []

    def make(*, python: str = sys.executable) -> CaseWorkspace:
        name = "root" if not made else f"root-{len(made) + 1}"
        workspace = CaseWorkspace(
            root=tmp_path / name, support=tmp_path / "support", python=python, render=char_render
        )
        made.append(workspace)
        return workspace

    yield make
    keep = os.environ.get(KEEP_VARIABLE) == "1"
    for workspace in made:
        workspace.release(keep=keep, say=lambda line: say_uncaptured(request, line))


def say_uncaptured(request: pytest.FixtureRequest, line: str) -> None:
    """Write ``line`` to the real stderr, past pytest's output capture."""
    capture = request.config.pluginmanager.getplugin("capturemanager")
    if capture is None:
        sys.stderr.write(f"{line}\n")
        return
    with capture.global_and_fixture_disabled():
        sys.stderr.write(f"{line}\n")
