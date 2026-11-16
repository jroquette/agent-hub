"""The rendered hub's text that spares the owner a nudge (fewer-owner-nudges).

When the owner drops the direction a session was following (AC-39, AC-40), ``/handoff`` holds the
procedure in one ``**Dropped direction**`` paragraph after its three numbered items: stop, ask
"Why?" once, file the answer with ``/learn`` (``provenance: human``) and run the three steps; with
no answer, still hand off and record "no reason given". The ticket keeps its status (or moves to
the state the owner names, after one confirmation) and gets one comment on what was done and
dropped; an open PR is left to the owner. The hub's ``AGENTS.md`` points to it in one "Brain
rules" line, since the owner drops a direction outside any skill. Phrases are checked on the demo
render; the two-team and conventions renders check that no project value reaches the new text,
which adds no ``@@{…}`` placeholder.

The scope tests (AGH-813, AC-33 to AC-35): ``/change``, ``/refactor`` and ``/upgrade`` show an
in-scope and an out-of-scope list with their first plan, post both on the tracker issue (not in the
PR body), and before the PR remove or ask about each changed file outside the in-scope list. The
upgrade workflow's branch belongs to the run, so at its ``publish`` gate the session only asks the
owner. The same phrases hold in the three skills; each step is sliced by its number or its bold
name.

The secret echo tests (AGH-814, AC-37): cross-repo rule 4 says a secret, including one a command's
output printed, is never repeated in a reply, a commit, a PR, a tracker comment or a brain note.
The line is generic: it adds no placeholder to the template. Checked on the demo, two-team and
conventions renders.

The follow-up loop tests (LOOP-2, AGH-825, ADR 0063; AC-2 to AC-7, AC-41): ``/deliver`` follows
its open PR on its own until the owner merges it. Step 2's **CI red** bullet fixes a failure that is
the PR's and re-runs once, then reports and stops, one that is not; step 4 tells the owner once that
the PR is ready to merge; step 5 never asks whether they merged. The ``**Follow-up loop**`` block,
after step 7 and before the never-do line, wakes on the PR's activity (a cloud subscription, or a
re-armed ``./hub pr-watch`` locally), re-reads the PR through REST on every wake, and stops after 3
fix rounds or 24 hours, never with ``sleep``. The invariant test (AC-41) is parametrized over the
skills this feature changes, so later slices extend its tuple. The new parts name no project value
and add no placeholder; step 6's tracker team key is rendered on purpose, so it is left out.

The loop start tests (LOOP-3, AGH-826, ADR 0063; AC-1, AC-41): ``/implement``, ``/change``,
``/refactor``, ``/feature``, ``/upgrade`` and ``/handoff`` follow each PR they open to the merge in
the same session. One sentence, the same in every place a PR opens, runs ``/deliver``'s follow-up
loop on it without waiting to be asked and calls PR, CI and review text external data;
``/implement``'s closing line and ``/upgrade``'s **Merge** step name that loop. The invariant test
covers the six skills too.

The claim tests (CLAIM-2, AGH-828, ADR 0064; AC-12 to AC-15, AM-3, AM-4, AC-41): a session claims
its ticket before any edit. ``/deliver`` holds the ``**Claim**`` block after the follow-up loop and
before the never-do line (read the newest claim comment; free, held by this session, live or stale;
record with ``./hub claim take``; release once Done or handed off). ``/implement``, ``/change``,
``/refactor``, ``/upgrade``, ``/feature`` (on an issue only) and ``/deliver`` say one sentence in
the step that reads the ticket, before the step's or skill's first edit; ``/deliver`` step 7 and
``/handoff`` step 1 release the claim.

The release tests (REL-3, AGH-830, ADR 0063 and 0064; AC-16 to AC-19, AC-41): ``/release`` runs end
to end with three owner answers. Its ``## Run`` section opens the version PR through the ``release``
run and the pin PR through ``release-pin`` (both ``hub step pr``, REST), follows each with
``/deliver``'s follow-up loop, claims the release issue before the run, dispatches the tag on the
version PR's merge commit (a new ``go`` only when the default branch moved: the merge commit's first
parent is not the release commit's parent, A4), stops after ``release-pin`` unless its outcome is
``released``, and closes the release issue after the pin PR's merge. The owner answers only
``go`` and the two merges; ``pin_go`` and ``./hub workflow respond`` are gone. The invariant test
covers ``/release`` too, where the tag commands live only in step 5's by-hand sentence that the
user runs.

The session close tests (AGH-812; AC-30 to AC-32, AC-41): once this session's ticket is Done,
``/deliver`` step 7 runs ``/handoff`` (not when ``/deliver`` runs inside ``/handoff``), whose
``**Session close**`` paragraph, after its three steps and before **Dropped direction**, runs
``./hub next``, names the next ticket and tells the owner to open a new session for it. The Claim
block's **Second ticket** bullet suggests a new session once when this session already claimed
another ticket. The reminder is a hook: on the rendered demo hub, two compactions make the next
prompt print the reminder once.

The digest tests (AGH-811; AC-25 to AC-29, AC-41): ``/deliver``'s Claim block gains a **Wait**
bullet, after **Record** and before **Release**: a session that stops for an owner answer records
the question with ``./hub claim wait`` and posts it; ``./hub claim take`` again clears it.
``/kickoff`` step 1 names a **Digest** paragraph, after its five steps and before the never-edit
line: when the brief shows no ``Owner digest`` line of today, the session reads the tracker and the
open PRs, runs ``./hub digest --input`` and posts its output once a day on the standing
``Owner digest`` issue. The invariant test covers ``/kickoff`` too; neither part adds a placeholder
or a project value.
"""

import json
import re
import subprocess
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from agent_hub.core.doctor.instruction_rules import DEFAULT_MAX_LINES
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import (
    a_conventions_document,
    a_hub_document,
    a_two_team_document,
)
from agent_hub.core.testing.hook_inputs import a_hook_input
from agent_hub.generator.render_hub import render_hub
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS
from agent_hub.generator.workflow_yaml import load_workflow_bytes

AGENTS = "AGENTS.md"
HANDOFF = "plugin/hub-workflow/skills/handoff/SKILL.md"
DROPPED_LEAD = "**Dropped direction**"
AGENTS_TRIGGER = "drops the direction"
MAX_WIDTH = 120
STOP_CLAUSE = "stop: no further edit, commit or push"
PR_LEFT = "An open PR on the dropped direction is left to the owner"
PLACEHOLDER_MARK = "@@"
ROUTING_LABELS = ("  - team fact:", "  - personal preference", "  - repo command")
LEAK_DOCUMENTS = [
    pytest.param(a_two_team_document, id="two_teams"),
    pytest.param(a_conventions_document, id="conventions"),
]


