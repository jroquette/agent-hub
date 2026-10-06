"""``hub doctor``: its command surface, the root and ``hub.json`` steps, and the exit codes.

A failed config runs only the config rules and reads no other file, so those cases copy only
``hub.json`` into an empty folder (plan O6); the others run on a copy of the ``DEMO`` hub, which is
walked, not listed by git, unless the test commits it (plan E21 e): only ``features.tracker`` reads
the listing.
"""

import errno
import json
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable, Iterator
from importlib.metadata import version
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from click import unstyle
from typer.testing import CliRunner, Result

from agent_hub.cli import doctor_command
from agent_hub.cli.main import app
from agent_hub.core.doctor.finding import Read, Rule
from agent_hub.core.doctor.registry import REGISTRY
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.json_form import dump_json
from agent_hub.core.testing.builders import a_second_repo, a_two_team_document
from agent_hub.generator import render_hub as render_hub_module

# The conftest's in-process doctor run, its path recorder and the recorder's filters (tests
# cannot import a conftest in importlib mode).
type DoctorRunner = Callable[..., Result]
type ReadsIn = Callable[[list[PathRead], Path], set[str]]
type Ancestors = Callable[..., set[str]]
type CheckoutFactory = Callable[[str], Path]
type Under = Callable[[list["PathRead"], Path], set[str]]


class PathRead(NamedTuple):
    """The conftest's ``PathRead``: the call, the path, its descriptor's identity, open flags."""

    call: str
    path: str
    identity: tuple[int, int] | None = None
    flags: int | str | None = None


VERSION = version("agent-hub-cli")
PINNED_COMMAND = (
    "uvx --from git+https://github.com/jroquette/agent-hub@v0.0.1"
    "#subdirectory=packages/agent-hub hub"
)
SCHEMA_FIX = "Fix: fix hub.json (docs/design/project-config.md)"
CLEAN = "0 errors, 0 warnings, 0 infos"
ONE_ERROR = "1 error, 0 warnings, 0 infos"
NOT_A_HUB = (
    ": not a hub: no hub.json in this folder (hub doctor runs in the hub folder, never a parent)"
)
FIFO_ALARM_SECONDS = 5
NOT_ADOPTED_LINE = (
    "warning lock.drift hub.lock: not adopted: no hub.lock records this hub's files"
    " Fix: run hub sync --adopt"
)
# The seeded Makefile.project holds two comment lines; the planted rule is the third.
OVERRIDE_LINE = (
    "warning makefile.override Makefile.project:3: redefines target 'check'"
    " Fix: rename the project target"
)
LISTING_FIX = (
    "Fix: fix the cause above so every file can be listed and read, then run hub doctor again"
)
# The characters of the box Rich may draw around a usage error.
BOX_CHARACTERS = "│╭╮╰╯─"


@pytest.fixture(autouse=True)
def demo_api_folder(tmp_path: Path) -> None:
    """DEMO's one repo as an empty folder next to the hub: a checkout with no file (plan E3a).

    So a run of every rule on a ``DEMO`` hub reports no missing checkout; the tests of the
    checkouts themselves make them git repos (``demo_checkout``) or remove them.
    """
    (tmp_path / "demo-api").mkdir()


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


def assert_refused(result: Result, message: str) -> None:
    """Exit 2 with ``message`` as one line of the usage error on stderr, nothing on stdout.

    Typer draws the error in a box whose width, colors and borders follow the terminal (CI sets
    ``FORCE_TERMINAL``), so the box is stripped and only the message line is pinned.
    """
    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    shown = unstyle(result.stderr)
    assert "not a hub" not in shown
    assert "Usage: hub doctor" in shown
    texts = [line.strip(BOX_CHARACTERS + " ") for line in shown.splitlines()]
    assert [text for text in texts if text == message] == [message], shown
    assert [text for text in texts if message in text] == [message], shown


def config_only_hub(tmp_path: Path, content: bytes) -> Path:
    """A folder holding only ``hub.json`` with ``content``."""
    root = tmp_path / "hub"
    root.mkdir()
    (root / "hub.json").write_bytes(content)
    return root


def lines_of(result: Result, *, exit_code: int) -> list[str]:
    """The stdout lines of a run that exited ``exit_code`` with nothing on stderr."""
    assert result.exit_code == exit_code, result.output
    # An exit, not an exception the runner caught.
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.stderr == ""
    return result.stdout.splitlines()


def plant_check_override(root: Path) -> None:
    """Give ``Makefile.project`` a rule for ``check``, a target the managed ``Makefile`` defines."""
    project = root / "Makefile.project"
    project.write_bytes(project.read_bytes() + b"check:\n\t@echo ours\n")


def schema_line(message: str) -> str:
    return f"error config.schema hub.json: {message} {SCHEMA_FIX}"


def commit_all(root: Path) -> None:
    """Make ``root`` a git work tree with every file committed, with a hermetic git."""
    git = shutil.which("git")
    assert git is not None
    env = {"HOME": str(root.parent), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    author = ["-c", "user.name=Jane Doe", "-c", "user.email=jane@example.com"]
    for args in (
        ["init", "-q"],
        ["add", "-A"],
        [*author, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"],
    ):
        subprocess.run([git, *args], cwd=root, env=env, check=True, capture_output=True)  # noqa: S603 - absolute git, fixed arguments


def test_lists_options_when_help_requested(demo_hub: Path, run_doctor: DoctorRunner) -> None:
    shown = CliRunner().invoke(app, ["doctor", "--help"], env={"COLUMNS": "120"})
    ran = run_doctor(demo_hub)
    unknown = run_doctor(demo_hub, "--nope")

    assert shown.exit_code == 0
    help_text = " ".join(unstyle(shown.stdout).split())
    assert "--only RULE" in help_text
    assert "Run only this rule (and config.schema); repeatable." in help_text
    assert "--json" in help_text
    assert "Print one JSON object instead of lines." in help_text
    assert "not implemented yet" not in ran.output
    assert lines_of(ran, exit_code=0) == [CLEAN]
    assert unknown.exit_code == 2
    assert "Usage:" in unknown.stderr
    assert unknown.stdout == ""


@pytest.mark.parametrize("case", ["empty-folder", "hub-subfolder"])
def test_exits_two_when_cwd_not_hub(
    tmp_path: Path,
    demo_hub: Path,
    run_doctor: DoctorRunner,
    *,
    path_reads: list[PathRead],
    reads_in: ReadsIn,
    ancestors: Ancestors,
    case: str,
) -> None:
    if case == "empty-folder":
        folder = tmp_path / "empty"
        folder.mkdir()
    else:
        folder = demo_hub / "brain"
        assert (demo_hub / "hub.json").is_file()
    real = os.path.realpath(folder)
    allowed = ancestors(real, up_to=tmp_path) | {os.path.join(real, "hub.json")}
    path_reads.clear()

    result = run_doctor(folder)

    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    assert result.stderr == f"{real}{NOT_A_HUB}\n"
    assert reads_in(path_reads, tmp_path) <= allowed


@pytest.mark.usefixtures("alarm")
@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("folder", "not a regular file"),
        ("fifo", "not a regular file"),
        ("dangling-link", "No such file or directory"),
        ("unreadable", "Permission denied"),
        ("lstat-refused", "Permission denied"),
    ],
    ids=["folder", "fifo", "dangling-link", "unreadable", "lstat-refused"],
)
def test_reports_config_schema_when_hub_json_not_regular(
    tmp_path: Path,
    demo_document: dict[str, Any],
    run_doctor: DoctorRunner,
    *,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    reason: str,
) -> None:
    root = tmp_path / "hub"
    root.mkdir()
    config = root / "hub.json"
    if case == "folder":
        config.mkdir()
    elif case == "fifo":
        os.mkfifo(config)
    elif case == "dangling-link":
        config.symlink_to("gone.json")
    else:
        config.write_bytes(dump_json(demo_document))
        # "unreadable" refuses the open alone; "lstat-refused" refuses every look at hub.json,
        # as an unsearchable folder does: the lstat error is not "absent", so it is no exit 2.
        calls = ("open",) if case == "unreadable" else ("open", "stat", "lstat")
        for call in calls:
            monkeypatch.setattr(os, call, refusing_hub_json(getattr(os, call)))
    shown = json.dumps(os.path.join(os.path.realpath(root), "hub.json"))

    lines = lines_of(run_doctor(root), exit_code=1)

    assert lines == [schema_line(f"$: cannot read {shown}: {reason}"), ONE_ERROR]


