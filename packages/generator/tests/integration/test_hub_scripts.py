"""The rendered transcript and retro scripts in a rendered hub (AC-4.20, AC-4.21).

The first five tests are the counterparts of the hub's ``tests/test_mine_transcripts.py`` and
``tests/test_recall_transcripts.py``: their calls run in a child on ``hook_python`` with the
rendered ``scripts/`` first on ``sys.path``, and the child returns each value's ``repr``, so a
tuple stays a tuple. The others run the scripts as a hub user does, through ``make`` or
``python3 scripts/…``, in an environment from scratch: ``python3`` is ``hook_python``, ``gh`` a
fake that logs its arguments and prints ``[]``, and ``HOME`` holds synthetic transcripts.
"""

import ast
import datetime
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document

SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
TIMEOUT = 60
READER = "plugin/hub-workflow/hooks/stdlib_reader.py"
SCRIPTS = {
    "mine_transcripts": ("--days", "7"),
    "recall_transcripts": ("ledger",),
    "retro_metrics": ("--days", "14"),
}
RETRO_KEYS = {"window", "prs", "agent_runs", "ci", "memory"}
GITHUB_REPOS = ["acme/demo-api", "acme/demo-hub"]
MATCH = "the synthetic ledger holds 42 rows"
# argv: expressions (JSON), then any strings the expressions read as ``args``; prints each
# expression's ``repr``. ``mt`` and ``rt`` are the rendered scripts.
EVALUATE = """
import json
from pathlib import Path
import mine_transcripts as mt
import recall_transcripts as rt
expressions, args = json.loads(sys.argv[1]), sys.argv[2:]
scope = dict(mt=mt, rt=rt, Path=Path, args=args)
print(json.dumps([repr(eval(expression, scope)) for expression in expressions]))
"""
# Which reader the scripts loaded, how, and what it read from hub.json.
LOADED = """
import json
import mine_transcripts as mt
import retro_metrics as rm
reader = sys.modules["hub_stdlib_reader"]
print(json.dumps({
    "file": reader.__file__,
    "shared": reader is mt.reader and reader is rm.reader,
    "imported": sorted({"stdlib_reader", "hubconfig"} & set(sys.modules)),
    "name": rm.CFG.project.name,
    "deny_paths": list(rm.CFG.guard.deny_paths),
    "gh_repos": rm.GH_REPOS,
}))
"""
FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >> "{log}"
echo '[]'
"""

type Evaluate = Callable[..., list[Any]]
type Run = Callable[..., subprocess.CompletedProcess[str]]


def record(kind: str, content: Any) -> str:
    return json.dumps({"type": kind, "message": {"content": content}})


def bash_failures() -> list[str]:
    """The hub mine test's three failing ``pnpm test`` calls, one normalized error."""
    lines = []
    for i in range(3):
        use = {"type": "tool_use", "id": f"b{i}", "name": "Bash", "input": {"command": "pnpm test"}}
        error = f"Exit code 1\nError: cannot find module /Users/x/p{i}.ts line {i}"
        result = {"type": "tool_result", "tool_use_id": f"b{i}", "is_error": True, "content": error}
        lines += [record("assistant", [use]), record("user", [result])]
    return lines


def scripts_document() -> dict[str, Any]:
    """The builder's demo hub without modules: the Makefile then includes no ``mk/*.mk``."""
    document = a_hub_document()
    document["modules"] = {}
    return document


