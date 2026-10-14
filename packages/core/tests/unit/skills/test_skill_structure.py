import pytest

from agent_hub.core.skills.skill_structure import (
    CLAUDE_CODE_COMMANDS,
    MAX_HEADING_CHARS,
    MAX_REFERENCES,
    MAX_STEP_TITLE_CHARS,
    MAX_STEPS,
    derive_structure,
    references,
    step_count,
    table_of_contents,
)
from agent_hub.core.skills.skill_view import Step, TocEntry
from agent_hub.core.testing.skill_trees import FEATURE_BODY_STEPS, a_feature_shaped_body

AGENTS = frozenset({"requirements-analyst", "evaluator"})
SKILLS = frozenset({"create-plan", "feature"})


def test_derives_steps_when_body_shaped_like_feature() -> None:
    structure = derive_structure(a_feature_shaped_body(), agents=AGENTS, skills=SKILLS)

    assert structure.steps == (
        Step(index=1, title="Spec", tags=("agent",), agents=("requirements-analyst",)),
        Step(index=2, title="Gate: user approves the spec", tags=("gate", "human")),
        Step(index=3, title="Plan", skills=("create-plan",)),
        Step(index=4, title="Implement", tags=("command",), commands=("make check",)),
        Step(index=5, title="Doctor", tags=("command",), commands=("./hub doctor",)),
    )
    assert structure.agents == ("requirements-analyst",)
    assert structure.skills == ("create-plan",)
    assert structure.commands == ("make check", "./hub doctor")
    assert structure.gates == ("Gate: user approves the spec",)
    assert structure.dynamic_context == 0
    assert not structure.truncated


def test_lists_agents_and_skills_only_when_cataloged() -> None:
    structure = derive_structure(a_feature_shaped_body(), agents=frozenset(), skills=frozenset())

    assert structure.steps[0].tags == ()
    assert structure.steps[0].agents == ()
    assert structure.steps[2].skills == ()
    assert structure.agents == ()
    assert structure.skills == ()


def test_gives_no_steps_when_body_has_no_ordered_list() -> None:
    body = "# Notes\n\n- a bullet\n- another `make check`\n\nPlain text.\n"

    structure = derive_structure(body, agents=AGENTS, skills=SKILLS)

    assert structure.steps == ()
    assert structure.commands == ("make check",)


@pytest.mark.parametrize(
    ("body", "steps"),
    [
        pytest.param(a_feature_shaped_body(), FEATURE_BODY_STEPS, id="anchors-feature-body"),
        pytest.param("1. one\n2) two\n  3. nested\n", 2, id="anchors-nested"),
        pytest.param("~~~\n1. fenced\n~~~\n1. after\n", 1, id="anchors-tilde-fence"),
        pytest.param("````\n```\n1. still fenced\n````\n", 0, id="anchors-long-fence"),
        pytest.param("1.no space\n1234567890. too long\n", 0, id="anchors-not-items"),
        pytest.param(" 1. one\n   2. two\n\n1. three\n", 1, id="anchors-indented-list"),
    ],
)
def test_counts_steps_like_web_when_lists_nested_or_fenced(body: str, steps: int) -> None:
    assert step_count(body) == steps
    assert len(derive_structure(body, agents=AGENTS, skills=SKILLS).steps) == steps


def test_lists_headings_when_toc_built() -> None:
    body = (
        "# Feature\n\n## Steps ##\n\n```md\n# not a heading\n```\n"
        "   ### Indented three\n    # code by indent\n#nospace\n####### seven\n"
    )

    assert table_of_contents(body) == (
        TocEntry(level=1, text="Feature"),
        TocEntry(level=2, text="Steps"),
        TocEntry(level=3, text="Indented three"),
    )


@pytest.mark.parametrize(
    ("line", "toc"),
    [
        pytest.param("# a #", (TocEntry(level=1, text="a"),), id="closing-sequence"),
        pytest.param("# a#", (TocEntry(level=1, text="a#"),), id="hash-in-text"),
        pytest.param("# #", (), id="only-closing-sequence"),
        pytest.param("#   ", (), id="only-spaces"),
        pytest.param("# a ##  ", (TocEntry(level=1, text="a"),), id="closing-then-spaces"),
        pytest.param("## a\t#\t", (TocEntry(level=2, text="a"),), id="closing-after-tab"),
        pytest.param("#" + " " * 1000, (), id="long-blank-heading"),
    ],
)
def test_strips_closing_sequence_when_heading_read(line: str, toc: tuple[TocEntry, ...]) -> None:
    assert table_of_contents(f"{line}\n") == toc


def test_skips_heading_when_line_over_cap() -> None:
    at_cap = "# " + "a" * (MAX_HEADING_CHARS - 2)
    over = "# " + "b" * (MAX_HEADING_CHARS - 1)

    toc = table_of_contents(f"{at_cap}\n\n{over}\n")

    assert len(at_cap) == MAX_HEADING_CHARS
    assert toc == (TocEntry(level=1, text="a" * (MAX_HEADING_CHARS - 2)),)


def test_marks_reference_unresolved_when_name_not_cataloged_or_builtin() -> None:
    body = (
        "Run `/create-plan`, then /missing-skill and `/hub-workflow:feature`.\n"
        "Use /compact if long; ask the `ghost` agent and the `evaluator` agent.\n"
        "Paths like scripts/s.sh, /etc/passwd and https://x.example/y are not references.\n"
        "```\n/fenced-skill and the `fenced` agent\n```\n"
    )

    found = references(body, agents=AGENTS, skills=SKILLS)

    assert found.agents == ("evaluator",)
    assert found.skills == ("create-plan", "feature")
    assert found.unresolved == ("/missing-skill", "ghost")
    assert "compact" in CLAUDE_CODE_COMMANDS


def test_counts_dynamic_context_when_bang_blocks_present() -> None:
    body = (
        "Status: !`git status` and !`git diff --stat`.\n"
        "```!\nmake check\n```\n"
        "```bash\necho !`not counted`\n```\n"
    )

    structure = derive_structure(body, agents=AGENTS, skills=SKILLS)

    assert structure.dynamic_context == 3
    assert structure.commands == ()


def test_tags_scripts_when_step_names_skill_scripts() -> None:
    body = "1. Run `scripts/check.sh` then `${CLAUDE_SKILL_DIR}/scripts/two.py`.\n"

    (step,) = derive_structure(body, agents=AGENTS, skills=SKILLS).steps

    assert step.tags == ("script",)
    assert step.scripts == ("scripts/check.sh", "${CLAUDE_SKILL_DIR}/scripts/two.py")
    assert step.title == "Run `scripts/check.sh` then `${CLAUDE_SKILL_DIR}/scripts/two.py`."


def test_stops_at_bounds_when_body_has_many_steps() -> None:
    long_title = "x" * (MAX_STEP_TITLE_CHARS + 20)
    body = "".join(f"{n}. {long_title} `/s{n}` `make t{n}`\n" for n in range(1, MAX_STEPS + 6))

    structure = derive_structure(body, agents=AGENTS, skills=SKILLS)
    found = references(body, agents=AGENTS, skills=SKILLS)

    assert len(structure.steps) == MAX_STEPS
    assert structure.truncated
    assert all(len(step.title) <= MAX_STEP_TITLE_CHARS for step in structure.steps)
    assert len(structure.commands) == MAX_REFERENCES
    assert len(found.unresolved) == MAX_REFERENCES