def refusing_hub_json(real: Callable[..., Any]) -> Callable[..., Any]:
    """``real``, except that a path ending in ``hub.json`` raises ``EACCES``."""

    def refusing(path: Any, *args: Any, **kwargs: Any) -> Any:
        if not isinstance(path, int) and os.fsdecode(path).endswith("hub.json"):
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), path)
        return real(path, *args, **kwargs)

    return refusing


def invalid_config(case: str, document: dict[str, Any]) -> tuple[bytes, str]:
    """The ``hub.json`` bytes of an invalid case and the start of its one problem."""
    if case == "invalid-json":
        return b'{"schema_version": 1,', "$: "
    if case == "missing-key":
        del document["project"]
        return dump_json(document), "project: "
    if case == "unknown-key":
        document["surprise"] = True
        return dump_json(document), "surprise: "
    document["project"]["name"] = "Demo"
    return dump_json(document), "project.name: String should match pattern"


@pytest.mark.parametrize("only", [(), ("--only", "lock.drift")], ids=["all", "only-lock-drift"])
@pytest.mark.parametrize("case", ["invalid-json", "missing-key", "unknown-key", "bad-name"])
def test_runs_only_config_schema_when_config_invalid(
    tmp_path: Path,
    demo_document: dict[str, Any],
    run_doctor: DoctorRunner,
    *,
    case: str,
    only: tuple[str, ...],
) -> None:
    content, problem = invalid_config(case, demo_document)
    # No hub.lock: had lock.drift run, it would report the hub as not adopted.
    root = config_only_hub(tmp_path, content)

    lines = lines_of(run_doctor(root, *only), exit_code=1)

    assert len(lines) == 2, lines
    assert lines[0].startswith(f"error config.schema hub.json: {problem}"), lines
    assert lines[0].endswith(f" {SCHEMA_FIX}")
    assert lines[1] == ONE_ERROR


def test_reports_transport_when_value_unknown(
    demo_hub: Path, demo_document: dict[str, Any], run_doctor: DoctorRunner
) -> None:
    demo_document["tracker"]["transport"] = "connector"
    (demo_hub / "hub.json").write_bytes(dump_json(demo_document))

    lines = lines_of(run_doctor(demo_hub, "--only", "config.schema"), exit_code=1)

    assert lines == [schema_line("tracker.transport: Input should be 'api' or 'mcp'"), ONE_ERROR]


def test_stays_clean_when_transport_absent(
    demo_hub: Path, demo_document: dict[str, Any], run_doctor: DoctorRunner
) -> None:
    assert "transport" not in demo_document["tracker"]
    assert b'"transport"' not in (demo_hub / "hub.json").read_bytes()

    lines = lines_of(run_doctor(demo_hub, "--only", "config.schema"), exit_code=0)

    assert lines == [CLEAN]


def test_passes_config_schema_when_identity_absent(
    demo_hub: Path, demo_document: dict[str, Any], run_doctor: DoctorRunner
) -> None:
    # A team hub: each developer's identity comes from hub.local.json or git config.
    for key in ("branch_prefix", "author_name", "author_email"):
        del demo_document["project"][key]
    (demo_hub / "hub.json").write_bytes(dump_json(demo_document))

    lines = lines_of(run_doctor(demo_hub, "--only", "config.schema"), exit_code=0)

    assert lines == [CLEAN]


def test_passes_config_schema_when_repo_sets_branch(
    demo_hub: Path, demo_document: dict[str, Any], run_doctor: DoctorRunner
) -> None:
    demo_document["repos"][0]["default_branch"] = "master"
    (demo_hub / "hub.json").write_bytes(dump_json(demo_document))

    lines = lines_of(run_doctor(demo_hub, "--only", "config.schema"), exit_code=0)

    assert lines == [CLEAN]


def test_passes_config_schema_when_tracker_lists_teams(
    demo_hub: Path, demo_document: dict[str, Any], run_doctor: DoctorRunner
) -> None:
    demo_document["tracker"] = a_two_team_document()["tracker"]
    (demo_hub / "hub.json").write_bytes(dump_json(demo_document))

    lines = lines_of(run_doctor(demo_hub, "--only", "config.schema"), exit_code=0)

    assert lines == [CLEAN]


def test_reports_team_keys_problem_when_both_set(
    demo_hub: Path, demo_document: dict[str, Any], run_doctor: DoctorRunner
) -> None:
    demo_document["tracker"]["teams"] = ["APP", "OPS"]
    (demo_hub / "hub.json").write_bytes(dump_json(demo_document))

    lines = lines_of(run_doctor(demo_hub, "--only", "config.schema"), exit_code=1)

    assert lines == [
        schema_line("tracker.teams: set tracker.team or tracker.teams, not both"),
        ONE_ERROR,
    ]


def test_reports_repo_branch_problem_when_value_invalid(
    demo_hub: Path, demo_document: dict[str, Any], run_doctor: DoctorRunner
) -> None:
    demo_document["repos"][0]["default_branch"] = "-x"
    (demo_hub / "hub.json").write_bytes(dump_json(demo_document))

    lines = lines_of(run_doctor(demo_hub, "--only", "config.schema"), exit_code=1)

    assert lines == [
        schema_line(
            "repos[0].default_branch: String should match pattern"
            " '^[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*(?:/[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*)*$'"
        ),
        ONE_ERROR,
    ]