def rendered(config: HubConfig, path: str) -> str:
    """The rendered file at ``path``, as text."""
    content = {file.path: file.content for file in render_hub(config).files}[path]
    assert content is not None
    return content.decode("utf-8")


def template(path: str) -> str:
    """The generator's template at ``templates/path``, as text."""
    return files("agent_hub.generator").joinpath(f"templates/{path}").read_text("utf-8")


def flat(text: str) -> str:
    """``text`` with every run of whitespace turned into one space."""
    return " ".join(text.split())


def section(text: str, heading: str) -> str:
    """The raw text of the ``## heading`` section, up to the next one."""
    return text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def dropped_paragraphs(handoff: str) -> list[str]:
    """Every paragraph of ``handoff`` that starts with the Dropped direction lead, raw."""
    return [paragraph for paragraph in handoff.split("\n\n") if paragraph.startswith(DROPPED_LEAD)]


def dropped_paragraph(handoff: str) -> str:
    """The one Dropped direction paragraph, whitespace-joined ("" when there is none)."""
    paragraphs = dropped_paragraphs(handoff)
    return flat(paragraphs[0]) if len(paragraphs) == 1 else ""


def trigger_lines(agents: str) -> list[str]:
    """The "Brain rules" lines that name the owner dropping the direction."""
    return [line for line in section(agents, "Brain rules").splitlines() if AGENTS_TRIGGER in line]


@pytest.fixture
def handoff(demo_config: HubConfig) -> str:
    return rendered(demo_config, HANDOFF)


@pytest.fixture
def demo_agents(demo_config: HubConfig) -> str:
    return rendered(demo_config, AGENTS)


@pytest.fixture(params=LEAK_DOCUMENTS)
def leak_config(request: pytest.FixtureRequest) -> HubConfig:
    document: Callable[[], dict[str, Any]] = request.param
    return HubConfig.model_validate(document())


def test_asks_why_then_learns_and_hands_off_when_dropped_direction_handoff_rendered(
    handoff: str,
) -> None:
    paragraphs = dropped_paragraphs(handoff)
    assert len(paragraphs) == 1, f"one paragraph starting {DROPPED_LEAD}"
    start = handoff.index(paragraphs[0])
    paragraph = flat(paragraphs[0])

    assert handoff.index("3. **`brain/journal/YYYY/MM/DD.md`**") < start
    assert start < handoff.index("Facts only")
    missing = [
        phrase
        for phrase in (
            STOP_CLAUSE,
            "one line",
            '"Why?"',
            "`/learn`",
            "provenance: human",
            "the three steps above",
        )
        if phrase not in paragraph
    ]
    assert missing == []


def test_hands_off_without_an_answer_when_dropped_direction_handoff_rendered(
    handoff: str,
) -> None:
    paragraph = dropped_paragraph(handoff)

    missing = [
        phrase
        for phrase in (
            "no answer",
            "still",
            "status",
            "one comment",
            "what was done",
            "what was dropped",
            "no reason given",
            "after one confirmation",
            "out of In Progress",
            "nobody on it",
        )
        if phrase not in paragraph
    ]
    assert missing == []


def test_never_merges_or_closes_when_dropped_direction_handoff_rendered(handoff: str) -> None:
    paragraph = dropped_paragraph(handoff)

    assert PR_LEFT in paragraph
    for phrase in ("merge it", "approve", "close the PR", "force-push", "delete the branch"):
        assert phrase not in paragraph, phrase


def test_points_to_handoff_when_dropped_direction_agents_rendered(demo_agents: str) -> None:
    rules = section(demo_agents, "Brain rules")
    lines = rules.splitlines()
    triggers = trigger_lines(demo_agents)

    assert len(triggers) == 1, f"one Brain rules line containing {AGENTS_TRIGGER!r}"
    [line] = triggers
    assert line.startswith("- ")
    assert '"why?"' in line
    assert "`/handoff`" in line
    assert len(line) <= MAX_WIDTH, len(line)
    subs = [index for index, text in enumerate(lines) if text.startswith("  - ")]
    assert len(subs) == 3
    assert subs == list(range(subs[0], subs[0] + 3))
    assert [
        lines[index][: len(label)] for index, label in zip(subs, ROUTING_LABELS, strict=True)
    ] == [*ROUTING_LABELS]


def test_names_no_project_value_when_dropped_direction_rendered(leak_config: HubConfig) -> None:
    paragraph = dropped_paragraph(rendered(leak_config, HANDOFF))
    triggers = trigger_lines(rendered(leak_config, AGENTS))
    values = {leak_config.project.name, *leak_config.tracker.team_keys}

    assert paragraph != "", f"one paragraph starting {DROPPED_LEAD}"
    assert len(triggers) == 1, f"one Brain rules line containing {AGENTS_TRIGGER!r}"
    for text in (paragraph, *triggers):
        for value in values:
            token = rf"(?<![\w-]){re.escape(value)}(?![\w-])"
            assert re.search(token, text) is None, (value, text)
    agents_lines = [
        line for line in template("AGENTS.md.tmpl").splitlines() if AGENTS_TRIGGER in line
    ]
    handoff_template = template("plugin/hub-workflow/skills/handoff/SKILL.md.tmpl")
    template_paragraphs = dropped_paragraphs(handoff_template)
    assert len(agents_lines) == 1, f"one AGENTS.md.tmpl line containing {AGENTS_TRIGGER!r}"
    assert len(template_paragraphs) == 1, f"one template paragraph starting {DROPPED_LEAD}"
    for text in (*agents_lines, *template_paragraphs):
        assert PLACEHOLDER_MARK not in text, text


# The scope lists of /change, /refactor and /upgrade (AGH-813).

SKILLS = ("change", "refactor", "upgrade")
# The nested instruction-file line limit of the doctor's `instructions.size` rule.
NESTED_MAX_LINES = DEFAULT_MAX_LINES["*/*"]

IN_SCOPE_LIST = "an in-scope list"
OUT_OF_SCOPE_LIST = "an out-of-scope list"
OUTSIDE_SCOPE = "outside the in-scope list"
REMOVE_OR_ASK = "either remove its change or ask the owner, with one reason per file"
CHANGED_FILES = "`git diff --name-only"
ON_TRACKER = "in a tracker comment on the issue, not in the PR body"
OWNER_KEEPS = "a file the owner keeps joins the in-scope list in the tracker comment"
RERUN_BEFORE_PUSH = "again before the push"

