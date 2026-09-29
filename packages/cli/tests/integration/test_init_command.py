import errno
import functools
import json
import os
import signal
from collections.abc import Callable, Collection, Iterator, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli import generator
from agent_hub.cli.git_defaults import read_git_defaults
from agent_hub.cli.main import app
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.rendered_file import Ownership
from agent_hub.core.hub_files.tree_snapshot import TreeSnapshot
from agent_hub.core.json_form import dump_json
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.hub_tree import read_hub_tree
from agent_hub.generator.render_hub import render_hub

VERSION = version("agent-hub-cli")
# The conftest's fake git builder (tests cannot import a conftest in importlib mode).
type FakeGitFactory = Callable[..., Any]
GIT_ANSWERS = {
    "config --get user.name": "Git Author",
    "config --get user.email": "git.author@example.com",
    "config --get remote.origin.url": "git@github.com:acme/git-hub.git",
}
# DEMO_FLAGS without the three values git can supply.
REQUIRED_FLAGS = ["demo", "--repos", "acme/demo-api", "--tracker", "linear:DEM"]
PINNED_COMMAND = (
    "uvx --from git+https://github.com/jroquette/agent-hub@v0.0.1"
    "#subdirectory=packages/agent-hub hub"
)
# A credential planted in a remote URL: it must never reach output or a written file.
LEAKED_MARK = "SECRET123"
FIFO_ALARM_SECONDS = 5


def run_init(args: Sequence[str]) -> Result:
    return CliRunner().invoke(app, ["init", *args])


def real(path: Path) -> str:
    return os.path.realpath(path)


def next_steps(root: Path, *, git_init: bool) -> list[str]:
    steps = [
        f"cd {real(root)}",
        *(["git init"] if git_init else []),
        "review hub.json, AGENTS.project.md and README.md",
        'git add -A && git commit -m "Create the hub"',
        "start Claude Code in the hub folder: claude",
    ]
    return ["Next steps:", *(f"  {number}. {step}" for number, step in enumerate(steps, 1))]


def created_line(config: HubConfig, root: Path) -> str:
    rendered = render_hub(config)
    managed = sum(file.ownership is Ownership.MANAGED for file in rendered.files)
    # The render's seeded files, plus hub.json; hub.lock is not counted.
    seeded = len(rendered.files) - managed + 1
    return (
        f"created {managed + seeded} files ({managed} managed, {seeded} seeded)"
        f" and {len(rendered.links)} links in {real(root)}"
    )


def written_config(root: Path) -> HubConfig:
    return HubConfig.model_validate(json.loads((root / "hub.json").read_bytes()))


def listing(root: Path) -> list[tuple[str, bytes | str | None]]:
    """Every path under ``root`` with a regular file's bytes or a link's target, never followed."""
    found: list[tuple[str, bytes | str | None]] = []
    for folder, folders, files in os.walk(root):
        for name in sorted([*folders, *files]):
            path = Path(folder) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                found.append((relative, os.readlink(path)))
            elif path.is_file():
                found.append((relative, path.read_bytes()))
            else:
                found.append((relative, None))
    return sorted(found)


def every_byte(root: Path) -> bytes:
    return b"".join(value for _, value in listing(root) if isinstance(value, bytes))


@pytest.fixture
def target(tmp_path: Path) -> Path:
    folder = tmp_path / "hub"
    folder.mkdir()
    return folder


@pytest.fixture
def git_on_path(fake_git: FakeGitFactory, monkeypatch: pytest.MonkeyPatch, target: Path) -> Any:
    """A fake git that holds values for every default, first and only on ``PATH``."""
    git = fake_git(GIT_ANSWERS, toplevel=target)
    monkeypatch.setenv("PATH", str(git.bin_dir))
    return git


