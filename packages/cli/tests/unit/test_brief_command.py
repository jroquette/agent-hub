import re
from importlib.resources import files

from agent_hub.cli import brief_command


def test_pins_git_timeout_when_module_loaded() -> None:
    assert brief_command.BRIEF_GIT_TIMEOUT == 6


def test_pins_gh_timeout_when_module_loaded() -> None:
    assert brief_command.BRIEF_GH_TIMEOUT == 6


def test_pins_gh_workers_when_module_loaded() -> None:
    assert brief_command.MAX_GH_WORKERS == 8


def test_pins_git_phase_budget_when_module_loaded() -> None:
    assert brief_command.GIT_PHASE_BUDGET == 3


def test_pins_gh_phase_budget_when_module_loaded() -> None:
    assert brief_command.GH_PHASE_BUDGET == 5


def test_fits_hook_deadline_when_budgets_added() -> None:
    # The SessionStart hook gives its resolve step and hub brief one deadline; the resolve step
    # keeps at least a second of it.
    template = (
        files("agent_hub.generator") / "templates/plugin/hub-workflow/hooks/session_start.py.tmpl"
    ).read_text(encoding="utf-8")
    found = re.search(r"^BRIEF_TIMEOUT = ([0-9]+)", template, re.M)
    assert found is not None
    hook_deadline = int(found.group(1))

    budgets = brief_command.GIT_PHASE_BUDGET + brief_command.GH_PHASE_BUDGET
    assert budgets < hook_deadline - 1