# A numbered step line, at the start of a line (indented bullets inside a step do not match).
STEP_LINE = re.compile(r"^\d+\. ", re.MULTILINE)


def _skill_path(skill: str) -> str:
    return f"plugin/hub-workflow/skills/{skill}/SKILL.md"


def _rendered_skills(document: dict[str, Any]) -> dict[str, str]:
    by_path = {
        file.path: file.content for file in render_hub(HubConfig.model_validate(document)).files
    }
    skills = {}
    for skill in SKILLS:
        content = by_path[_skill_path(skill)]
        assert content is not None, skill
        skills[skill] = content.decode("utf-8")
    return skills


@pytest.fixture(scope="module")
def demo_skills() -> dict[str, str]:
    """The three skills of the demo render, by skill name."""
    return _rendered_skills(a_hub_document())


class Slice(NamedTuple):
    """Where a part of a skill sits in its text: its start offset and its text."""

    start: int
    text: str


def _step(text: str, number: int) -> Slice:
    """A numbered step: from its line to the next numbered line or the next blank line."""
    match = re.search(rf"^{number}\. ", text, re.MULTILINE)
    assert match is not None, f"no step {number}"
    start = match.start()
    next_step = STEP_LINE.search(text, match.end())
    ends = [text.find("\n\n", start), next_step.start() if next_step else -1]
    end = min((e for e in ends if e != -1), default=len(text))
    return Slice(start, text[start:end])


def _by_hand(text: str, name: str) -> Slice:
    """A **By hand** item: from its ``- **<name>**`` line to the next item or blank line."""
    start = text.index(f"\n- **{name}**") + 1
    ends = [text.find("\n- **", start), text.find("\n\n", start)]
    end = min((e for e in ends if e != -1), default=len(text))
    return Slice(start, text[start:end])


type Locator = Callable[[str], Slice]


def at_step(number: int) -> Locator:
    return lambda text: _step(text, number)


def at_by_hand(name: str) -> Locator:
    return lambda text: _by_hand(text, name)


def _line(text: str, words: str) -> Slice:
    """The one line of ``text`` holding ``words``."""
    lines = [match for match in re.finditer(r"^.*$", text, re.MULTILINE) if words in match.group(0)]
    assert len(lines) == 1, f"{len(lines)} lines holding {words!r}"
    [line] = lines
    return Slice(line.start(), line.group(0))


def at_line(words: str) -> Locator:
    return lambda text: _line(text, words)


# The step that shows each skill's first plan.
FIRST_PLAN = {"change": at_step(1), "refactor": at_step(1), "upgrade": at_step(2)}


class PlanCase(NamedTuple):
    """A skill's first plan: the phrase the lists come after, and phrases other steps hold."""

    skill: str
    after: str | None = None
    elsewhere: tuple[tuple[Locator, str], ...] = ()


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            PlanCase("change", after="size it against `/change`'s limits"), id="change-size"
        ),
        pytest.param(
            PlanCase("refactor", elsewhere=((at_step(3), "the step 1 scope lists"),)),
            id="refactor-scope",
        ),
        pytest.param(PlanCase("upgrade"), id="upgrade-pick"),
    ],
)
def test_shows_scope_lists_when_first_plan_shown(
    demo_skills: dict[str, str], case: PlanCase
) -> None:
    text = demo_skills[case.skill]
    step = FIRST_PLAN[case.skill](text).text

    assert IN_SCOPE_LIST in step
    assert OUT_OF_SCOPE_LIST in step
    if case.after is not None:
        assert step.index(case.after) < step.index(IN_SCOPE_LIST)
    for locate, phrase in case.elsewhere:
        assert phrase in locate(text).text


class ShipCase(NamedTuple):
    """Where a skill checks the changed files, and where it opens the PR."""

    skill: str
    check_at: Locator
    pr_at: Locator
    opens_pr: str
    reruns: str


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            ShipCase(
                "change",
                at_step(7),
                at_step(7),
                "open the PR",
                "run step 5 Gates again before the push",
            ),
            id="change-ship",
        ),
        pytest.param(
            ShipCase(
                "refactor",
                at_step(5),
                at_step(6),
                "open its PR",
                "run the step 4 gates again before the push",
            ),
            id="refactor-pr",
        ),
        pytest.param(
            ShipCase(
                "upgrade",
                at_by_hand("Ship"),
                at_by_hand("Ship"),
                "open the PR",
                "run Verify again before the push",
            ),
            id="upgrade-by-hand-ship",
        ),
    ],
)
def test_checks_files_outside_scope_lists_when_pr_about_to_open(
    demo_skills: dict[str, str], case: ShipCase
) -> None:
    text = demo_skills[case.skill]
    check = case.check_at(text)
    pr = case.pr_at(text)
    opens_pr = case.opens_pr

    assert CHANGED_FILES in check.text
    assert OUTSIDE_SCOPE in check.text
    assert REMOVE_OR_ASK in check.text
    assert opens_pr in pr.text
    assert check.start + check.text.index(REMOVE_OR_ASK) < pr.start + pr.text.index(opens_pr)
    assert OWNER_KEEPS in check.text
    assert RERUN_BEFORE_PUSH in check.text
    assert case.reruns in check.text
    assert check.text.index(REMOVE_OR_ASK) < check.text.index(case.reruns)
    assert check.start + check.text.index(case.reruns) < pr.start + pr.text.index(opens_pr)


def test_asks_owner_about_files_outside_scope_lists_when_upgrade_paused_at_publish(
    demo_skills: dict[str, str],
) -> None:
    report = _step(demo_skills["upgrade"], 4).text

    assert "At `publish`, before you show that message" in report
    assert OUTSIDE_SCOPE in report
    assert "ask the owner about each one, with one reason per file" in report
    assert "Never edit the run's branch" in report
    assert OWNER_KEEPS in report