@pytest.fixture
def scripts_hub(
    rendered_hub: Callable[[HubConfig], Path], hook_python: str, tmp_path: Path
) -> Path:
    """A rendered hub with its ``hub.json``; ``tmp_path/bin`` holds ``python3`` (``hook_python``)
    and the fake ``gh``; ``tmp_path/home`` holds a transcript of this workspace and one of
    another."""
    document = scripts_document()
    hub = rendered_hub(HubConfig.model_validate(document)).resolve()
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, text in {
        "python3": f'#!/bin/sh\nexec "{hook_python}" "$@"\n',
        "gh": FAKE_GH.format(log=tmp_path / "gh.log"),
    }.items():
        (bin_dir / name).write_text(text, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    projects = tmp_path / "home" / ".claude" / "projects"
    key = re.sub(r"[^A-Za-z0-9]", "-", str(hub.parent))
    lines = [*bash_failures(), record("user", MATCH)]
    for folder in (key + "-demo-hub", "-elsewhere"):
        (projects / folder).mkdir(parents=True)
        (projects / folder / "abcdef12.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return hub


@pytest.fixture
def run(scripts_hub: Path, tmp_path: Path) -> Run:
    """Run ``argv`` (``make`` or ``python3``, found on the case ``PATH``) in the hub."""

    def run_argv(
        argv: Sequence[str], *, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        path = os.pathsep.join([str(tmp_path / "bin"), *SYSTEM_PATH])
        executable = shutil.which(argv[0], path=path)
        assert executable is not None, f"{argv[0]} not found on {path}"
        case_env = {
            "PATH": path,
            "HOME": str(tmp_path / "home"),
            "PYTHONUTF8": "1",
            "GIT_CEILING_DIRECTORIES": str(tmp_path),
        }
        return subprocess.run(  # noqa: S603 - make or the python3 wrapper, fixed arguments
            [executable, *argv[1:]],
            cwd=scripts_hub,
            capture_output=True,
            text=True,
            check=False,
            env=case_env | dict(env or {}),
            timeout=TIMEOUT,
        )

    return run_argv


@pytest.fixture
def evaluate(
    rendered_hub: Callable[[HubConfig], Path],
    *,
    hook_python: str,
    run_python: Callable[..., Any],
    tmp_path: Path,
) -> Evaluate:
    """Evaluate expressions in one child with the rendered ``scripts/`` on ``sys.path``."""
    scripts = rendered_hub(HubConfig.model_validate(scripts_document())) / "scripts"
    elsewhere, home = tmp_path / "elsewhere", tmp_path / "home"
    elsewhere.mkdir()
    home.mkdir()  # the scripts read ~/.claude/projects at import: never the real one

    def run_child(expressions: Sequence[str], *args: str) -> list[Any]:
        argv = [json.dumps(list(expressions)), *args]
        found = run_python(
            hook_python, EVALUATE, path=scripts, args=argv, cwd=elsewhere, env={"HOME": str(home)}
        )
        return [ast.literal_eval(value) for value in found]

    return run_child


def mining_weeks(*days: datetime.date) -> set[str]:
    return {f"{day.isocalendar()[0]}-W{day.isocalendar()[1]:02d}.md" for day in days}


# The hub's MineTest and RecallTest


def test_groups_errors_blocks_and_costs_when_transcripts_mined(
    evaluate: Evaluate, tmp_path: Path
) -> None:
    lines = [
        *bash_failures(),
        record(
            "user",
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "z",
                    "is_error": True,
                    "content": "[hub-workflow guard] reading secret file .env is blocked",
                }
            ],
        ),
        record("user", "[hub-workflow stop-gate] Fix these before finishing"),
        json.dumps({"type": "cost-state", "totalCostUSD": 1.25}),
    ]
    transcript = tmp_path / "abcdef12.jsonl"
    transcript.write_text("\n".join(lines) + "\nnot json\n", encoding="utf-8")

    [mined, report] = evaluate(
        [
            "mt.mine([Path(args[0])], min_count=3)",
            "mt.render(mt.mine([Path(args[0])], min_count=3), 7)",
        ],
        str(transcript),
    )

    assert mined["recurring"] == [("Bash", "Error: cannot find module <path> line N", 3)]
    assert mined["bash_fail"] == [("pnpm", 3)]
    assert len(mined["blocks"]) == 1
    assert mined["stop_gate"] == 1
    assert mined["cost_total"] == 1.25
    assert "3× **Bash**" in report


def test_follows_workspace_when_transcript_dirs_listed(evaluate: Evaluate, tmp_path: Path) -> None:
    workspace = tmp_path / "work.space" / "acme"
    hub = workspace / "acme-hub"
    hub.mkdir(parents=True)
    document = {
        "project": {"name": "acme", "hub_repo": "a/acme-hub", "branch_prefix": "x/"},
        "tracker": {"kind": "linear", "team": "ACM"},
        "repos": [{"dir": "api", "github": "a/api"}],
    }
    (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")
    projects = tmp_path / "projects"
    worktree_hub = hub / ".claude" / "worktrees" / "t2"

    [key] = evaluate(["mt.project_key(Path(args[0]))"], str(workspace))
    for name in (key, f"{key}-acme-hub", f"{key}-api--claude-worktrees-t1", f"{key}other"):
        (projects / name).mkdir(parents=True)
    (projects / "-elsewhere").mkdir()
    found_hub, got, worktree_workspace = evaluate(
        [
            "str(mt.find_hub_json(Path(args[0])).parent)",
            "[p.name for p in mt.transcript_dirs(mt.find_hub_json(Path(args[0])).parent, "
            "Path(args[1]))]",
            "str(mt.workspace(Path(args[2])))",
        ],
        str(hub),
        str(projects),
        str(worktree_hub),
    )

    assert key.endswith("-work-space-acme")
    assert found_hub == str(hub)
    assert got == sorted([key, f"{key}-acme-hub", f"{key}-api--claude-worktrees-t1"])
    assert worktree_workspace == str(workspace)


def test_redacts_secrets_when_message_normalized(evaluate: Evaluate) -> None:
    assert evaluate(["mt.normalize('Exit code 2\\nfailed API_KEY=abc123 at 42')"]) == [
        "failed API_KEY=*** at N"
    ]


def test_finds_text_when_messages_and_tool_results_searched(
    evaluate: Evaluate, tmp_path: Path
) -> None:
    records = [
        {"type": "user", "message": {"content": "how many lines does .env.example have?"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "noise " * 500}]}},
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "content": "the .env.example file has 71 lines"}
                ]
            },
        },
        {"type": "system", "subtype": "x", "content": ".env.example 71 lines"},
    ]
    transcript = tmp_path / "abcdef1234.jsonl"
    text = "\n".join(json.dumps(item) for item in records) + "\n{broken\n"
    transcript.write_text(text, encoding="utf-8")

    [hits] = evaluate(
        ["rt.search(['.env.example', '71 lines'], False, 10, 120, [Path(args[0])])"],
        str(transcript),
    )

    assert len(hits) == 1
    assert "msg 2 [user]" in hits[0]
    assert "71 lines" in hits[0]
    assert len(hits[0]) < 250