CONTRACT_SYNC = {"source": "demo-api", "target": "demo-web"}


@pytest.mark.parametrize(
    ("modules", "problem"),
    [
        (
            {"contract-sync": {"target": "demo-web"}},
            "modules.contract-sync.source: Field required",
        ),
        (
            {"contract-sync": CONTRACT_SYNC | {"branch": "main"}},
            "modules.contract-sync.branch: Extra inputs are not permitted",
        ),
        (
            {"contract-sync": CONTRACT_SYNC | {"source": 1}},
            "modules.contract-sync.source: Input should be a valid string",
        ),
        (
            {"contract-sync": CONTRACT_SYNC | {"target": None}},
            "modules.contract-sync.target: null is not a value; give a value or leave the key out",
        ),
        (
            {"contract-sync": CONTRACT_SYNC | {"target": "nope"}},
            'modules.contract-sync.target: repo dir "nope" is not in repos',
        ),
        (
            {"contract-sync": CONTRACT_SYNC | {"target": "demo-api"}},
            'modules.contract-sync.target: target "demo-api" is the source too;'
            " give two different repos",
        ),
        ({"cloud": {"x": 1}}, "modules.cloud.x: Extra inputs are not permitted"),
        ({"deploy": {}}, "modules.deploy: Extra inputs are not permitted"),
    ],
    ids=["missing", "extra", "not-string", "null", "unknown-repo", "same-repo", "cloud", "deploy"],
)
def test_reports_contract_sync_problem_when_settings_invalid(
    tmp_path: Path,
    demo_document: dict[str, Any],
    run_doctor: DoctorRunner,
    *,
    modules: dict[str, Any],
    problem: str,
) -> None:
    demo_document["repos"].append(a_second_repo())
    demo_document["modules"] = modules
    root = config_only_hub(tmp_path, dump_json(demo_document))

    lines = lines_of(run_doctor(root, "--only", "config.schema"), exit_code=1)

    assert lines == [schema_line(problem), ONE_ERROR]


@pytest.mark.parametrize(
    "modules",
    [("cloud",), ("marketplace",), ("bench", "cloud", "contract-sync", "marketplace")],
    ids=["cloud", "marketplace", "all"],
)
def test_finds_no_stale_reference_when_fresh_hub_selects_modules(
    tmp_path: Path,
    demo_document: dict[str, Any],
    run_doctor: DoctorRunner,
    *,
    modules: tuple[str, ...],
) -> None:
    # AGH-17: AGENTS.md names the selected modules' files, which a fresh hub holds, so none is a
    # stale reference.
    demo_document["repos"].append(a_second_repo())
    source, target = (repo["dir"] for repo in demo_document["repos"])
    settings = {"contract-sync": {"source": source, "target": target}}
    demo_document["modules"] = {module: settings.get(module, {}) for module in modules}
    config = tmp_path / "hub.json"
    config.write_bytes(dump_json(demo_document))
    root = tmp_path / "hub"
    created = CliRunner().invoke(app, ["init", "--config", str(config), "--dir", str(root)])
    assert created.exit_code == 0, created.stderr

    assert lines_of(run_doctor(root, "--only", "instructions.refs"), exit_code=0) == [CLEAN]


@pytest.mark.parametrize(
    ("project_branch", "repo_branch"),
    [("main", "release/2"), ("stable/1", None)],
    ids=["repo-branch", "project-branch"],
)
def test_finds_no_stale_reference_when_fresh_hub_names_branch_with_slash(
    tmp_path: Path,
    demo_document: dict[str, Any],
    run_doctor: DoctorRunner,
    *,
    project_branch: str,
    repo_branch: str | None,
) -> None:
    # AGENTS.md names the configured branches as code spans; one with a ``/`` looks like a path
    # but is not a stale reference.
    demo_document["project"]["default_branch"] = project_branch
    if repo_branch is not None:
        demo_document["repos"][0]["default_branch"] = repo_branch
    config = tmp_path / "hub.json"
    config.write_bytes(dump_json(demo_document))
    root = tmp_path / "hub"
    created = CliRunner().invoke(app, ["init", "--config", str(config), "--dir", str(root)])
    assert created.exit_code == 0, created.stderr

    assert lines_of(run_doctor(root, "--only", "instructions.refs"), exit_code=0) == [CLEAN]


def test_finds_same_findings_when_fresh_hub_lists_teams(
    tmp_path: Path, demo_document: dict[str, Any], run_doctor: DoctorRunner
) -> None:
    # AGH-56: a fresh hub with two tracker teams renders their names into AGENTS.md and the
    # plugin; every check finds what it finds in a fresh one-team hub, and nothing more.
    two_team_document = {**demo_document, "tracker": a_two_team_document()["tracker"]}
    results = []
    for name, document in (("one", demo_document), ("two", two_team_document)):
        base = tmp_path / name
        base.mkdir()
        config = base / "hub.json"
        config.write_bytes(dump_json(document))
        root = base / "hub"
        created = CliRunner().invoke(app, ["init", "--config", str(config), "--dir", str(root)])
        assert created.exit_code == 0, created.stderr
        result = run_doctor(root)
        results.append((result.exit_code, result.stdout.splitlines(), result.stderr))

    assert results[1] == results[0]


@pytest.mark.parametrize("schema_version", [1, 2], ids=["schema-ok", "schema-wrong"])
def test_reports_pin_only_when_pin_differs(
    demo_hub: Path,
    demo_document: dict[str, Any],
    run_doctor: DoctorRunner,
    *,
    schema_version: int,
) -> None:
    demo_document["platform"]["version"] = "0.0.1"
    demo_document["schema_version"] = schema_version
    (demo_hub / "hub.json").write_bytes(dump_json(demo_document))

    lines = lines_of(run_doctor(demo_hub), exit_code=1)

    assert lines == [
        f"error platform.version hub.json: this hub is pinned to 0.0.1 but this hub command is"
        f" {VERSION}. Fix: run the pinned release: {PINNED_COMMAND}",
        ONE_ERROR,
    ]