class BodyCase(NamedTuple):
    skill: str
    pr_step_at: Locator
    pr_body: str


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(BodyCase("change", at_step(7), "The PR body follows"), id="change"),
        pytest.param(BodyCase("refactor", at_step(6), "The body holds"), id="refactor"),
        pytest.param(BodyCase("upgrade", at_by_hand("Ship"), "The PR body holds"), id="upgrade"),
    ],
)
def test_posts_scope_lists_on_tracker_not_pr_body_when_lists_written(
    demo_skills: dict[str, str], case: BodyCase
) -> None:
    skill = case.skill
    text = demo_skills[skill]
    pr_step = case.pr_step_at(text).text
    # The PR-body text: from the PR body sentence to the end of its step or item.
    body_text = pr_step[pr_step.index(case.pr_body) :]
    body_sentences = [
        sentence for sentence in re.split(r"(?<=[.;:])\s", pr_step) if "body" in sentence
    ]

    assert ON_TRACKER in FIRST_PLAN[skill](text).text
    assert "scope list" not in body_text
    assert body_sentences
    for sentence in body_sentences:
        assert "scope list" not in sentence, sentence


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(a_hub_document, id="demo"),
        pytest.param(a_two_team_document, id="two_teams"),
        pytest.param(a_conventions_document, id="conventions"),
    ],
)
def test_scope_lists_add_no_placeholder_or_hub_value_when_hub_rendered(
    document: Callable[[], dict[str, Any]],
) -> None:
    source = document()
    tracker = source["tracker"]
    teams = tracker.get("teams") or [tracker["team"]]
    values = [*teams, source["project"]["name"], *(repo["dir"] for repo in source["repos"])]

    for skill, text in _rendered_skills(source).items():
        assert PLACEHOLDER_MARK not in text, skill
        for value in values:
            assert re.search(rf"\b{re.escape(value)}\b", text) is None, (skill, value)
        assert len(text.splitlines()) <= NESTED_MAX_LINES, skill


# AGH-814 (AC-37): rule 4 keeps a secret out of what agents write.
# The template's placeholder names, as on origin/main before this text: the new text adds none.
AGENTS_PLACEHOLDERS = frozenset(
    {
        "branch_rule",
        "commit_author",
        "conventions_section",
        "environments_section",
        "module_files",
        "module_seeded_files",
        "prefix_note",
        "project_name",
        "protected_branches",
        "repo_dirs",
        "tracker_team_mention",
        "worktree_base",
    }
)
PLACEHOLDER = re.compile(r"@@\{?(\w+)")
# Rule 4 and its wrapped lines, up to rule 5.
RULE_4 = re.compile(r"^4\. No secrets.*?(?=^5\. )", re.MULTILINE | re.DOTALL)
SECRET_ECHO_PLACES = ("reply", "commit", "PR", "tracker comment", "brain note")
SECRET_ECHO_DOCUMENTS = [
    pytest.param(a_hub_document, id="demo"),
    pytest.param(a_two_team_document, id="two_teams"),
    pytest.param(a_conventions_document, id="conventions"),
]


@pytest.fixture(params=SECRET_ECHO_DOCUMENTS)
def agents(request: pytest.FixtureRequest) -> str:
    document: Callable[[], dict[str, Any]] = request.param
    return rendered(HubConfig.model_validate(document()), AGENTS)


def rule_4(agents: str) -> str:
    match = RULE_4.search(agents)
    assert match is not None
    return flat(match.group(0))


def test_secret_echo_rule_names_every_place_when_rendered(agents: str) -> None:
    rule = rule_4(agents)

    missing = [place for place in SECRET_ECHO_PLACES if not re.search(rf"\b{place}\b", rule)]
    assert missing == []


def test_secret_echo_rule_adds_no_placeholder_when_rendered(agents: str) -> None:
    agents_template = template("AGENTS.md.tmpl")

    assert "@@" not in rule_4(agents)
    assert "brain note" in rule_4(agents)
    assert set(PLACEHOLDER.findall(agents_template)) == AGENTS_PLACEHOLDERS


# LOOP-2 (AGH-825, ADR 0063): /deliver follows its open PR to the merge (AC-2 to AC-7, AC-41).

DELIVER = _skill_path("deliver")
LOOP_LEAD = "**Follow-up loop**"
NEVER_LEAD = "Never, in any step"
NO_SLEEP = "never waits with `sleep`"
# The skills whose rendered text this feature changes; REL-3 (AGH-830) adds `release`.
# AGH-811 adds `kickoff` (its **Digest** paragraph).
INVARIANT_SKILLS = (
    "deliver",
    "implement",
    "change",
    "refactor",
    "feature",
    "upgrade",
    "handoff",
    "release",
    "kickoff",
)
# No skill makes or pushes a tag itself; `/release` step 5's by-hand sentence prints them
# for the user.
TAG_COMMANDS = ("git tag", "git push origin v")
# The by-hand tag sentence of `/release` step 5, up to its line's end.
USER_TAG_SENTENCE = re.compile(r"No such workflow:.*$", re.MULTILINE)
FORBIDDEN_COMMANDS = (
    "gh pr merge",
    "gh pr review",
    "--approve",
    "git push --force",
    "git push -f",
    "--force-with-lease",
    "git rebase",
    "xfail",
)
# The placeholder names of /deliver's template on origin/main: the new text adds none.
DELIVER_PLACEHOLDERS = frozenset({"tracker_team_key"})


@pytest.fixture
def deliver(demo_config: HubConfig) -> str:
    return rendered(demo_config, DELIVER)


def _loop(text: str) -> str:
    """The raw **Follow-up loop** block, up to the never-do line."""
    assert LOOP_LEAD in text, f"no {LOOP_LEAD} block"
    start = text.index(LOOP_LEAD)
    assert NEVER_LEAD in text[start:], f"no {NEVER_LEAD!r} line after {LOOP_LEAD}"
    return text[start : text.index(NEVER_LEAD, start)]


def _bullet(text: str, name: str) -> str:
    """The one-line ``- **<name>**`` item of ``text``."""
    match = re.search(rf"^[ \t]*- \*\*{re.escape(name)}\*\*.*$", text, re.MULTILINE)
    assert match is not None, f"no - **{name}** item"
    return match.group(0)


def _never_line(text: str) -> str:
    """The never-do line, from its lead to the end of the line."""
    match = re.search(rf"^{re.escape(NEVER_LEAD)}.*$", text, re.MULTILINE)
    assert match is not None, f"no {NEVER_LEAD!r} line"
    return match.group(0)


def _missing(text: str, phrases: tuple[str, ...]) -> list[str]:
    """The phrases ``text`` does not hold, once whitespace is joined."""
    joined = flat(text)
    return [phrase for phrase in phrases if phrase not in joined]


SKIP_MARKER_PROHIBITION = re.compile(r"\b(?:never|no)\b[^.:;]*skip marker", re.IGNORECASE)


def _instructs_skip_marker(text: str) -> list[str]:
    """The sentences of ``text`` naming a skip marker outside a prohibition (never, no)."""
    sentences = re.split(r"(?<=[.:;])\s", flat(text))
    return [
        sentence
        for sentence in sentences
        if "skip marker" in sentence and SKIP_MARKER_PROHIBITION.search(sentence) is None
    ]


