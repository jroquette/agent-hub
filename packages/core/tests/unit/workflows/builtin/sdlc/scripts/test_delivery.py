"""The sdlc pack's ``delivery.py`` (AGH-404), in process: the report, this run's hub files."""

import importlib.util
import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/sdlc/scripts/delivery.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.sdlc.scripts.delivery"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


SUPERSEDED = "change request 1 approved but superseded by plan v2: not applied"
REPORT = {
    "delivery": "failed",
    "stage": "pr_open",
    "reason": "no PR was opened for the commits",
    "question": "",
    "pr": "",
    "summary": "",
}


def git(folder: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=folder,
        check=True,
        capture_output=True,
    )


def a_hub(tmp_path: Path) -> Path:
    feature = tmp_path / "brain/features/demo-flow"
    (feature / "tickets").mkdir(parents=True)
    (feature / "plan.md").write_text("# Plan\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    files_ = {
        "plan.md": "# Plan\n\n## Amendments\n",
        "tickets/DEM-1/brief.md": "x\n",
        "tickets/DEM-2/brief.md": "another ticket's\n",
        "change-requests/1.md": "---\nrun_id: run-1\n---\n",
        "change-requests/1.decision.md": "---\ndecision: approved\n---\n",
        "change-requests/2.md": "---\nrun_id: run-2\n---\n",
        "change-requests/3.md": "---\nrun_id: run-0\n---\n",
        "change-requests/3.decision.md": "---\ndecision: declined\n---\n",
        "change-requests/4.decision.md": "---\ndecision: declined\n---\n",
        "evals/dem-1.json": "{}\n",
        "evals/dem-2.json": "{}\n",
        "notes.md": "not a record of this run\n",
    }
    for name, text in files_.items():
        (feature / name).parent.mkdir(parents=True, exist_ok=True)
        (feature / name).write_text(text)
    return tmp_path


def args(*extra: str) -> list[str]:
    return [
        *("--report", json.dumps(REPORT), "--feature", "demo-flow"),
        *("--brief", "brain/features/demo-flow/tickets/DEM-1/brief.md"),
        *extra,
    ]


def test_names_only_this_runs_hub_files_and_a_no_ship_when_the_run_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(a_hub(tmp_path))
    monkeypatch.setenv("AGENT_HUB_RUN_ID", "run-1")
    given = ("--eval", "NO-SHIP", "--eval-delivery", "dem-1", "--request", "3")

    assert load().main(args(*given, "--superseded", SUPERSEDED)) == 0

    assert json.loads(capsys.readouterr().out) == REPORT | {
        "stage": "evaluating",
        "reason": "the ticket eval is NO-SHIP: no PR was opened",
        "superseded": SUPERSEDED,
        "hub_files": [
            "change-requests/1.decision.md",
            "change-requests/1.md",
            "change-requests/3.decision.md",
            "change-requests/3.md",
            "evals/dem-1.json",
            "plan.md",
            "tickets/DEM-1/brief.md",
        ],
    }


def test_keeps_the_report_and_names_no_request_when_the_run_has_no_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(a_hub(tmp_path))
    monkeypatch.delenv("AGENT_HUB_RUN_ID", raising=False)

    assert load().main(args()) == 0

    output = json.loads(capsys.readouterr().out)
    assert (output["reason"], output["superseded"]) == (REPORT["reason"], "")
    assert output["hub_files"] == ["plan.md", "tickets/DEM-1/brief.md"]


@pytest.mark.parametrize(
    "argv",
    [
        ["--report", "not json", "--feature", "demo-flow", "--brief", "b"],
        ["--report", "{}", "--feature", "../up", "--brief", "b"],
    ],
)
def test_exits_two_when_the_report_or_the_feature_is_unusable(argv: list[str]) -> None:
    assert load().main(argv) == 2


def test_exits_two_when_git_cannot_read_the_hub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # not a git repository

    assert load().main(args()) == 2
