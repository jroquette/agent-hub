"""Workflow fixtures (docs/design/workflow-schema.md § Dry run and fixtures, AC-213.11).

``parse_fixture`` takes the mapping a loader read (``generator`` reads a pack's
``fixtures/*.yaml``) and returns the frozen model, or raises ``WorkflowLoadError`` naming each key
path. ``run_fixture`` dry-runs the plan with the fixture's ``inputs`` and ``stubs``, then checks
``expect`` (``status``, ``outcome``), and ``failed`` and ``reached`` as exact sets. A stub for a
node the workflow lacks, a reached node with no stub, a run the engine refuses and each mismatch
are problems; a stub never used is only a warning (a skipped branch is legitimate).
"""

import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Annotated, Final

from pydantic import Discriminator, Field, JsonValue, StrictStr, Tag, ValidationError

# Private helpers of document.py, kept unrenamed while their module is in other open PRs.
from agent_hub.core.workflows.document import (
    WorkflowLoadError,
    WorkflowProblem,
    _document_loc,
    _message,
)
from agent_hub.core.workflows.dry_run import PLACEHOLDER_TEXT, Stub, dry_run, skeleton_stub
from agent_hub.core.workflows.engine import WorkflowEngineError
from agent_hub.core.workflows.nodes import (
    READ_ONLY,
    Text,
    WorkflowObject,
    empty,
)
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.ports import OutputValidator, ReportStatus
from agent_hub.core.workflows.substitution import echo

_INPUT_PLACEHOLDERS: Final[Mapping[str, JsonValue]] = {
    "string": PLACEHOLDER_TEXT,
    "integer": 0,
    "number": 0,
    "boolean": False,
}


def _stubs_kind(value: object) -> str:
    return "<list>" if isinstance(value, list) else "<one>"


# One member checked, chosen by the value's kind; the tags are dropped from error paths.
FixtureStubs = Annotated[
    Annotated[Stub, Tag("<one>")] | Annotated[tuple[Stub, ...], Tag("<list>")],
    Discriminator(_stubs_kind),
]


class Expect(WorkflowObject):
    status: ReportStatus
    outcome: JsonValue = None


class Fixture(WorkflowObject):
    """One fixture: the workflow it runs, its inputs and stubs, and what the run must show."""

    workflow: Text
    inputs: Annotated[Mapping[StrictStr, JsonValue], *READ_ONLY] = Field(default_factory=empty)
    stubs: Annotated[Mapping[StrictStr, FixtureStubs], *READ_ONLY] = Field(default_factory=empty)
    expect: Expect
    failed: tuple[StrictStr, ...] = ()
    reached: tuple[StrictStr, ...]


@dataclass(frozen=True)
class FixtureResult:
    """What a fixture found: ``problems`` fail it, ``warnings`` do not."""

    problems: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.problems


def parse_fixture(content: object) -> Fixture:
    """The fixture ``content`` holds; raises ``WorkflowLoadError`` naming every problem."""
    try:
        return Fixture.model_validate(content)
    except ValidationError as error:
        problems = []
        for detail in error.errors(include_url=False, include_input=False):
            loc = [s for s in detail["loc"] if not (isinstance(s, str) and s.startswith("<"))]
            problems.append(
                WorkflowProblem(
                    _document_loc(loc, content), _message(detail["type"], detail["msg"])
                )
            )
        raise WorkflowLoadError(problems) from None


def run_fixture(plan: WorkflowPlan, fixture: Fixture, *, outputs: OutputValidator) -> FixtureResult:
    """Dry-run ``plan`` as ``fixture`` says and compare the run with its expectations."""
    name = plan.document.name
    if fixture.workflow != name:
        return FixtureResult(
            (f"workflow: the fixture is for {echo(fixture.workflow)}, not {echo(name)}",)
        )
    ids = {node.id for node in plan.document.nodes}
    if unknown := [node for node in fixture.stubs if node not in ids]:
        return FixtureResult(tuple(f"stubs: no node has the id {echo(node)}" for node in unknown))
    try:
        report = dry_run(plan, fixture.inputs, fixture.stubs, outputs=outputs)
    except WorkflowEngineError as error:
        return FixtureResult((f"the run did not start: {error}",))
    problems = [f"no stub for the reached node {echo(node)}" for node in report.missing]
    if report.run.status != fixture.expect.status:
        problems.append(f"status: expected {fixture.expect.status}, got {report.run.status}")
    if _json(report.outcome) != _json(fixture.expect.outcome):
        problems.append(
            f"outcome: expected {_json(fixture.expect.outcome)}, got {_json(report.outcome)}"
        )
    problems.extend(_set_problem("failed", fixture.failed, report.failed))
    problems.extend(_set_problem("reached", fixture.reached, report.reached))
    warnings = tuple(f"the stub of {echo(node)} was never used" for node in report.unused)
    return FixtureResult(tuple(problems), warnings)


def skeleton_fixture(plan: WorkflowPlan, *, outputs: OutputValidator) -> dict[str, JsonValue]:
    """A fixture that passes: a placeholder per required input, a ``skeleton_stub`` per
    node but halts, and the expectations its own dry run gives."""
    document = plan.document
    inputs: dict[str, JsonValue] = {
        name: _INPUT_PLACEHOLDERS[spec.type]
        for name, spec in document.inputs.items()
        if spec.required
    }
    stubs: dict[str, JsonValue] = {
        node.id: skeleton_stub(node) for node in document.nodes if node.type != "halt"
    }
    parsed = {node: Stub.model_validate(stub) for node, stub in stubs.items()}
    report = dry_run(plan, inputs, parsed, outputs=outputs)
    return {
        "workflow": document.name,
        "inputs": inputs,
        "stubs": stubs,
        "expect": {"status": report.run.status, "outcome": report.outcome},
        "failed": list(report.failed),
        "reached": list(report.reached),
    }


def _set_problem(key: str, expected: Collection[str], actual: Collection[str]) -> list[str]:
    if set(expected) == set(actual):
        return []
    return [f"{key}: expected {_json(sorted(set(expected)))}, got {_json(sorted(set(actual)))}"]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)