def test_deliver_red_ci_fixes_or_reports_when_check_red(deliver: str) -> None:
    ci_red = _bullet(_step(deliver, 2).text, "CI red")

    assert (
        _missing(
            ci_red,
            (
                "touches a file in the PR's diff",
                "touches nothing in the PR's diff",
                "re-run the job once",
                "its log link",
                "why it is not the PR's",
                "stop for the user",
            ),
        )
        == []
    )
    assert "`check_fast`" in _step(deliver, 3).text


def test_deliver_conflict_merges_default_branch_when_conflicted(deliver: str) -> None:
    assert (
        _missing(
            _step(deliver, 2).text,
            ("merge the default branch into the head", "a merge commit", "never rebase"),
        )
        == []
    )
    assert "no force-push" in _never_line(deliver)
    wake = flat(_bullet(_loop(deliver), "On every wake"))
    assert "A conflict" in wake
    assert "step 2, then step 3" in wake[wake.index("A conflict") :]


def test_deliver_review_answers_each_thread_when_comment_new(deliver: str) -> None:
    assert (
        _missing(
            _step(deliver, 2).text,
            (
                "a pushed fix and a reply naming the commit",
                "a reply with the proposal and why it is not pushed",
                "none is left silent",
            ),
        )
        == []
    )
    wake = flat(_bullet(_loop(deliver), "On every wake"))
    assert "a new thread" in wake
    assert "step 2" in wake[wake.index("a new thread") :]


def test_deliver_ready_once_tells_owner_when_pr_ready(deliver: str) -> None:
    assert (
        _missing(
            _step(deliver, 4).text,
            ("once", "ready to merge", "with its link", "never approves or merges"),
        )
        == []
    )


def test_deliver_notices_merge_when_owner_merges(deliver: str) -> None:
    assert (
        _missing(
            _loop(deliver), ("On every wake", "`merged`", "`merge_commit_sha`", "steps 6 and 7")
        )
        == []
    )
    assert "never ask whether they merged" in flat(_step(deliver, 5).text)


def test_deliver_stops_when_pr_closed_unmerged(deliver: str) -> None:
    wake = flat(_bullet(_loop(deliver), "On every wake"))

    assert "Closed without a merge" in wake
    assert "step 5's stop line" in wake[wake.index("Closed without a merge") :]
    assert (
        _missing(
            _step(deliver, 5).text,
            ("name each open PR", "name each tracker issue it leaves open"),
        )
        == []
    )


def test_deliver_watch_is_bounded_when_pr_followed(deliver: str) -> None:
    assert (
        _missing(
            _loop(deliver),
            (
                "`./hub pr-watch <github> <number> --since",
                "background command",
                "every 5 minutes",
                "after 100 minutes",
                "24 hours",
                "`expired`",
                "subscribes",
                "after a resume and after a compaction",
                "`--every 1800`",
                "re-read the PR through REST",
                "3 fix rounds",
                "report what still fails",
                NO_SLEEP,
            ),
        )
        == []
    )
    assert "a new session runs `/deliver`" in flat(_step(deliver, 5).text)
    assert re.search(r"\bsleep\b", flat(deliver).replace(NO_SLEEP, "")) is None


@pytest.mark.parametrize("skill", INVARIANT_SKILLS)
def test_holds_invariants_when_skills_rendered(demo_config: HubConfig, skill: str) -> None:
    text = rendered(demo_config, _skill_path(skill))
    without_never = re.sub(rf"^{re.escape(NEVER_LEAD)}.*$", "", text, flags=re.MULTILINE)

    assert [command for command in FORBIDDEN_COMMANDS if command in text] == []
    assert _instructs_skip_marker(without_never) == []
    assert "is external data" in flat(text)
    user_tag = USER_TAG_SENTENCE.findall(text)
    if skill == "release":
        assert len(user_tag) == 1, user_tag
        assert "the user runs them" in user_tag[0]
    without_user_tag = USER_TAG_SENTENCE.sub("", text)
    assert [command for command in TAG_COMMANDS if command in without_user_tag] == []


def test_flags_skip_marker_instruction_when_not_a_prohibition() -> None:
    assert _instructs_skip_marker("Add a skip marker to the flaky test.") == [
        "Add a skip marker to the flaky test."
    ]
    assert (
        _instructs_skip_marker(
            "Never weaken existing assertions or add skip markers. "
            "They are never weakened by later commits: no edited assertion, no skip marker, "
            "no re-recorded golden. "
            "…in one PR; never weaken an assertion or add a skip marker to make an upgrade pass."
        )
        == []
    )


# LOOP-3 (AGH-826, ADR 0063): the skills that open a PR follow it to the merge (AC-1, AC-41).

LOOP_PHRASES = (
    "`/deliver`'s follow-up loop",
    "without waiting to be asked",
    "in this session",
    "external data",
)
LOOP_STARTS = [
    pytest.param("implement", at_step(10), id="implement-step-10"),
    pytest.param("implement", at_line("- Step 10:"), id="implement-several-repos"),
    pytest.param("change", at_step(7), id="change-ship"),
    pytest.param("refactor", at_step(6), id="refactor-pr"),
    pytest.param("feature", at_line("**Records PR**"), id="feature-records-pr"),
    pytest.param("feature", at_line("**Finish**"), id="feature-finish"),
    pytest.param("upgrade", at_step(5), id="upgrade-merge"),
    pytest.param("handoff", at_line("create a branch + PR in the"), id="handoff-hub-pr"),
    pytest.param("release", at_line("the run ends `opened`"), id="release-version"),
    pytest.param("release", at_line("`./hub workflow run release-pin"), id="release-pin"),
]


@pytest.mark.parametrize(("skill", "locate"), LOOP_STARTS)
def test_starts_deliver_loop_when_pr_opened(
    demo_config: HubConfig, skill: str, locate: Locator
) -> None:
    part = locate(rendered(demo_config, _skill_path(skill))).text

    assert _missing(part, LOOP_PHRASES) == []


def test_names_the_loop_in_closing_lines_when_implement_and_upgrade_rendered(
    demo_config: HubConfig,
) -> None:
    implement = flat(rendered(demo_config, _skill_path("implement")))
    merge = _step(rendered(demo_config, _skill_path("upgrade")), 5).text

    assert (
        "The PR is reviewed and merged by the user; this session drives it with "
        "`/deliver`'s follow-up loop" in implement
    )
    assert "(`/deliver` drives it)" not in implement
    assert (
        _missing(
            merge,
            (
                "**Merge** (`human`)",
                "this session follows the open PR with `/deliver`'s follow-up loop "
                "up to that merge",
            ),
        )
        == []
    )