@pytest.fixture
def alarm() -> Iterator[None]:
    """Fail a test that blocks (a FIFO opened by mistake) instead of hanging the run."""

    def timed_out(_signal: int, _frame: object) -> None:
        pytest.fail("the command blocked")

    previous = signal.signal(signal.SIGALRM, timed_out)
    signal.alarm(FIFO_ALARM_SECONDS)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def write_config(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "config" / "hub.json"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(dump_json(document))
    return path


@pytest.mark.parametrize("git_folder", ["absent", "folder", "file"])
def test_writes_hub_when_demo_flags_given(
    git_on_path: Any, target: Path, demo_flags: list[str], *, git_folder: str
) -> None:
    # The git init step is there exactly when <target>/.git is absent, as a folder or a file.
    if git_folder == "folder":
        (target / ".git").mkdir()
    elif git_folder == "file":
        (target / ".git").write_text("gitdir: /elsewhere/.git/worktrees/hub\n", encoding="utf-8")

    result = run_init([*demo_flags, "--dir", str(target)])

    assert result.exit_code == 0, result.stderr
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    config = written_config(target)
    steps = next_steps(target, git_init=git_folder == "absent")
    assert lines == [created_line(config, target), "", *steps]
    rendered = render_hub(config)
    for file in rendered.files:
        assert (target / file.path).read_bytes() == file.content
    for link in rendered.links:
        assert os.readlink(target / link.path) == link.target
    assert (target / "hub.lock").is_file()
    # Every defaultable value was given: git is never called.
    assert git_on_path.calls() == []


def test_reads_content_of_compared_files_when_tree_read(
    git_on_path: Any, monkeypatch: pytest.MonkeyPatch, target: Path, *, demo_flags: list[str]
) -> None:
    # The planner compares every managed file and hub.json by content: the reader must read them.
    asked: list[frozenset[str]] = []

    def recording_read(root: Path, *, wanted: Collection[str]) -> TreeSnapshot:
        asked.append(frozenset(wanted))
        return read_hub_tree(root, wanted=wanted)

    monkeypatch.setattr(generator, "read_hub_tree", recording_read)

    result = run_init([*demo_flags, "--dir", str(target)])

    assert result.exit_code == 0, result.stderr
    rendered = render_hub(written_config(target))
    managed = {file.path for file in rendered.files if file.ownership is Ownership.MANAGED}
    assert asked == [frozenset({*managed, "hub.json"})]


@pytest.mark.parametrize(
    ("repos", "expected_repos"),
    [
        ("acme/demo-api", ["acme/demo-api"]),
        ("acme/a,acme/b", ["acme/a", "acme/b"]),
    ],
    ids=["demo", "flag-order"],
)
def test_writes_flag_document_when_flags_given(
    git_on_path: Any,
    target: Path,
    demo_flags: list[str],
    *,
    repos: str,
    expected_repos: list[str],
) -> None:
    flags = [repos if value == "acme/demo-api" else value for value in demo_flags]

    result = run_init([*flags, "--dir", str(target)])

    assert result.exit_code == 0, result.stderr
    expected = {
        "$schema": "./hub.schema.json",
        "schema_version": 1,
        "platform": {"version": VERSION},
        "project": {
            "name": "demo",
            "hub_repo": "acme/demo-hub",
            "branch_prefix": "jdoe/",
            "author_name": "Jane Doe",
            "author_email": "jane@example.com",
        },
        "tracker": {"kind": "linear", "team": "DEM"},
        "repos": [
            {
                "dir": github.rpartition("/")[2],
                "github": github,
                "role": "app",
                "check_fast": "make check-fast",
                "check": "make check",
            }
            for github in expected_repos
        ],
    }
    assert (target / "hub.json").read_bytes() == dump_json(expected)
    assert [repo.github for repo in written_config(target).repos] == expected_repos


@pytest.mark.parametrize("form", ["one-json-form", "crlf-indent-four"])
def test_copies_config_bytes_when_config_given(
    target: Path, tmp_path: Path, demo_document: dict[str, Any], *, form: str
) -> None:
    demo_document["project"]["author_name"] = "Jos\N{LATIN SMALL LETTER E WITH ACUTE} Doe"
    if form == "one-json-form":
        content = dump_json(demo_document)
    else:
        text = json.dumps(demo_document, indent=4, ensure_ascii=False).replace("\n", "\r\n")
        content = text.encode("utf-8")
    config = tmp_path / "given.json"
    config.write_bytes(content)

    result = run_init(["--config", str(config), "--dir", str(target)])

    assert result.exit_code == 0, result.stderr
    assert (target / "hub.json").read_bytes() == content
    assert result.stdout.splitlines()[0] == created_line(written_config(target), target)
    assert result.stderr == ""


def test_prints_pinned_command_when_config_pin_differs(
    tmp_path: Path, demo_document: dict[str, Any]
) -> None:
    demo_document["platform"]["version"] = "0.0.1"
    config = write_config(tmp_path, demo_document)
    absent = tmp_path / "new" / "hub"

    result = run_init(["--config", str(config), "--dir", str(absent)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    assert result.stderr.startswith("hub.json: platform.version: ")
    assert PINNED_COMMAND in result.stderr
    assert not (tmp_path / "new").exists()


def invalid_config(case: str, tmp_path: Path, demo_document: dict[str, Any]) -> Path:
    path = tmp_path / "config" / "hub.json"
    path.parent.mkdir()
    if case == "wrong-schema":
        demo_document["schema_version"] = 2
    elif case == "pin-before-schema":
        demo_document["platform"]["version"] = "0.0.1"
        demo_document["schema_version"] = 2
    elif case == "model-error":
        demo_document["project"]["name"] = "Demo"
    if case == "invalid-json":
        path.write_bytes(b'{"schema_version": 1,')
    elif case == "fifo":
        os.mkfifo(path)
    elif case != "missing-file":
        path.write_bytes(dump_json(demo_document))
    return path


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("wrong-schema", "hub.json: schema_version: schema version 2 is not supported"),
        ("pin-before-schema", "hub.json: platform.version: this hub is pinned to 0.0.1"),
        ("model-error", "hub.json: project.name: String should match pattern"),
        ("invalid-json", "hub.json: $: not valid JSON"),
        ("missing-file", "hub.json: $: cannot read "),
        ("fifo", "hub.json: $: cannot read "),
    ],
    ids=[
        "wrong-schema",
        "pin-before-schema",
        "model-error",
        "invalid-json",
        "missing-file",
        "fifo",
    ],
)
@pytest.mark.usefixtures("alarm")
def test_reports_config_problems_in_order_when_config_invalid(
    tmp_path: Path, demo_document: dict[str, Any], *, case: str, expected: str
) -> None:
    config = invalid_config(case, tmp_path, demo_document)
    existing = tmp_path / "hub"
    existing.mkdir()
    (existing / "notes.txt").write_text("mine\n", encoding="utf-8")
    absent = tmp_path / "new" / "hub"

    results = [
        run_init(["--config", str(config), "--dir", str(folder)]) for folder in (existing, absent)
    ]

    for result in results:
        assert result.exit_code == 1
        assert result.stdout == ""
        lines = result.stderr.splitlines()
        assert lines[0].startswith(expected), lines
        assert all(line.startswith("hub.json: ") for line in lines)
    if case == "fifo":
        assert "not a regular file" in results[0].stderr
    assert listing(existing) == [("notes.txt", b"mine\n")]
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("pinned", ["running", "other"])
def test_refuses_modules_when_config_selects_them(
    tmp_path: Path, target: Path, demo_document: dict[str, Any], *, pinned: str
) -> None:
    demo_document["modules"] = {"cloud": {}, "bench": {}}
    if pinned == "other":
        demo_document["platform"]["version"] = "0.0.1"
    config = write_config(tmp_path, demo_document)

    result = run_init(["--config", str(config), "--dir", str(target)])

    assert result.exit_code == 1
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert len(lines) == 1
    if pinned == "running":
        assert (
            lines[0]
            == "hub.json: modules: bench, cloud: not supported yet (module templates ship later)"
        )
    else:
        # The module check runs after the pin: a pin mismatch still reports the pin.
        assert PINNED_COMMAND in lines[0]
        assert "modules" not in lines[0]
    assert listing(target) == []


def test_writes_into_cwd_when_dir_absent(
    git_on_path: Any, monkeypatch: pytest.MonkeyPatch, target: Path, *, demo_flags: list[str]
) -> None:
    monkeypatch.chdir(target)

    result = run_init(demo_flags)

    assert result.exit_code == 0, result.stderr
    assert result.stdout.splitlines()[0].endswith(f" links in {real(target)}")
    assert (target / "hub.lock").is_file()


def test_creates_dir_with_parents_when_checks_pass(
    git_on_path: Any, tmp_path: Path, demo_flags: list[str]
) -> None:
    nested = tmp_path / "a" / "b" / "c"

    result = run_init([*demo_flags, "--dir", str(nested)])

    assert result.exit_code == 0, result.stderr
    assert result.stdout.splitlines()[0] == created_line(written_config(nested), nested)
    assert (nested / "hub.lock").is_file()


def test_exits_one_when_dir_is_file(
    git_on_path: Any, tmp_path: Path, demo_flags: list[str]
) -> None:
    a_file = tmp_path / "hub-file"
    a_file.write_bytes(b"not a folder\n")

    result = run_init([*demo_flags, "--dir", str(a_file)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.splitlines() == [f"{real(a_file)}: not a folder"]
    assert a_file.read_bytes() == b"not a folder\n"


def test_writes_into_link_target_when_dir_is_symlink(
    git_on_path: Any, tmp_path: Path, demo_flags: list[str]
) -> None:
    folder = tmp_path / "real-hub"
    folder.mkdir()
    link = tmp_path / "hub-link"
    link.symlink_to(folder, target_is_directory=True)

    result = run_init([*demo_flags, "--dir", str(link)])

    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == created_line(written_config(folder), folder)
    assert lines[3] == f"  1. cd {real(folder)}"
    assert (folder / "hub.lock").is_file()
    assert link.is_symlink()


def test_names_only_branch_prefix_when_git_holds_values(git_on_path: Any, target: Path) -> None:
    result = run_init([*REQUIRED_FLAGS, "--dir", str(target)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.splitlines() == ["--branch-prefix: Field required"]
    assert listing(target) == []


def test_reads_missing_values_from_git_when_flags_absent(git_on_path: Any, target: Path) -> None:
    result = run_init([*REQUIRED_FLAGS, "--branch-prefix", "jdoe/", "--dir", str(target)])

    assert result.exit_code == 0, result.stderr
    project = written_config(target).project
    assert (project.author_name, project.author_email, project.hub_repo) == (
        "Git Author",
        "git.author@example.com",
        "acme/git-hub",
    )
    # Read-only calls, each run in the target.
    assert git_on_path.calls() == [
        (real(target), "config --get user.name"),
        (real(target), "config --get user.email"),
        (real(target), "rev-parse --show-toplevel"),
        (real(target), "config --get remote.origin.url"),
    ]


def broken_git(tmp_path: Path) -> Path:
    # An executable that is no program: the exec fails with ENOEXEC, not ENOENT.
    bin_dir = tmp_path / "broken-bin"
    bin_dir.mkdir()
    (bin_dir / "git").write_bytes(b"\x00\x01\x02\x03")
    (bin_dir / "git").chmod(0o755)
    return bin_dir


@pytest.mark.parametrize(
    ("git", "reason"),
    [
        ("empty", None),
        ("absent", "git not found"),
        ("broken", "git could not run"),
        ("hangs", "git timed out"),
    ],
    ids=["empty", "absent", "broken", "hangs"],
)
def test_names_three_flags_when_git_empty_or_absent(
    fake_git: FakeGitFactory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    no_git_path: Path,
    target: Path,
    git: str,
    reason: str | None,
) -> None:
    if git == "absent":
        monkeypatch.setenv("PATH", str(no_git_path))
    elif git == "broken":
        monkeypatch.setenv("PATH", str(broken_git(tmp_path)))
    else:
        monkeypatch.setenv("PATH", str(fake_git({}, toplevel=target, hangs=git == "hangs").bin_dir))
        monkeypatch.setattr(
            generator, "read_git_defaults", functools.partial(read_git_defaults, timeout=0.2)
        )

    result = run_init([*REQUIRED_FLAGS, "--branch-prefix", "jdoe/", "--dir", str(target)])

    assert result.exit_code == 1
    assert result.stdout == ""
    suffix = "" if reason is None else f" ({reason})"
    assert sorted(result.stderr.splitlines()) == [
        f"--author-email: Field required{suffix}",
        f"--author-name: Field required{suffix}",
        f"--hub-repo: Field required{suffix}",
    ]
    assert listing(target) == []


def test_succeeds_without_git_when_flags_given(
    monkeypatch: pytest.MonkeyPatch, no_git_path: Path, target: Path, *, demo_flags: list[str]
) -> None:
    monkeypatch.setenv("PATH", str(no_git_path))

    result = run_init([*demo_flags, "--dir", str(target)])

    assert result.exit_code == 0, result.stderr
    assert (target / "hub.lock").is_file()


@pytest.mark.parametrize(
    ("url", "hub_repo"),
    [
        (f"https://x-access-token:{LEAKED_MARK}@github.com/acme/demo-hub", "acme/demo-hub"),
        (f"https://user:{LEAKED_MARK}@gitlab.com/acme/demo-hub.git", None),
    ],
    ids=["github-token", "gitlab-token"],
)
def test_never_shows_secret_when_remote_has_token(
    fake_git: FakeGitFactory,
    monkeypatch: pytest.MonkeyPatch,
    target: Path,
    *,
    url: str,
    hub_repo: str | None,
) -> None:
    answers = GIT_ANSWERS | {"config --get remote.origin.url": url}
    monkeypatch.setenv("PATH", str(fake_git(answers, toplevel=target).bin_dir))

    result = run_init([*REQUIRED_FLAGS, "--branch-prefix", "jdoe/", "--dir", str(target)])

    if hub_repo is None:
        assert result.exit_code == 1
        assert result.stderr.splitlines() == ["--hub-repo: Field required"]
    else:
        assert result.exit_code == 0, result.stderr
        assert written_config(target).project.hub_repo == hub_repo
    for shown in (result.stdout, result.stderr):
        assert LEAKED_MARK not in shown
        assert url not in shown
    assert LEAKED_MARK.encode() not in every_byte(target)


@pytest.mark.parametrize(
    ("value", "flag", "message"),
    [
        (["--tracker", "jira:DEM"], "--tracker", "Input should be 'linear'"),
        (["--tracker", "linear"], "--tracker", "String should match pattern"),
        (["--repos", "acme"], '--repos item 1 ("acme")', "String should match pattern"),
        (
            ["--repos", "acme/a,ACME/A"],
            '--repos item 2 ("ACME/A")',
            'repo dir "A" is already used by repos[0]',
        ),
        (["--branch-prefix", "jdoe"], "--branch-prefix", "String should match pattern"),
    ],
    ids=["tracker", "tracker-no-team", "repos-shape", "repos-clash", "branch-prefix"],
)
def test_names_flag_when_flag_value_rejected(
    git_on_path: Any,
    tmp_path: Path,
    demo_flags: list[str],
    *,
    value: list[str],
    flag: str,
    message: str,
) -> None:
    flags = list(demo_flags)
    at = flags.index(value[0])
    flags[at : at + 2] = value
    absent = tmp_path / "new" / "hub"

    result = run_init([*flags, "--dir", str(absent)])

    assert result.exit_code == 1
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert lines
    assert all(line.startswith(f"{flag}: ") for line in lines), lines
    assert any(message in line for line in lines), lines
    assert not (tmp_path / "new").exists()


def test_names_project_when_project_rejected(git_on_path: Any, target: Path) -> None:
    flags = ["Demo", *REQUIRED_FLAGS[1:], "--branch-prefix", "jdoe/"]

    result = run_init([*flags, "--dir", str(target)])

    assert result.exit_code == 1
    assert result.stderr.splitlines() == [
        "PROJECT: String should match pattern '^[a-z0-9]+(-[a-z0-9]+)*$'"
    ]


def failing_run(
    case: str,
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flags: list[str],
    document: dict[str, Any],
) -> tuple[list[str], Path]:
    """The arguments of a run that fails at ``case``'s pipeline step, and its target."""
    nested = tmp_path / "new" / "hub"
    if case == "missing-flag":
        at = flags.index("--branch-prefix")
        del flags[at : at + 2]
        return [*flags, "--dir", str(nested)], nested
    if case == "rejected-flag":
        flags[flags.index("--tracker") + 1] = "jira:DEM"
        return [*flags, "--dir", str(nested)], nested
    if case == "modules":
        document["modules"] = {"bench": {}}
        return ["--config", str(write_config(tmp_path, document)), "--dir", str(nested)], nested
    target = tmp_path / "case-hub"
    if case == "dir-is-file":
        target.write_bytes(b"x")
        return [*flags, "--dir", str(target)], target
    target.mkdir()
    if case == "tree-refusal":
        (target / "notes.txt").write_bytes(b"mine\n")
    else:

        def failing_replace(*_args: object, **_kwargs: object) -> None:
            raise OSError(errno.EIO, os.strerror(errno.EIO))

        monkeypatch.setattr(os, "replace", failing_replace)
    return [*flags, "--dir", str(target)], target


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("missing-flag", "--branch-prefix: Field required"),
        ("rejected-flag", "--tracker: Input should be 'linear'"),
        ("modules", "hub.json: modules: bench: not supported yet (module templates ship later)"),
        ("dir-is-file", "{target}: not a folder"),
        ("tree-refusal", "notes.txt: not part of the hub; run hub sync --adopt"),
        ("write-error", "{first_write}: Input/output error"),
    ],
    ids=["missing-flag", "rejected-flag", "modules", "dir-is-file", "tree-refusal", "write-error"],
)
def test_prints_nothing_on_stdout_when_init_fails(
    git_on_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    demo_flags: list[str],
    demo_document: dict[str, Any],
    case: str,
    expected: str,
) -> None:
    args, target = failing_run(
        case, tmp_path=tmp_path, monkeypatch=monkeypatch, flags=demo_flags, document=demo_document
    )
    before = listing(target) if target.is_dir() else None
    rendered = render_hub(HubConfig.model_validate(demo_document))
    first_write = min(file.path for file in rendered.files)

    result = run_init(args)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.splitlines() == [
        expected.format(target=real(target), first_write=first_write)
    ]
    if case == "dir-is-file":
        assert target.read_bytes() == b"x"
    elif before is None:
        # Checks come first: an absent target is not created.
        assert not (tmp_path / "new").exists()
    elif case != "write-error":
        assert listing(target) == before
    else:
        assert not (target / "hub.lock").exists()


def test_prints_every_refusal_sorted_when_target_conflicts(
    git_on_path: Any, target: Path, demo_flags: list[str]
) -> None:
    (target / "notes.txt").write_bytes(b"mine\n")
    (target / "Makefile").write_bytes(b"all:\n")
    # A name that would fake an output line if printed as is.
    (target / "evil\nhub.lock: fake").write_bytes(b"")
    before = listing(target)

    result = run_init([*demo_flags, "--dir", str(target)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.splitlines() == [
        "Makefile: differs from its render; run hub sync --adopt",
        '"evil\\nhub.lock: fake": not part of the hub; run hub sync --adopt',
        "notes.txt: not part of the hub; run hub sync --adopt",
    ]
    assert listing(target) == before


def test_prints_notes_when_write_error_has_notes(
    git_on_path: Any, monkeypatch: pytest.MonkeyPatch, target: Path, *, demo_flags: list[str]
) -> None:
    def failing_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EIO, os.strerror(errno.EIO))

    def failing_unlink(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EACCES, os.strerror(errno.EACCES))

    monkeypatch.setattr(os, "replace", failing_replace)
    monkeypatch.setattr(os, "unlink", failing_unlink)

    result = run_init([*demo_flags, "--dir", str(target)])

    assert result.exit_code == 1
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert len(lines) == 2
    assert lines[0].endswith(": Input/output error")
    written = lines[0].removesuffix(": Input/output error")
    folder, _, name = written.rpartition("/")
    assert lines[1].startswith(f"{folder}/.{name}.hub-tmp-" if folder else f".{name}.hub-tmp-")
    assert lines[1].endswith(": not removed: Permission denied")


@pytest.mark.parametrize(
    ("message", "shown"),
    [
        ("brain: Permission denied", "brain: Permission denied"),
        ("evil\nname: Permission denied", '"evil\\nname: Permission denied"'),
    ],
    ids=["plain", "newline"],
)
def test_prints_generator_error_when_tree_cannot_be_read(
    git_on_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    target: Path,
    *,
    demo_flags: list[str],
    message: str,
    shown: str,
) -> None:
    def failing_read(*_args: object, **_kwargs: object) -> None:
        raise GeneratorError(message)

    monkeypatch.setattr(generator, "read_hub_tree", failing_read)

    result = run_init([*demo_flags, "--dir", str(target)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.splitlines() == [shown]
    assert listing(target) == []