class TestExitCodes:
    def test_exits_one_when_error_found(
        self, demo_hub: Path, demo_document: dict[str, Any], run_doctor: DoctorRunner
    ) -> None:
        demo_document["surprise"] = True
        (demo_hub / "hub.json").write_bytes(dump_json(demo_document))

        lines = lines_of(run_doctor(demo_hub), exit_code=1)

        assert [line.split(" ")[:3] for line in lines[:-1]] == [
            ["error", "config.schema", "hub.json:"]
        ]
        assert lines[-1] == ONE_ERROR

    def test_exits_two_when_only_names_unknown_rule(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        path_reads: list[PathRead],
        reads_in: ReadsIn,
    ) -> None:
        # Outside any hub: the refusal comes before the root and hub.json are looked at.
        monkeypatch.chdir(tmp_path)
        path_reads.clear()

        result = CliRunner().invoke(app, ["doctor", "--only", "nope"], env={"COLUMNS": "80"})

        assert_refused(result, "unknown rule in --only: nope")
        assert reads_in(path_reads, tmp_path) == set()

    @pytest.mark.parametrize(
        ("modules", "message"),
        [(None, "module bench is not selected")],
        ids=["unselected"],
    )
    def test_exits_two_when_only_names_module_rule(
        self,
        demo_hub: Path,
        demo_document: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        *,
        modules: dict[str, Any] | None,
        message: str,
    ) -> None:
        if modules is not None:
            demo_document["modules"] = modules
        (demo_hub / "hub.json").write_bytes(dump_json(demo_document))
        monkeypatch.chdir(demo_hub)

        result = CliRunner().invoke(app, ["doctor", "--only", "bench.tasks"], env={"COLUMNS": "80"})

        assert_refused(result, message)

    def test_exits_zero_when_only_warnings_or_infos(
        self, demo_hub: Path, run_doctor: DoctorRunner
    ) -> None:
        (demo_hub / "hub.lock").unlink()

        lines = lines_of(run_doctor(demo_hub), exit_code=0)

        assert lines == [NOT_ADOPTED_LINE, "0 errors, 1 warning, 0 infos"]

    def test_runs_only_named_rule_when_only_given(
        self, demo_hub: Path, run_doctor: DoctorRunner
    ) -> None:
        # A lock.drift problem (a managed file edited) that only a run of lock.drift reports.
        (demo_hub / "AGENTS.md").write_bytes(b"# Agents, edited\n")
        plant_check_override(demo_hub)

        lines = lines_of(run_doctor(demo_hub, "--only", "makefile.override"), exit_code=0)

        assert lines == [OVERRIDE_LINE, "0 errors, 1 warning, 0 infos"]

    def test_notes_disabled_rule_when_only_names_it(
        self, demo_hub: Path, demo_document: dict[str, Any], run_doctor: DoctorRunner
    ) -> None:
        # lock.drift would warn "not adopted"; makefile.override, retuned to error, sets the exit.
        demo_document["doctor"] = {
            "rules": {"lock.drift": {"enabled": False}, "makefile.override": {"severity": "error"}}
        }
        (demo_hub / "hub.json").write_bytes(dump_json(demo_document))
        (demo_hub / "hub.lock").unlink()
        plant_check_override(demo_hub)

        result = run_doctor(demo_hub, "--only", "lock.drift", "--only", "makefile.override")

        assert result.exit_code == 1, result.output
        assert result.stderr == "lock.drift: disabled in hub.json doctor.rules\n"
        assert result.stdout.splitlines() == [
            OVERRIDE_LINE.replace("warning", "error", 1),
            ONE_ERROR,
        ]


TASKS = "brain/workflow/bench/tasks.json"
BENCH_SHA = "0123456789abcdef0123456789abcdef01234567"


def a_bench_case(**changes: Any) -> dict[str, Any]:
    """A bench case valid against ``DEMO`` (its one repo ``demo-api``), with ``changes``."""
    case: dict[str, Any] = {
        "id": "T1",
        "repo": "demo-api",
        "merge": BENCH_SHA,
        "prompt": "Add the fix",
        "hidden_tests": ["tests/test_fix.py"],
        "test_cmd": ["python3", "-m", "pytest", "-q"],
    }
    return case | changes


def write_bench(
    root: Path, document: dict[str, Any], *, modules: dict[str, Any] | None, cases: object
) -> None:
    """Give the hub ``modules`` (none when ``None``) and ``cases`` in the bench's tasks.json."""
    if modules is not None:
        document["modules"] = modules
    (root / "hub.json").write_bytes(dump_json(document))
    tasks = root / TASKS
    tasks.parent.mkdir(parents=True, exist_ok=True)
    tasks.write_bytes(dump_json(cases))


class TestBenchTasks:
    """``bench.tasks`` runs only when module ``bench`` is selected (spec AC-17.2, AC-17.3, E6)."""

    @pytest.mark.parametrize("cases", [[], [a_bench_case()]], ids=["empty", "valid"])
    def test_runs_rule_when_only_names_it_and_bench_selected(
        self,
        demo_hub: Path,
        demo_document: dict[str, Any],
        run_doctor: DoctorRunner,
        *,
        cases: list[dict[str, Any]],
    ) -> None:
        write_bench(demo_hub, demo_document, modules={"bench": {}}, cases=cases)
        # A lock.drift problem that only a run of lock.drift reports.
        (demo_hub / "hub.lock").unlink()

        lines = lines_of(run_doctor(demo_hub, "--only", "bench.tasks"), exit_code=0)

        assert lines == [CLEAN]

    @pytest.mark.parametrize("only", [(), ("--only", "bench.tasks")], ids=["all", "only"])
    def test_reports_findings_when_cases_invalid(
        self,
        demo_hub: Path,
        demo_document: dict[str, Any],
        run_doctor: DoctorRunner,
        *,
        only: tuple[str, ...],
    ) -> None:
        cases = [a_bench_case(), a_bench_case(repo="zz"), a_bench_case(id="T3", merge="--orphan")]
        write_bench(demo_hub, demo_document, modules={"bench": {}}, cases=cases)

        lines = lines_of(run_doctor(demo_hub, *only), exit_code=1)

        fix = "Fix: fix the case in tasks.json"
        assert lines == [
            f'error bench.tasks {TASKS}: [1].id: duplicate id "T1" {fix}',
            f'error bench.tasks {TASKS}: [1].repo: "zz" is not in repos (demo-api) {fix}',
            f"error bench.tasks {TASKS}: [2].merge: must be a commit sha:"
            f" 7 to 40 characters among 0-9 and a-f {fix}",
            "3 errors, 0 warnings, 0 infos",
        ]

    def test_skips_rule_when_bench_unselected(
        self, demo_hub: Path, demo_document: dict[str, Any], run_doctor: DoctorRunner
    ) -> None:
        write_bench(demo_hub, demo_document, modules={"cloud": {}}, cases="not a list")

        lines = lines_of(run_doctor(demo_hub, "--json"), exit_code=0)

        assert json.loads("\n".join(lines)) == {
            "findings": [],
            "totals": {"errors": 0, "warnings": 0, "infos": 0},
        }

    def test_rejects_rule_settings_when_bench_unselected(
        self, demo_hub: Path, demo_document: dict[str, Any], run_doctor: DoctorRunner
    ) -> None:
        demo_document["doctor"] = {"rules": {"bench.tasks": {"enabled": False}}}
        write_bench(demo_hub, demo_document, modules=None, cases="not a list")

        lines = lines_of(run_doctor(demo_hub), exit_code=1)

        assert lines == [
            schema_line(
                'doctor.rules["bench.tasks"]: rule "bench.tasks" belongs to module "bench",'
                ' which is not selected; add "bench" to modules or remove the rule'
            ),
            ONE_ERROR,
        ]