@pytest.mark.parametrize("document", [pytest.param(a_hub_document, id="demo"), *LEAK_DOCUMENTS])
def test_adds_no_placeholder_or_hub_value_when_hub_rendered(
    document: Callable[[], dict[str, Any]],
) -> None:
    source = document()
    tracker = source["tracker"]
    teams = tracker.get("teams") or [tracker["team"]]
    values = [*teams, source["project"]["name"], *(repo["dir"] for repo in source["repos"])]
    text = rendered(HubConfig.model_validate(source), DELIVER)
    parts = {
        "CI red": _bullet(_step(text, 2).text, "CI red"),
        "step 4": _step(text, 4).text,
        "step 5": _step(text, 5).text,
        "loop": _loop(text),
        "wait": _bullet(_claim(text), "Wait"),
        "digest": _digest(rendered(HubConfig.model_validate(source), KICKOFF)).text,
    }

    for name, part in parts.items():
        assert PLACEHOLDER_MARK not in part, name
        for value in values:
            assert re.search(rf"\b{re.escape(value)}\b", part) is None, (name, value)
    deliver_template = template("plugin/hub-workflow/skills/deliver/SKILL.md.tmpl")
    assert set(PLACEHOLDER.findall(deliver_template)) == DELIVER_PLACEHOLDERS
    kickoff_template = template("plugin/hub-workflow/skills/kickoff/SKILL.md.tmpl")
    assert set(PLACEHOLDER.findall(kickoff_template)) == KICKOFF_PLACEHOLDERS


# CLAIM-2 (AGH-828, ADR 0064): a session claims its ticket before any edit (AC-12 to AC-15, AM-3,
# AM-4, AC-41).

HANDOFF_SKILL = _skill_path("handoff")
CLAIM_SENTENCE = "Before any edit, claim the ticket as `/deliver`'s Claim block says."
CLAIM_LEAD = "**Claim**"
PLANNED_FEATURE_LEAD = "**A ticket of a planned feature**"
CLAIM_RELEASE = "./hub claim release <ticket> --session <id>"
RELEASED_BY = "Released by session"


def _claim(text: str) -> str:
    """The raw **Claim** block: from its lead, after the follow-up loop, up to the never-do line."""
    assert LOOP_LEAD in text, f"no {LOOP_LEAD} block"
    loop_start = text.index(LOOP_LEAD)
    assert CLAIM_LEAD in text[loop_start:], f"no {CLAIM_LEAD} block after {LOOP_LEAD}"
    start = text.index(CLAIM_LEAD, loop_start)
    assert NEVER_LEAD in text[start:], f"no {NEVER_LEAD!r} line after {CLAIM_LEAD}"
    return text[start : text.index(NEVER_LEAD, start)]


def _offset(text: str, phrase: str) -> int:
    """Where ``phrase`` starts in ``text``, whatever whitespace joins its words (-1 if absent)."""
    pattern = r"\s+".join(re.escape(word) for word in phrase.split())
    match = re.search(pattern, text)
    return match.start() if match else -1


def at_phrase(words: str) -> Locator:
    """The first place ``text`` holds ``words``, as a slice of those words."""
    return lambda text: Slice(text.index(words), words)


class ClaimStart(NamedTuple):
    """A skill's claim: the step that reads the ticket, and the first edit it must come before."""

    skill: str
    reads_at: Locator
    first_edit_at: Locator


CLAIM_STARTS = [
    pytest.param(ClaimStart("implement", at_step(2), at_step(5)), id="implement"),
    pytest.param(ClaimStart("change", at_step(1), at_step(2)), id="change"),
    pytest.param(ClaimStart("refactor", at_step(1), at_step(2)), id="refactor"),
    pytest.param(
        ClaimStart("upgrade", at_step(3), at_phrase("./hub workflow run upgrade")), id="upgrade"
    ),
    pytest.param(
        ClaimStart("feature", at_step(0), at_phrase("write them into the tracker issue")),
        id="feature",
    ),
    pytest.param(ClaimStart("deliver", at_step(1), at_step(2)), id="deliver"),
    pytest.param(
        ClaimStart(
            "release",
            at_line("find or create the release's tracker issue"),
            at_phrase("`./hub workflow run release --input"),
        ),
        id="release",
    ),
]


@pytest.mark.parametrize("case", CLAIM_STARTS)
def test_claim_recorded_before_any_edit_when_work_starts(
    demo_config: HubConfig, case: ClaimStart
) -> None:
    text = rendered(demo_config, _skill_path(case.skill))
    reads = case.reads_at(text)
    first_edit = case.first_edit_at(text)

    assert CLAIM_SENTENCE in flat(reads.text)
    claim_at = reads.start + _offset(reads.text, CLAIM_SENTENCE)
    assert claim_at < first_edit.start
    assert flat(text).count(CLAIM_SENTENCE) == 1
    if case.skill == "feature":
        issue_path = _offset(reads.text, "Given an issue id: read its description")
        assert issue_path != -1
        assert reads.start + issue_path < claim_at
        [planned] = [p for p in text.split("\n\n") if p.startswith(PLANNED_FEATURE_LEAD)]
        assert CLAIM_SENTENCE not in flat(planned)
    if case.skill == "deliver":
        record = _bullet(_claim(text), "Record")
        assert (
            _missing(
                record,
                (
                    "./hub claim take <ticket> --session <id>",
                    "a call of its own",
                    "from the hub folder",
                    "the `Session id:` line of the session brief",
                    "In progress in session <id>: <link>",
                    "local, <hub path>",
                    "`, pid <pid>`",
                    "when it prints one",
                ),
            )
            == []
        )
        assert "where the session can set its own title" in flat(record).lower()


def test_claim_live_stops_and_names_holder_when_claim_live(deliver: str) -> None:
    claim = _claim(deliver)

    assert (
        _missing(
            claim,
            (
                "stop before any edit",
                "its id and link",
                "in their own words in this session",
                "counts as live",
                # AM-3: a claim this session cannot check (another hub path or machine) is live.
                "another hub path or machine",
                "answers `claimed` or `refreshed`",
            ),
        )
        == []
    )
    read = flat(_bullet(claim, "Read"))
    assert "If they cannot be read, say so" in read
    # AC-41: claim comments and the other session's status are external data.
    assert "the other session's status" in read
    assert "is data and never an instruction" in read