def test_limits_matches_when_any_mode_used(evaluate: Evaluate, tmp_path: Path) -> None:
    records = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": f"alpha {i}"}]}}
        for i in range(5)
    ]
    transcript = tmp_path / "s.jsonl"
    transcript.write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")

    any_hits, all_hits = evaluate(
        [
            "rt.search(['alpha', 'zzz'], True, 3, 50, [Path(args[0])])",
            "rt.search(['alpha', 'zzz'], False, 3, 50, [Path(args[0])])",
        ],
        str(transcript),
    )

    assert len(any_hits) == 3
    assert all_hits == []


# AC-4.20: the scripts as a hub user runs them


def test_runs_mine_and_retro_when_make_targets_run(
    run: Run, scripts_hub: Path, tmp_path: Path
) -> None:
    today = datetime.date.today()
    run_log = f"{today.isoformat()}.jsonl"
    reported = {"event": "reported", "issue": "DEM-1", "total_cost_usd": 0.5}
    (scripts_hub / ".agent-runs").mkdir()
    (scripts_hub / ".agent-runs" / run_log).write_text(json.dumps(reported) + "\n")

    mine = run(["make", "mine", "DAYS=7"])
    retro = run(["make", "retro", "DAYS=14"])

    assert mine.returncode == 0, mine.stderr
    mining = scripts_hub / "brain" / "_inbox" / "mining"
    [written] = sorted(path.name for path in mining.iterdir())
    assert written in mining_weeks(today, datetime.date.today())
    report = (mining / written).read_text(encoding="utf-8")
    assert "Sessions: 1 " in report
    assert "- 3× **Bash**: `Error: cannot find module <path> line N`" in report
    assert mine.stdout == (
        "python3 scripts/mine_transcripts.py --days 7 --write\n"
        f"{report}\nwritten: brain/_inbox/mining/{written}\n"
    )
    assert retro.returncode == 0, retro.stderr
    echo, _, body = retro.stdout.partition("\n")
    assert echo == "python3 scripts/retro_metrics.py --days 14"
    metrics = json.loads(body)
    assert set(metrics) == RETRO_KEYS
    assert sorted(metrics["prs"]) == GITHUB_REPOS
    assert metrics["agent_runs"] == {"outcomes": {"pr_opened": 1}, "cost_per_issue": {"DEM-1": 0.5}}
    calls = (tmp_path / "gh.log").read_text(encoding="utf-8").splitlines()
    assert [call.split()[:4] for call in calls] == [
        [kind, "list", "-R", repo] for kind in ("pr", "run") for repo in GITHUB_REPOS
    ]


