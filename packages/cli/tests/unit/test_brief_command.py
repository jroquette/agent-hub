import re
from importlib.resources import files

from agent_hub.cli import brief_command


def test_pins_brief_deadline_when_module_loaded() -> None:
    assert brief_command.BRIEF_DEADLINE == 2


def test_pins_workers_when_module_loaded() -> None:
    assert brief_command.MAX_WORKERS == 8


def test_fits_hook_deadline_when_budgets_added() -> None:
    # The SessionStart refresh gives its resolve step and hub brief --write-cache one deadline;
    # the resolve step keeps at least a second of it.
    template = (
        files("agent_hub.generator") / "templates/plugin/hub-workflow/hooks/session_start.py.tmpl"
    ).read_text(encoding="utf-8")
    found = re.search(r"^REFRESH_TIMEOUT = ([0-9]+)", template, re.M)
    assert found is not None
    hook_deadline = int(found.group(1))

    deadline = brief_command.BRIEF_DEADLINE
    assert deadline < hook_deadline - 1