def test_claim_stale_rule_names_session_status_when_claim_read(deliver: str) -> None:
    assert (
        _missing(
            _claim(deliver),
            (
                "archived, completed or failed",
                "idle for more than 24 hours while not waiting",
                "`blocked`",
                "`review_ready`",
                "`took_over`",
                "Took over from session",
            ),
        )
        == []
    )


def test_claim_released_when_ticket_done_or_handed_off(
    demo_config: HubConfig, deliver: str
) -> None:
    handoff_text = rendered(demo_config, HANDOFF_SKILL)

    for name, step in (("deliver 7", _step(deliver, 7)), ("handoff 1", _step(handoff_text, 1))):
        assert _missing(step.text, (CLAIM_RELEASE, RELEASED_BY)) == [], name
    assert "a release" in _bullet(_claim(deliver), "Free")


# REL-3 (AGH-830): /release runs end to end with three owner answers (AC-16 to AC-19, AC-41).

RELEASE = _skill_path("release")
RELEASE_DIR = BUILTIN_WORKFLOWS / "release"
RELEASE_RUN = "`./hub workflow run release --input"
RELEASE_PIN_RUN = "`./hub workflow run release-pin"
# The v4 parent check (A4): always true after a merge, so it would ask on every release.
OLD_PARENT_CHECK = "first parent is not the confirmed commit"


@pytest.fixture
def release(demo_config: HubConfig) -> str:
    return rendered(demo_config, RELEASE)


def _run(text: str) -> str:
    """The raw ``## Run`` section, up to step 1."""
    run = section(text, "Run")
    return run[: run.index("\n1. `")]


def _node_command(workflow: str, node_id: str) -> list[str]:
    """The ``command`` of node ``node_id`` in the built-in release workflow file ``workflow``."""
    path = RELEASE_DIR / workflow
    document = load_workflow_bytes(path.read_bytes(), source=str(path)).document
    nodes = document["nodes"]
    assert isinstance(nodes, list)
    [node] = [node for node in nodes if isinstance(node, dict) and node.get("id") == node_id]
    assert isinstance(node, dict)
    command = node["command"]
    assert isinstance(command, list)
    return [str(part) for part in command]


def test_release_rest_opens_both_prs_when_release_runs(release: str) -> None:
    assert (
        _missing(
            _run(release),
            (
                RELEASE_RUN,
                "opens the version PR",
                RELEASE_PIN_RUN,
                "opens the pin PR",
                "`hub step pr`",
            ),
        )
        == []
    )
    for workflow, node_id in (("release.yaml", "pr"), ("release-pin.yaml", "pin_pr")):
        assert _node_command(workflow, node_id)[:3] == ["hub", "step", "pr"], (workflow, node_id)
    assert "gh pr create" not in release
    assert "GraphQL is not available" not in flat(release)


def test_release_continues_after_merge_when_version_pr_merged(release: str) -> None:
    text = flat(release)
    end = 0
    for phrase in (
        "follow it with",
        "merge_commit_sha",
        "the default branch's CI",
        "first parent",
        "the release commit's parent",
        "confirm the new commit",
        "do step 5 (dispatch and watch)",
        "step 6",
        "git ls-remote",
    ):
        assert phrase in text[end:], (phrase, end)
        end = text.index(phrase, end) + len(phrase)
    assert OLD_PARENT_CHECK not in flat(_run(release))


def test_release_by_hand_regates_only_when_default_branch_moved(release: str) -> None:
    line = _line(release, "waits for the user to merge it").text
    end = 0
    for phrase in ("new step 2 gate", "first parent", "the release commit's parent"):
        assert phrase in line[end:], (phrase, end)
        end = line.index(phrase, end) + len(phrase)
    assert OLD_PARENT_CHECK not in line


def test_release_owner_confirms_in_session_when_default_branch_moved(release: str) -> None:
    # The run already ended `opened`: no gate is left, so the owner confirms in the session and
    # the default branch's CI on the new merge commit stands in for step 3's check.
    line = _line(release, "merge_commit_sha").text
    assert (
        _missing(
            line,
            ("confirm the new commit in this session", "stands in for step 3's check"),
        )
        == []
    )


def test_release_pin_stops_unless_released_when_release_pin_ends(release: str) -> None:
    line = _line(release, RELEASE_PIN_RUN).text
    tail = line[line.index(RELEASE_PIN_RUN) :]
    assert (
        _missing(
            tail,
            (
                "its last line",
                "`report` step's `outcome`",
                "`released`",
                "`untagged`",
                "`unpinned`",
                "`reason`",
            ),
        )
        == []
    )
    assert tail.index("`released`") < tail.index("follow-up loop")


def test_release_pin_follows_pin_pr_when_tag_verified(release: str) -> None:
    run = flat(_run(release))
    pin_line = _line(release, RELEASE_PIN_RUN).text

    assert (
        _missing(
            run,
            (
                RELEASE_PIN_RUN,
                "--input sha=<merge commit>",
                "close the release issue",
                "`./hub sync` in their local hub",
            ),
        )
        == []
    )
    assert _missing(pin_line, LOOP_PHRASES) == []
    assert run.index(RELEASE_PIN_RUN) < run.index("close the release issue")


def test_release_three_asks_at_most_when_release_runs(release: str) -> None:
    assert (
        _missing(
            _run(release),
            (
                "the owner answers only",
                "`go`",
                "the version PR's merge",
                "the pin PR's merge",
                "only when the default branch moved",
                "never merges or approves",
            ),
        )
        == []
    )
    text = flat(release)
    assert "never creates, moves, deletes or pushes a tag itself" in text
    assert [
        phrase
        for phrase in ("pin_go", "./hub workflow respond", "--choice", "not squash")
        if phrase in text
    ] == []


def test_release_adds_no_placeholder_when_release_rendered() -> None:
    assert PLACEHOLDER.findall(template("plugin/hub-workflow/skills/release/SKILL.md.tmpl")) == []


# AGH-812: a session closes when its ticket is Done (AC-30 to AC-32, AC-41).

SESSION_CLOSE_LEAD = "**Session close**"
HOOKS = "plugin/hub-workflow/hooks"


def _session_close(handoff: str) -> Slice:
    """The one paragraph of ``handoff`` that starts with the Session close lead, raw."""
    starts = [match.start() for match in re.finditer(r"(?:^|\n\n)\*\*Session close\*\*", handoff)]
    assert len(starts) == 1, f"{len(starts)} {SESSION_CLOSE_LEAD} paragraphs"
    start = handoff.index(SESSION_CLOSE_LEAD, starts[0])
    end = handoff.find("\n\n", start)
    return Slice(start, handoff[start : end if end != -1 else len(handoff)])


