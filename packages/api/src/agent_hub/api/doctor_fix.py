"""Fix a registered hub's auto-fixable doctor findings: this server's ``hub doctor --fix``.

The same command as in a terminal, run in the hub with the running release: it rewrites what
needs no person (today every ``brain.leak``, on the brain side only, never a repo), then checks
the hub again. Nothing is committed: the changed files stay in the hub's checkout for the owner
to review in a hub PR, as after a platform sync. The answer holds the fixer's lines (one per
file it wrote), the files that changed and the findings left after the new check.
"""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict

from agent_hub.api.platform_sync import Runner, _changed_files, _lines, _run
from agent_hub.api.run_launcher import own_hub_program

# ``hub doctor``: 0 no error left, 1 errors left (the fix still ran); anything else failed.
_CHECKED: Final = frozenset({0, 1})


class DoctorFixRequest(BaseModel):
    """The empty JSON body of the fix: a cross-site form cannot send one (S7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class DoctorFixResult(BaseModel):
    """What one fix did, and what the check after it found."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hub_id: str
    ok: bool
    exit_code: int
    output: tuple[str, ...]
    changed_files: tuple[str, ...]
    errors_left: int | None
    warnings_left: int | None


def _totals(stdout: str) -> tuple[int | None, int | None]:
    try:
        totals = json.loads(stdout).get("totals", {})
        return int(totals["errors"]), int(totals["warnings"])
    except ValueError, TypeError, KeyError, AttributeError:
        return None, None


def fix_hub(
    hub_id: str, hub_path: str, *, run: Runner = _run, program: Sequence[str] | None = None
) -> DoctorFixResult:
    """Run ``hub doctor --fix --json`` in the hub at ``hub_path``."""
    hub = Path(hub_path)
    dirty_before = set(_changed_files(hub, run))
    argv = (*(program or own_hub_program()), "doctor", "--fix", "--json")
    try:
        done = run(argv, hub)
        exit_code, stdout, output = done.returncode, done.stdout, _lines(done.stderr)
    except subprocess.TimeoutExpired:
        exit_code, stdout, output = 2, "", ("hub doctor --fix did not finish in time",)
    except OSError as error:
        exit_code, stdout = 2, ""
        output = (f"hub doctor --fix could not start: {error.strerror or error}",)
    errors, warnings = _totals(stdout)
    return DoctorFixResult(
        hub_id=hub_id,
        ok=exit_code in _CHECKED,
        exit_code=exit_code,
        output=output,
        # Files already changed before the fix are the owner's, not this fix's.
        changed_files=tuple(p for p in _changed_files(hub, run) if p not in dirty_before),
        errors_left=errors,
        warnings_left=warnings,
    )
