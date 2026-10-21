"""A scenario run's findings as texts for others: a tracker issue draft and a brain inbox note
(docs/design/scenarios.md § Investigation; AC-350.27).

The findings come from the run record, folded by ``run_record``; each is named by its id
(``f<n>``, across the run). Both texts name the scenario, the run, the step, the environment, the
finding's text and evidence, and where its record is: the scenario run's page in hub web and its
``records.jsonl``. They hold names only, never a credential value: the finding's texts were
redacted when proposed, and every text is redacted again here (``redact_shapes``).

The inbox note is ``brain/_inbox/<date>-scenario-<name>-<finding-id>.md`` with frontmatter
``provenance: agent-from-external``, because its evidence comes from the system under test. The
names it is built from (scenario, run, finding id) are checked first: one that could leave the
folder or break a line raises ``FindingsError``.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Final

from agent_hub.core.errors import AgentHubError
from agent_hub.core.scenarios.run_record import FindingView, ScenarioRunView
from agent_hub.core.secret_shapes import redact_shapes

PROVENANCE: Final = "agent-from-external"
NOTE_TYPE: Final = "scenario-finding"
# Linear's title limit is 255 characters; a longer title is cut, with an ellipsis.
MAX_TITLE_CHARS: Final = 200
# A scenario name (a kebab id) and a run id, as their writers check them; a finding id ``f<n>``.
_SCENARIO: Final = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_RUN: Final = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
_FINDING: Final = re.compile(r"f[1-9][0-9]{0,5}")
_NO_TEXT: Final = "(no description was recorded)"
_NO_EVIDENCE: Final = "none recorded"


class FindingsError(AgentHubError):
    """The run record names a scenario, run or finding id no text can be built from."""


@dataclass(frozen=True, kw_only=True, slots=True)
class IssueDraft:
    """A tracker issue's title (one line) and Markdown description."""

    title: str
    description: str


@dataclass(frozen=True, kw_only=True, slots=True)
class InboxNote:
    """A brain inbox note: its file name in ``brain/_inbox/`` and its text."""

    name: str
    text: str


@dataclass(frozen=True, kw_only=True, slots=True)
class _Names:
    scenario: str
    run: str
    environment: str
    finding: str


def finding_of(view: ScenarioRunView, finding_id: str) -> FindingView | None:
    """The run's finding with the id ``finding_id``, else None."""
    return next((item for item in view.findings if item.finding_id == finding_id), None)


def screen_path(scenario: str, run: str) -> str:
    """The scenario run's page in hub web."""
    return f"/scenarios/{scenario}/runs/{run}"


def issue_draft(view: ScenarioRunView, finding: FindingView, *, record: str) -> IssueDraft:
    """The issue a person may create for ``finding``; ``record`` is the record file's path."""
    names = _names(view, finding)
    title = _one_line(f"Scenario {names.scenario}: {finding.title}")
    if len(title) > MAX_TITLE_CHARS:
        title = title[: MAX_TITLE_CHARS - 1] + "…"
    return IssueDraft(title=title, description=_body(names, finding, record=record))


def inbox_note(view: ScenarioRunView, finding: FindingView, *, record: str, day: date) -> InboxNote:
    """The brain inbox note for ``finding``, dated ``day``."""
    names = _names(view, finding)
    front = (
        "---",
        f"type: {NOTE_TYPE}",
        "repos: []",
        "status: proposed",
        f"last_verified: {day.isoformat()}",
        f"sources: [scenario run {names.run}, finding {names.finding}]",
        f"provenance: {PROVENANCE}",
        "---",
    )
    heading = f"## {_one_line(finding.title) or names.finding}"
    text = "\n".join((*front, heading, "", _body(names, finding, record=record)))
    name = f"{day.isoformat()}-scenario-{names.scenario}-{names.finding}.md"
    return InboxNote(name=name, text=text)


def _names(view: ScenarioRunView, finding: FindingView) -> _Names:
    """The names the texts are built from, each checked; else ``FindingsError``."""
    environment = _one_line(view.environment or "") or "unknown"
    return _Names(
        scenario=_checked("scenario", view.scenario, _SCENARIO),
        run=_checked("run", view.run, _RUN),
        environment=environment,
        finding=_checked("finding id", finding.finding_id, _FINDING),
    )


def _checked(noun: str, value: str | None, pattern: re.Pattern[str]) -> str:
    if value is None or not pattern.fullmatch(value):
        msg = f"the run record names no usable {noun}"
        raise FindingsError(msg)
    return value


def _body(names: _Names, finding: FindingView, *, record: str) -> str:
    where = (
        f"The scenario {names.scenario} found this in run {names.run}, at step"
        f" {_one_line(finding.step)}, in environment {names.environment}."
    )
    text = redact_shapes(finding.text).strip() or _NO_TEXT
    evidence = _one_line(finding.evidence) or _NO_EVIDENCE
    link = (
        f"Record: {screen_path(names.scenario, names.run)} in hub web, or the file"
        f" {_one_line(record)} in the hub (finding {names.finding})."
    )
    return "\n".join((where, "", text, "", f"Evidence: {evidence}", "", link)) + "\n"


def _one_line(text: str) -> str:
    """``text`` redacted, on one line: every run of whitespace is one space."""
    return " ".join(redact_shapes(text).split())