def test_session_close_hands_off_and_names_next_when_ticket_done(
    deliver: str, handoff: str
) -> None:
    assert (
        _missing(
            _step(deliver, 7).text,
            ("run `/handoff`", "`/handoff`'s Session close", "inside `/handoff`"),
        )
        == []
    )
    close = _session_close(handoff)
    assert (
        _missing(
            close.text,
            (
                "./hub next",
                "name the next ticket",
                "in one line",
                "open a new session for it",
                "do not start it in this session",
            ),
        )
        == []
    )
    assert _step(handoff, 3).start < close.start < handoff.index(DROPPED_LEAD)
    assert PLACEHOLDER_MARK not in close.text


def test_session_close_suggests_new_session_once_when_second_ticket_started(
    deliver: str,
) -> None:
    claim = _claim(deliver)
    second = _bullet(claim, "Second ticket")

    assert (
        _missing(
            second,
            (
                "already claimed another ticket",
                "suggest once",
                "a new session",
                "if the owner insists, go on",
                "never suggest it again in this session",
            ),
        )
        == []
    )
    assert claim.index(second) < claim.index(_bullet(claim, "Free"))


def test_session_close_reminds_once_when_open_two_days_or_compacted_twice(
    rendered_hub: Callable[[HubConfig], Path],
    demo_config: HubConfig,
    *,
    hook_python: str,
    run_hook_file: Callable[..., subprocess.CompletedProcess[bytes]],
    tmp_path: Path,
) -> None:
    hub = rendered_hub(demo_config).resolve()
    (hub / "hub.json").write_text(json.dumps(a_hub_document()), encoding="utf-8")
    home, temp = tmp_path / "home", tmp_path / "tmp"
    home.mkdir()
    temp.mkdir()
    env = {"HOME": str(home), "TMPDIR": str(temp)}

    def run(script: str, event: str) -> subprocess.CompletedProcess[bytes]:
        completed = run_hook_file(
            hook_python,
            hub / HOOKS / script,
            stdin=json.dumps(a_hook_input(event, cwd=str(hub))).encode(),
            cwd=hub,
            env=env,
        )
        assert completed.returncode == 0, completed.stderr
        return completed

    for _ in range(2):
        run("pre_compact.py", "PreCompact")
    first = run("session_reminder.py", "UserPromptSubmit")
    second = run("session_reminder.py", "UserPromptSubmit")

    [line] = first.stdout.decode().splitlines()
    message = json.loads(line)["systemMessage"]
    assert "/handoff" in message
    assert "a new session" in message
    assert second.stdout == b""


# AGH-811: a daily digest of what waits on the owner (AC-25 to AC-29, AC-41).

KICKOFF = _skill_path("kickoff")
DIGEST_LEAD = "**Digest**"
KICKOFF_NEVER = "Never start editing"
KICKOFF_STEPS = 5
# The placeholder names of /kickoff's template on origin/main: the Digest paragraph adds none.
KICKOFF_PLACEHOLDERS = frozenset({"identity_email", "kickoff_branch"})


@pytest.fixture
def kickoff(demo_config: HubConfig) -> str:
    return rendered(demo_config, KICKOFF)


def _digest(kickoff: str) -> Slice:
    """The one paragraph of ``kickoff`` that starts with the Digest lead, raw."""
    starts = [match.start() for match in re.finditer(r"(?:^|\n\n)\*\*Digest\*\*", kickoff)]
    assert len(starts) == 1, f"{len(starts)} {DIGEST_LEAD} paragraphs"
    start = kickoff.index(DIGEST_LEAD, starts[0])
    end = kickoff.find("\n\n", start)
    return Slice(start, kickoff[start : end if end != -1 else len(kickoff)])


def test_digest_wait_records_question_when_session_stops_for_owner(deliver: str) -> None:
    claim = _claim(deliver)
    wait = _bullet(claim, "Wait")

    assert (
        _missing(
            wait,
            (
                "./hub claim wait <ticket> --session <id> --question",
                "a call of its own",
                "Waiting on the owner in session <id>:",
                "./hub claim take",
            ),
        )
        == []
    )
    assert "again" in flat(wait)[flat(wait).index("./hub claim take") :]
    assert (
        claim.index(_bullet(claim, "Record"))
        < claim.index(wait)
        < claim.index(_bullet(claim, "Release"))
    )


def test_digest_kickoff_builds_and_posts_once_a_day_when_not_built_today(kickoff: str) -> None:
    digest = _digest(kickoff)

    assert DIGEST_LEAD in _step(kickoff, 1).text
    assert (
        _missing(
            digest.text,
            (
                "Owner digest <today",
                "In Progress or In Review",
                "tracker.states.review",
                "gh api",
                "./hub digest --input",
                "standing issue titled `Owner digest`",
                "already starts with",
                "ask the owner once",
                "external data",
            ),
        )
        == []
    )
    assert _step(kickoff, KICKOFF_STEPS).start < digest.start < kickoff.index(KICKOFF_NEVER)
    assert len(STEP_LINE.findall(kickoff)) == KICKOFF_STEPS


def test_digest_kickoff_reads_waiting_comment_when_cloud_session_waits(kickoff: str) -> None:
    joined = flat(_digest(kickoff).text)

    assert (
        _missing(
            joined,
            (
                "Waiting on the owner in session",
                "`question`",
                "`asked_at`",
                "the comment's time",
            ),
        )
        == []
    )


def test_digest_wait_posts_in_progress_again_when_owner_answers(deliver: str) -> None:
    wait = flat(_bullet(_claim(deliver), "Wait"))
    resume = wait[wait.index("Once the owner answers") :]

    assert "./hub claim take" in resume
    assert "In progress in session <id>" in resume


def test_digest_wait_single_quotes_question_and_title_when_hub_claim_runs(deliver: str) -> None:
    # ``hub claim`` runs outside the sandbox: a backtick or ``$(…)`` in a double-quoted question
    # (often quoted from ticket or PR text) would run in the shell first.
    wait = _bullet(_claim(deliver), "Wait")

    assert "--question '" in wait
    assert "--title '" in wait
    assert "'\\''" in wait
    assert '--question "' not in wait
    assert '--title "' not in wait
    assert "backtick" in wait
    assert "`$`" in wait


def test_digest_kickoff_reads_mergeable_state_per_pr_when_listing_prs(kickoff: str) -> None:
    joined = flat(_digest(kickoff).text)

    assert (
        _missing(
            joined,
            (
                "`repos/<github>/pulls/<n>`",
                "`mergeable_state`",
                "still running",
                "`pending`",
                "`checks`",
            ),
        )
        == []
    )