def test_runs_no_git_when_no_rule_needs_listing(
    demo_hub: Path, run_doctor: DoctorRunner, path_reads: list[PathRead]
) -> None:
    commit_all(demo_hub)
    path_reads.clear()

    lines = lines_of(run_doctor(demo_hub, "--only", "platform.version"), exit_code=0)

    assert lines == [CLEAN]
    assert [read for read in path_reads if read.call == "Popen"] == []


@pytest.mark.parametrize("case", ["clean", "error"])
def test_prints_one_json_object_when_json_given(
    tmp_path: Path,
    demo_hub: Path,
    demo_document: dict[str, Any],
    *,
    run_doctor: DoctorRunner,
    case: str,
) -> None:
    if case == "error":
        demo_document["surprise"] = True
        del demo_document["project"]
        (demo_hub / "hub.json").write_bytes(dump_json(demo_document))
    empty = tmp_path / "empty"
    empty.mkdir()

    text = run_doctor(demo_hub)
    shown = run_doctor(demo_hub, "--json")
    not_hub = run_doctor(empty, "--json")

    assert shown.exit_code == text.exit_code
    assert shown.exit_code == (1 if case == "error" else 0)
    assert shown.stderr == ""
    document = json.loads(shown.stdout)
    # One object in the one JSON form, and nothing else.
    assert shown.stdout == dump_json(document).decode()
    assert list(document) == ["findings", "totals"]
    text_lines = text.stdout.splitlines()
    assert [
        f"{finding['severity']} {finding['rule']} {finding['path']}: {finding['message']}"
        f" Fix: {finding['fix']}"
        for finding in document["findings"]
    ] == text_lines[:-1]
    assert all(finding["line"] is None for finding in document["findings"])
    errors = len(document["findings"])
    assert document["totals"] == {"errors": errors, "warnings": 0, "infos": 0}
    assert (case == "error") == (errors == 2)
    assert not_hub.exit_code == 2
    assert not_hub.stdout == ""
    assert not_hub.stderr == f"{os.path.realpath(empty)}{NOT_A_HUB}\n"


def refusing_name(name: str, real: Callable[..., Any]) -> Callable[..., Any]:
    """``real``, except that a path named ``name`` (its last segment) raises ``EACCES``."""

    def refusing(path: Any, *args: Any, **kwargs: Any) -> Any:
        if not isinstance(path, int) and os.path.basename(os.fsdecode(path)) == name:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), path)
        return real(path, *args, **kwargs)

    return refusing


def test_reports_lock_drift_when_managed_paths_changed(
    demo_hub: Path, run_doctor: DoctorRunner, path_reads: list[PathRead]
) -> None:
    # Paths the lock alone names (no fixed path): only the lock's paths make them looked at.
    (demo_hub / "AGENTS.md").write_bytes(b"# Agents, edited\n")
    (demo_hub / "CLAUDE.md").unlink()
    (demo_hub / "plugin/hub-workflow/hooks/guard.py").chmod(0o644)
    retargeted = demo_hub / ".claude/agents/planner.md"
    retargeted.unlink()
    retargeted.symlink_to("../../plugin/hub-workflow/agents/architect.md")
    # Seeded: the project's, never compared.
    (demo_hub / "README.md").write_bytes(b"# Our hub\n")
    path_reads.clear()

    lines = lines_of(run_doctor(demo_hub, "--only", "lock.drift"), exit_code=1)

    assert lines == [
        "error lock.drift .claude/agents/planner.md: link target differs from its hub.lock entry"
        " (on disk -> ../../plugin/hub-workflow/agents/architect.md,"
        " hub.lock -> ../../plugin/hub-workflow/agents/planner.md) Fix: run hub sync",
        "error lock.drift AGENTS.md: content differs from its hub.lock entry Fix: run hub sync",
        "error lock.drift CLAUDE.md: missing; hub sync restores it Fix: run hub sync",
        "error lock.drift plugin/hub-workflow/hooks/guard.py: executable bit differs from its"
        " hub.lock entry (on disk -x, hub.lock +x) Fix: run hub sync",
        "4 errors, 0 warnings, 0 infos",
    ]
    # The lock's paths are looked at by path: no listing, so no git.
    assert [read for read in path_reads if read.call == "Popen"] == []


@pytest.mark.parametrize("refused", [".claude", "hub.lock"])
def test_reports_read_problem_not_adoption_when_lock_drift_cannot_read(
    demo_hub: Path, run_doctor: DoctorRunner, monkeypatch: pytest.MonkeyPatch, *, refused: str
) -> None:
    # An unreadable hub.lock is not an absent one, and an unread managed file is not missing.
    monkeypatch.setattr(os, "open", refusing_name(refused, os.open))

    lines = lines_of(run_doctor(demo_hub, "--only", "lock.drift"), exit_code=1)

    assert lines == [
        f"error lock.drift .: could not read the files: {refused}: Permission denied"
        " Fix: fix the cause above so every file can be listed and read, then run hub doctor again",
        ONE_ERROR,
    ]


