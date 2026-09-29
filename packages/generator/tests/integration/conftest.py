"""Rendered hubs on disk and the interpreters that run their hooks and scripts.

Every rendered ``.py`` runs on the system ``python3``, which is 3.9 on macOS (AC-4.24): each test
that runs one takes ``hook_python`` and so runs twice, on this interpreter and on a real 3.9.
Children get an environment built from scratch and ``-I``, so nothing of this process leaks in.
The golden file harness of the characterization cases (AC-4.22) is at the end, behind the
``golden`` fixture.
"""

import difflib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
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
