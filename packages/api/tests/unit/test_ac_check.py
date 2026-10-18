"""``AcCheckRunner``: runs the command features.json records for an AC, in its repo's checkout."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from agent_hub.api.ac_check import AcCheckError, AcCheckRunner
from agent_hub.core.readmodels.read_ports import HubReadModels


def _ac(ac_id: str, command: str | None, *, manual: bool = False, repo: str | None = "app") -> Any:
    return SimpleNamespace(id=ac_id, command=command, manual=manual, repo=repo)


def _models(tmp_path: Path, *acs: Any) -> HubReadModels:
    (tmp_path / "hub").mkdir()
    (tmp_path / "app").mkdir()
    repo = SimpleNamespace(name="app", dir="app")
    return cast(
        "HubReadModels",
        SimpleNamespace(
            get_feature=lambda _p, _s: SimpleNamespace(ac_rows=acs),
            project_repos=lambda _p: SimpleNamespace(items=(repo,)),
            get_project=lambda _p: SimpleNamespace(hub_path=str(tmp_path / "hub")),
        ),
    )


def test_a_passing_check_answers_exit_zero_and_its_output_from_the_repo(tmp_path: Path) -> None:
    runner = AcCheckRunner(_models(tmp_path, _ac("AC-1", "pwd && echo ok")))

    run = runner.run("p", "f", "AC-1")

    assert run.passed
    assert run.exit_code == 0
    assert run.repo == "app"
    assert str(tmp_path / "app") in run.output
    assert "ok" in run.output


def test_a_failing_check_answers_its_exit_code_and_stderr(tmp_path: Path) -> None:
    runner = AcCheckRunner(_models(tmp_path, _ac("AC-1", "echo boom >&2; exit 3")))

    run = runner.run("p", "f", "AC-1")

    assert not run.passed
    assert run.exit_code == 3
    assert "boom" in run.output


def test_a_check_past_the_timeout_is_killed(tmp_path: Path) -> None:
    runner = AcCheckRunner(_models(tmp_path, _ac("AC-1", "sleep 5")), timeout=0.2)

    run = runner.run("p", "f", "AC-1")

    assert run.timed_out
    assert run.exit_code is None
    assert not run.passed


@pytest.mark.parametrize(
    ("ac", "status"),
    [
        (_ac("AC-1", "true", manual=True), 409),
        (_ac("AC-1", None), 409),
        (_ac("AC-1", "true", repo="other"), 409),
        (_ac("AC-9", "true"), 404),
    ],
)
def test_an_ac_that_cannot_run_is_refused(tmp_path: Path, ac: Any, status: int) -> None:
    runner = AcCheckRunner(_models(tmp_path, ac))

    with pytest.raises(AcCheckError) as raised:
        runner.run("p", "f", "AC-1")

    assert raised.value.status == status