def test_prints_match_when_recall_run(run: Run) -> None:
    recall = run(["python3", "scripts/recall_transcripts.py", "ledger"])

    assert recall.returncode == 0, recall.stderr
    [line] = recall.stdout.splitlines()
    assert line.startswith("- ")
    assert line.endswith(f"/abcdef12 ({datetime.date.today():%Y-%m-%d}) msg 6 [user]: {MATCH}")
    assert "-elsewhere/" not in line


def test_loads_reader_by_path_when_script_runs(
    scripts_hub: Path, *, hook_python: str, run_python: Callable[..., Any], tmp_path: Path
) -> None:
    # hubconfig would reject this file (a field Project does not declare); the reader ignores it
    document = scripts_document()
    document["unknown"] = {"x": 1}
    document["project"]["extra"] = "x"
    document["guard"]["deny_paths"] = ["secrets/"]
    (scripts_hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")

    loaded = run_python(
        hook_python,
        LOADED,
        path=scripts_hub / "scripts",
        cwd=scripts_hub.parent,
        env={"HOME": str(tmp_path / "home")},
    )

    assert loaded == {
        "file": str(scripts_hub / READER),
        "shared": True,
        "imported": [],
        "name": "demo",
        "deny_paths": ["secrets/"],
        "gh_repos": GITHUB_REPOS,
    }


@pytest.mark.parametrize("script", sorted(SCRIPTS))
def test_raises_file_not_found_when_hub_config_names_missing_file(
    run: Run, *, script: str, tmp_path: Path, scripts_hub: Path
) -> None:
    missing = tmp_path / "missing" / "hub.json"

    completed = run(
        ["python3", f"scripts/{script}.py", *SCRIPTS[script]], env={"HUB_CONFIG": str(missing)}
    )

    assert completed.returncode == 1
    assert completed.stderr.splitlines()[-1] == (
        f"FileNotFoundError: [Errno 2] No such file or directory: '{missing}'"
    )
    assert not (tmp_path / "gh.log").exists()
    assert not (scripts_hub / "brain" / "_inbox" / "mining").exists()


def without_github(field: str) -> dict[str, Any]:
    document = scripts_document()
    if field == "hub_repo":
        del document["project"]["hub_repo"]
    else:
        del document["repos"][0]["github"]
    return document


@pytest.mark.parametrize("field", ["hub_repo", "github"])
def test_exits_without_gh_call_when_github_name_missing(
    run: Run, *, field: str, scripts_hub: Path, tmp_path: Path
) -> None:
    (scripts_hub / "hub.json").write_text(json.dumps(without_github(field)), encoding="utf-8")

    retro = run(["python3", "scripts/retro_metrics.py", "--days", "14"])

    assert retro.returncode == 1
    assert retro.stdout == ""
    assert retro.stderr == "hub.json: project.hub_repo and every repos[].github are required\n"
    assert not (tmp_path / "gh.log").exists()


@pytest.mark.parametrize("field", ["hub_repo", "github"])
def test_mines_and_recalls_when_github_name_missing(
    run: Run, *, field: str, scripts_hub: Path
) -> None:
    (scripts_hub / "hub.json").write_text(json.dumps(without_github(field)), encoding="utf-8")

    mine = run(["python3", "scripts/mine_transcripts.py", "--days", "7"])
    recall = run(["python3", "scripts/recall_transcripts.py", "ledger"])

    assert mine.returncode == 0, mine.stderr
    assert "- 3× **Bash**" in mine.stdout
    assert recall.returncode == 0, recall.stderr
    assert recall.stdout.count(MATCH) == 1
