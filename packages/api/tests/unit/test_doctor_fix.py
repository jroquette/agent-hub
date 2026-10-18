import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from agent_hub.api.doctor_fix import fix_hub

FIXED = "fixed brain/notes/draft.md: promoted draft, now a stub pointing at ../demo-api/a.md\n"


class FakeRunner:
    """Answers ``hub doctor --fix --json`` with ``exit_code``; ``git status`` lists ``notes.md``
    (the owner's own edit) before the fix, and the rewritten brain note beside it after."""

    def __init__(self, *, exit_code: int = 0, errors: int = 0) -> None:
        self.exit_code = exit_code
        self.errors = errors
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        self.calls.append(tuple(argv))
        if argv[0] == "hub":
            totals = {"errors": self.errors, "warnings": 6, "infos": 0}
            stdout = json.dumps({"findings": [], "totals": totals})
            return subprocess.CompletedProcess(argv, self.exit_code, stdout, FIXED)
        fixed = any(call[0] == "hub" for call in self.calls)
        status = " M notes.md\n" + (" M brain/notes/draft.md\n" if fixed else "")
        return subprocess.CompletedProcess(argv, 0, status, "")


def test_fix_hub_runs_doctor_fix_and_lists_what_changed(tmp_path: Path) -> None:
    runner = FakeRunner()

    result = fix_hub("h1", str(tmp_path), run=runner, program=("hub",))

    assert ("hub", "doctor", "--fix", "--json") in runner.calls
    assert result.ok
    assert result.output == (FIXED.strip(),)
    assert result.changed_files == ("brain/notes/draft.md",)
    assert (result.errors_left, result.warnings_left) == (0, 6)


def test_fix_hub_is_ok_when_errors_are_left(tmp_path: Path) -> None:
    result = fix_hub("h1", str(tmp_path), run=FakeRunner(exit_code=1, errors=2), program=("hub",))

    assert result.ok
    assert result.errors_left == 2


def test_fix_hub_fails_when_doctor_cannot_run(tmp_path: Path) -> None:
    result = fix_hub("h1", str(tmp_path), run=FakeRunner(exit_code=2), program=("hub",))

    assert not result.ok
    assert result.exit_code == 2