def test_reports_settings_weakening_when_project_disables_hooks(
    demo_hub: Path, run_doctor: DoctorRunner, path_reads: list[PathRead]
) -> None:
    # The retimed group is found only against the release's base hooks block.
    settings_path = demo_hub / ".claude/settings.json"
    settings = json.loads(settings_path.read_bytes())
    settings["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 1
    settings_path.write_bytes(dump_json(settings))
    (demo_hub / ".claude/settings.project.json").write_bytes(dump_json({"disableAllHooks": False}))
    path_reads.clear()

    lines = lines_of(run_doctor(demo_hub, "--only", "settings.weakening"), exit_code=1)

    assert lines == [
        "error settings.weakening .claude/settings.json: hooks.Stop: a base hook group is missing"
        " or changed Fix: run hub sync",
        "error settings.weakening .claude/settings.project.json: disableAllHooks: refused: a"
        " project cannot set this key (it weakens the harness)"
        " Fix: remove disableAllHooks from .claude/settings.project.json",
        "2 errors, 0 warnings, 0 infos",
    ]
    assert [read for read in path_reads if read.call == "Popen"] == []


def test_warns_not_adopted_and_runs_other_rules_when_lock_absent(
    demo_hub: Path, run_doctor: DoctorRunner
) -> None:
    (demo_hub / "hub.lock").unlink()
    plant_check_override(demo_hub)

    lines = lines_of(run_doctor(demo_hub), exit_code=0)

    assert lines == [NOT_ADOPTED_LINE, OVERRIDE_LINE, "0 errors, 2 warnings, 0 infos"]


def test_renders_nothing_when_doctor_runs(
    demo_hub: Path, run_doctor: DoctorRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every render entry point, wherever a module bound it by name, raises when called.
    renders = {name: getattr(render_hub_module, name) for name in ("render_hub", "render_entries")}
    for module in [m for name, m in sys.modules.items() if name.startswith("agent_hub.")]:
        for name, real in renders.items():
            if getattr(module, name, None) is real:
                monkeypatch.setattr(module, name, refusing_call(name))

    lines = lines_of(run_doctor(demo_hub), exit_code=0)

    assert lines == [CLEAN]


def refusing_call(name: str) -> Callable[..., Any]:
    def refusing(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail(f"hub doctor called {name}")

    return refusing


def test_leaves_no_marker_when_guard_extension_would_write(
    tmp_path: Path, demo_hub: Path, run_doctor: DoctorRunner
) -> None:
    marker = tmp_path / "imported.marker"
    extension = demo_hub / "plugin/demo/hooks/project_guard.py"
    extension.write_text(
        "import pathlib\n"
        f"pathlib.Path({str(marker)!r}).write_text('ran')\n"
        "\n\n"
        "def check(event, cfg):\n"
        "    return None\n",
        encoding="utf-8",
    )

    lines = lines_of(run_doctor(demo_hub), exit_code=0)

    assert lines == [CLEAN]
    assert not os.path.lexists(marker)


def test_checks_features_when_only_features_tracker(
    demo_hub: Path, run_doctor: DoctorRunner
) -> None:
    features = demo_hub / "brain/features"
    valid = {
        "feature": "valid",
        "linear": ["DEM-1"],
        "acs": [a_demo_ac(1, repo="demo-api"), a_demo_ac(2, repo="demo-hub")],
    }
    invalid = {
        "feature": "invalid",
        "linear": ["DEM-2"],
        "acs": [a_demo_ac(1, repo="api"), a_demo_ac(2, passes=True)],
    }
    for name, record in (("valid", valid), ("invalid", invalid)):
        (features / name).mkdir()
        (features / name / "features.json").write_bytes(dump_json(record))
    # The valid record agrees with its spec, so the cross-check runs and finds nothing.
    (features / "valid/spec.md").write_bytes(b"# Valid\n\n- **AC-1** x\n- **AC-2** y\n")
    # A lock.drift problem that only a run of lock.drift reports.
    (demo_hub / "hub.lock").unlink()

    lines = lines_of(run_doctor(demo_hub, "--only", "features.tracker"), exit_code=1)

    record = "brain/features/invalid/features.json"
    assert lines == [
        f"error features.tracker {record}: AC-1: repo must be one of demo-api, demo-hub"
        " Fix: fix the record in features.json",
        f"error features.tracker {record}: AC-2: passes=true needs evidence (command + result)"
        " Fix: record the command run and its result in evidence",
        "2 errors, 0 warnings, 0 infos",
    ]


def test_lists_files_when_rule_reads_instruction_files(
    demo_hub: Path, run_doctor: DoctorRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A rule that declares only INSTRUCTION_FILES still gets the listing its set comes from, so
    # the file that is not text is found (E28).
    reader = Rule(
        id="instructions.size",
        severity=Severity.WARNING,
        summary="A synthetic instruction-files reader.",
        module=None,
        reads=frozenset({Read.INSTRUCTION_FILES}),
        check=lambda snapshot: (),
    )
    schema = next(rule for rule in REGISTRY if rule.id == "config.schema")
    monkeypatch.setattr(doctor_command, "REGISTRY", (schema, reader))
    (demo_hub / "AGENTS.md").write_bytes(b"\xff")

    lines = lines_of(run_doctor(demo_hub), exit_code=1)

    assert lines == [
        "error instructions.size AGENTS.md: not UTF-8 text: byte 0 cannot be decoded"
        " Fix: save it as UTF-8 text",
        ONE_ERROR,
    ]


def a_demo_ac(number: int, **changes: object) -> dict[str, Any]:
    """A pending AC of the ``DEMO`` hub, valid unless ``changes`` break it."""
    ac: dict[str, Any] = {
        "id": f"AC-{number}",
        "description": "Given x When y Then z",
        "repo": "demo-api",
        "verification": f"pytest tests/unit/test_x.py::test_{number}",
        "passes": False,
        "evidence": None,
    }
    return ac | changes


@pytest.mark.parametrize("only", [(), ("--only", "features.tracker")], ids=["all", "only-features"])
def test_reports_listing_problem_once_when_git_missing(
    demo_hub: Path,
    run_doctor: DoctorRunner,
    monkeypatch: pytest.MonkeyPatch,
    *,
    no_git_path: Path,
    only: tuple[str, ...],
) -> None:
    # A .git entry asks for git's listing; with no git on PATH the listing fails. The fixed
    # paths are still read, so no other rule reports anything (plan E23, E24).
    (demo_hub / ".git").mkdir()
    monkeypatch.setenv("PATH", str(no_git_path))

    lines = lines_of(run_doctor(demo_hub, *only), exit_code=1)

    # E35: E24's owner is the first rule by id reading the listing, E28's file sets included.
    owner = "features.tracker" if only else "attribution.ai"
    assert lines == [
        f"error {owner} .: could not list the files: git not found {LISTING_FIX}",
        ONE_ERROR,
    ]


MISSING_WEB = (
    "info brain.leak ../demo-web: repo demo-web is not checked out next to the hub;"
    " its repo checks are skipped Fix: clone the repo next to the hub"
)


@pytest.mark.parametrize("missing_as", ["absent", "file", "link-to-file"])
def test_reports_info_when_checkout_missing(
    demo_two_repo_hub: Path,
    run_doctor: DoctorRunner,
    demo_checkout: CheckoutFactory,
    *,
    missing_as: str,
) -> None:
    demo_checkout("demo-api")
    web = demo_two_repo_hub.parent / "demo-web"
    if missing_as == "file":
        web.write_bytes(b"not a checkout\n")
    elif missing_as == "link-to-file":
        (demo_two_repo_hub.parent / "web.txt").write_bytes(b"not a checkout\n")
        web.symlink_to("web.txt")

    lines = lines_of(run_doctor(demo_two_repo_hub), exit_code=0)

    assert lines == [MISSING_WEB, "0 errors, 0 warnings, 1 info"]


def test_reads_checkout_real_path_when_dir_is_link(
    demo_two_repo_hub: Path, run_doctor: DoctorRunner, demo_checkout: CheckoutFactory
) -> None:
    # ../<dir> is taken as its real path once (plan E18): a link to a checkout is a checkout.
    demo_checkout("demo-api")
    demo_checkout("web-clone")
    (demo_two_repo_hub.parent / "demo-web").symlink_to("web-clone")

    lines = lines_of(run_doctor(demo_two_repo_hub), exit_code=0)

    assert lines == [CLEAN]


def test_reads_no_repo_when_no_repo_rule_selected(
    demo_two_repo_hub: Path,
    run_doctor: DoctorRunner,
    *,
    demo_checkout: CheckoutFactory,
    path_reads: list[PathRead],
    under: Under,
) -> None:
    workspace = demo_two_repo_hub.parent
    checkouts = [demo_checkout("demo-api"), demo_checkout("demo-web")]
    path_reads.clear()

    lines = lines_of(run_doctor(demo_two_repo_hub, "--only", "features.tracker"), exit_code=0)

    # Copied first: the filters' own real-path looks would be recorded too.
    recorded = list(path_reads)
    assert lines == [CLEAN]
    assert {path for checkout in checkouts for path in under(recorded, checkout)} == set()
    outside_hub = under(recorded, workspace) - under(recorded, demo_two_repo_hub)
    assert outside_hub <= {os.path.realpath(workspace)}
    # The recorder sees a checkout read when a repo rule runs.
    path_reads.clear()
    assert lines_of(run_doctor(demo_two_repo_hub, "--only", "links.dead"), exit_code=0) == [CLEAN]
    assert under(list(path_reads), checkouts[1]) != set()


def test_reports_error_when_checkout_cannot_be_listed(
    demo_two_repo_hub: Path, run_doctor: DoctorRunner, demo_checkout: CheckoutFactory
) -> None:
    # An empty .git folder asks for git's listing, and git finds no repository there (nor above
    # the test's folder): the checkout is skipped with one error, never silently (plan E36).
    demo_checkout("demo-api")
    (demo_two_repo_hub.parent / "demo-web" / ".git").mkdir(parents=True)

    lines = lines_of(run_doctor(demo_two_repo_hub), exit_code=1)

    assert lines == [
        "error brain.leak ../demo-web: could not list the files: git exited with 128:"
        " fatal: not a git repository (or any of the parent directories): .git"
        f" {LISTING_FIX}",
        ONE_ERROR,
    ]


BRAIN_LINE = "A synthetic brain line, long enough for brain.leak to compare it."


def test_checks_rest_of_checkout_when_one_file_unreadable(
    demo_two_repo_hub: Path,
    run_doctor: DoctorRunner,
    *,
    demo_checkout: CheckoutFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One file that cannot be read is no listing problem (plan E36): the other files are checked.
    (demo_two_repo_hub / "brain/note.md").write_text(f"# Note\n\n{BRAIN_LINE}\n", encoding="utf-8")
    api = demo_checkout("demo-api")
    (api / "LEAK.md").write_text(f"{BRAIN_LINE}\n", encoding="utf-8")
    (api / "unreadable.md").write_text(f"{BRAIN_LINE}\n", encoding="utf-8")
    demo_checkout("demo-web")
    monkeypatch.setattr(os, "open", refusing_name("unreadable.md", os.open))

    lines = lines_of(run_doctor(demo_two_repo_hub), exit_code=1)

    assert lines == [
        "error brain.leak ../demo-api/LEAK.md:1: line also in the brain at brain/note.md:3"
        " Fix: reword or remove the line here, or reword the brain note if it quotes this file",
        ONE_ERROR,
    ]


def test_reports_error_when_checkout_cannot_be_looked_at(
    demo_two_repo_hub: Path,
    run_doctor: DoctorRunner,
    monkeypatch: pytest.MonkeyPatch,
    *,
    demo_checkout: CheckoutFactory,
) -> None:
    # A ../<dir> that cannot be looked at may be a checkout: E36's error, never Q-9's info.
    demo_checkout("demo-api")
    web = demo_two_repo_hub.parent / "demo-web"
    web.mkdir()
    (web / "README.md").write_bytes(b"# Web\n")
    monkeypatch.setattr(os, "lstat", refusing_name("demo-web", os.lstat))

    lines = lines_of(run_doctor(demo_two_repo_hub), exit_code=1)

    assert lines == [
        f"error brain.leak ../demo-web: could not list the files: {os.path.realpath(web)}:"
        f" Permission denied {LISTING_FIX}",
        ONE_ERROR,
    ]


type Workspace = Any

DERIVED_INFO = (
    "info config.identity: branch prefix `jane/` is derived from git config user.email"
    " (hub.local.json and hub.json set none)"
    " Fix: set project.branch_prefix in hub.local.json to choose another"
)
ONE_INFO = "0 errors, 0 warnings, 1 info"


def identity_reads(traced_git: Any) -> list[tuple[str, str]]:
    """``(cwd, arguments)`` of each git call of a run that reads a ``user.*`` config key."""
    return [
        (cwd, arguments)
        for cwd, arguments in traced_git.calls()
        if "config" in arguments and "user." in arguments
    ]


def email_read_in(folder: Path) -> list[tuple[str, str]]:
    """The one git call a derived prefix needs, run in ``folder``."""
    return [(os.path.realpath(folder), "config --get user.email")]


def hub_worktree_of(workspace: Workspace) -> Path:
    """Commit the workspace's hub and add a hub worktree of it, as a developer's task would."""
    hub = workspace.hub
    workspace.git(hub, "-c", "init.defaultBranch=main", "init", "-q")
    workspace.git(hub, "add", "-A")
    workspace.git(hub, "commit", "-q", "-m", "hub")
    worktree = hub / ".claude" / "worktrees" / "x"
    workspace.git(hub, "worktree", "add", "-q", "-b", "x", str(worktree))
    return worktree


class TestIdentity:
    def test_reports_derived_prefix_info_when_only_git_sets_email(
        self, demo_workspace: Workspace, run_doctor: DoctorRunner, traced_git: Any
    ) -> None:
        demo_workspace.drop_identity()
        demo_workspace.git_identity("Jane Roe", "jane@example.com")

        lines = lines_of(run_doctor(demo_workspace.hub), exit_code=0)

        assert lines == [DERIVED_INFO, ONE_INFO]
        # Git is asked for the email only: the prefix needs nothing else.
        assert identity_reads(traced_git) == email_read_in(demo_workspace.hub)

    def test_reports_no_identity_info_when_local_sets_prefix(
        self, demo_workspace: Workspace, run_doctor: DoctorRunner, traced_git: Any
    ) -> None:
        demo_workspace.drop_identity()
        demo_workspace.git_identity("Jane Roe", "jane@example.com")
        demo_workspace.write_local(json.dumps({"project": {"branch_prefix": "me/"}}))

        lines = lines_of(run_doctor(demo_workspace.hub), exit_code=0)

        assert lines == [CLEAN]
        assert identity_reads(traced_git) == []

    def test_reports_local_file_error_when_invalid(
        self, demo_workspace: Workspace, run_doctor: DoctorRunner
    ) -> None:
        demo_workspace.write_local(json.dumps({"project": {"colour": "blue"}}))

        lines = lines_of(run_doctor(demo_workspace.hub), exit_code=1)

        assert lines == [
            "error config.schema hub.local.json: project.colour: Extra inputs are not permitted"
            " Fix: fix hub.local.json (docs/design/developer-identity.md)",
            ONE_ERROR,
        ]

    def test_reports_local_file_error_when_hub_json_also_invalid(
        self, demo_workspace: Workspace, run_doctor: DoctorRunner
    ) -> None:
        path = demo_workspace.hub / "hub.json"
        document = json.loads(path.read_text())
        document["shade"] = 1
        path.write_text(json.dumps(document))
        demo_workspace.write_local("[]")

        lines = lines_of(run_doctor(demo_workspace.hub), exit_code=1)

        assert lines == [
            schema_line("shade: Extra inputs are not permitted"),
            "error config.schema hub.local.json: $: must be a JSON object"
            " Fix: fix hub.local.json (docs/design/developer-identity.md)",
            "2 errors, 0 warnings, 0 infos",
        ]

    def test_finds_same_findings_when_valid_local_file_added(
        self, demo_workspace: Workspace, run_doctor: DoctorRunner
    ) -> None:
        # The doctor judges the hub, not the developer: the same hub gives every developer the
        # same findings, whatever their local file sets.
        # `me/…` is a stale path to the hub, whose prefix is not `me/`, whatever the local one.
        (demo_workspace.hub / "AGENTS.md").write_bytes(
            b"# Agents\nRun `scripts/gone.py`.\nNot the branch `me/dem-1-x`.\n"
        )
        without = run_doctor(demo_workspace.hub)
        demo_workspace.write_local(
            json.dumps(
                {
                    "project": {
                        "branch_prefix": "me/",
                        "author_name": "Jane Roe",
                        "author_email": "jane.doe@example.com",
                    },
                    "tracker": {"transport": "mcp"},
                }
            )
        )

        with_local = run_doctor(demo_workspace.hub)

        assert lines_of(with_local, exit_code=1) == lines_of(without, exit_code=1)
        shown = lines_of(without, exit_code=1)
        refs = [line for line in shown if line.startswith("error instructions.refs AGENTS.md:")]
        assert [line.split(" (no such path)")[0] for line in refs] == [
            "error instructions.refs AGENTS.md:2: stale reference `scripts/gone.py`",
            "error instructions.refs AGENTS.md:3: stale reference `me/dem-1-x`",
        ]
        # The edited AGENTS.md is also lock.drift's.
        assert shown[-1] == "3 errors, 0 warnings, 0 infos"

    def test_refuses_identity_severity_when_hub_json_retunes_it(
        self, demo_workspace: Workspace, run_doctor: DoctorRunner
    ) -> None:
        # A retuned info would make the exit code depend on the developer's git email.
        demo_workspace.drop_identity()
        demo_workspace.git_identity("Jane Roe", "jane@example.com")
        path = demo_workspace.hub / "hub.json"
        document = json.loads(path.read_text())
        document["doctor"] = {"rules": {"config.identity": {"severity": "error"}}}
        path.write_text(json.dumps(document))

        lines = lines_of(run_doctor(demo_workspace.hub), exit_code=1)

        assert lines == [
            schema_line(
                'doctor.rules["config.identity"].severity: config.identity is always an info,'
                " so every developer's run exits alike; remove severity"
            ),
            ONE_ERROR,
        ]

    def test_runs_no_git_config_when_identity_rule_disabled(
        self, demo_workspace: Workspace, run_doctor: DoctorRunner, traced_git: Any
    ) -> None:
        demo_workspace.drop_identity()
        demo_workspace.git_identity("Jane Roe", "jane@example.com")
        path = demo_workspace.hub / "hub.json"
        document = json.loads(path.read_text())
        document["doctor"] = {"rules": {"config.identity": {"enabled": False}}}
        path.write_text(json.dumps(document))

        lines = lines_of(run_doctor(demo_workspace.hub), exit_code=0)

        assert lines == [CLEAN]
        assert identity_reads(traced_git) == []

    def test_reports_main_checkout_local_file_when_run_from_hub_worktree(
        self, demo_workspace: Workspace, run_doctor: DoctorRunner
    ) -> None:
        hub_worktree = hub_worktree_of(demo_workspace)
        demo_workspace.write_local("[]")

        lines = lines_of(run_doctor(hub_worktree, "--only", "config.schema"), exit_code=1)

        assert lines == [
            "error config.schema hub.local.json: $: must be a JSON object"
            " Fix: fix hub.local.json (docs/design/developer-identity.md)",
            ONE_ERROR,
        ]

    def test_reads_git_email_in_main_checkout_when_run_from_hub_worktree(
        self, demo_workspace: Workspace, run_doctor: DoctorRunner, traced_git: Any
    ) -> None:
        demo_workspace.drop_identity()
        hub_worktree = hub_worktree_of(demo_workspace)
        demo_workspace.git_identity("Jane Roe", "jane@example.com")

        lines = lines_of(run_doctor(hub_worktree, "--only", "config.identity"), exit_code=0)

        assert lines == [DERIVED_INFO, ONE_INFO]
        assert identity_reads(traced_git) == email_read_in(demo_workspace.hub)

    def test_runs_no_git_config_when_only_config_schema_selected(
        self, demo_workspace: Workspace, run_doctor: DoctorRunner, traced_git: Any
    ) -> None:
        demo_workspace.drop_identity()
        demo_workspace.git_identity("Jane Roe", "jane@example.com")

        lines = lines_of(run_doctor(demo_workspace.hub, "--only", "config.schema"), exit_code=0)

        assert lines == [CLEAN]
        assert identity_reads(traced_git) == []

    def test_finds_nothing_in_agents_when_team_hub_checked(
        self, tmp_path: Path, demo_document: dict[str, Any], run_doctor: DoctorRunner
    ) -> None:
        # AC-65.8: the team AGENTS.md names `hub.local.json`, which no developer commits (E12),
        # and the developer's git identity, which is no AI attribution.
        for key in ("branch_prefix", "author_name", "author_email"):
            del demo_document["project"][key]
        demo_document["modules"] = {"marketplace": {}}
        config = tmp_path / "hub.json"
        config.write_bytes(dump_json(demo_document))
        root = tmp_path / "hub"
        created = CliRunner().invoke(app, ["init", "--config", str(config), "--dir", str(root)])
        assert created.exit_code == 0, created.stderr
        agents = (root / "AGENTS.md").read_text(encoding="utf-8")
        assert "`hub.local.json`" in agents
        assert not (root / "hub.local.json").exists()

        lines = lines_of(run_doctor(root), exit_code=0)

        assert lines == [CLEAN]
