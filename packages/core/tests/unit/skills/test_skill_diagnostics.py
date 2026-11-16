import pytest

from agent_hub.core.skills.skill_diagnostics import (
    MAX_BODY_LINES,
    MAX_DESCRIPTION_CHARS,
    context_cost,
    diagnose,
)
from agent_hub.core.skills.skill_frontmatter import read_skill_document
from agent_hub.core.skills.skill_view import (
    KNOWN_AGENT_KEYS,
    KNOWN_SKILL_KEYS,
    SEVERITY,
    ContextCost,
    DiagnosticCode,
    ItemKind,
)


def _doc(*lines: str, body: str = "# Body\n") -> str:
    return "---\n" + "".join(f"{line}\n" for line in lines) + "---\n" + body


_GOOD = ("name: alpha", "description: Checks the alpha flow.")

CASES = {
    "name_invalid": (_doc("name: Bad_Name", _GOOD[1]), "Bad_Name", ()),
    "name_mismatch": (_doc("name: alpha", _GOOD[1]), "other", ()),
    "description_missing": (_doc("name: alpha"), "alpha", ()),
    "description_too_long": (
        _doc("name: alpha", "description: " + "d" * (MAX_DESCRIPTION_CHARS + 1)),
        "alpha",
        (),
    ),
    "body_too_long": (_doc(*_GOOD, body="line\n" * (MAX_BODY_LINES + 1)), "alpha", ()),
    "reference_not_found": (_doc(*_GOOD), "alpha", ("/missing-skill", "ghost")),
    "frontmatter_unparseable": (_doc("name: alpha", "metadata: {a: b}"), "alpha", ()),
    "unknown_key": (_doc(*_GOOD, "colour: blue"), "alpha", ()),
}


@pytest.mark.parametrize(("code", "case"), CASES.items(), ids=CASES.keys())
def test_reports_each_code_when_fixture_breaks_its_rule(
    code: str, case: tuple[str, str, tuple[str, ...]]
) -> None:
    text, file_name, unresolved = case
    document = read_skill_document(text, known_keys=KNOWN_SKILL_KEYS)

    diagnostics = diagnose(
        document,
        kind=ItemKind.SKILL,
        file_name=file_name,
        known_keys=KNOWN_SKILL_KEYS,
        unresolved=unresolved,
    )

    assert [diagnostic.code for diagnostic in diagnostics] == [code] * max(1, len(unresolved))
    for diagnostic in diagnostics:
        assert diagnostic.severity == SEVERITY[code]
        assert diagnostic.message
        assert "\n" not in diagnostic.message
        assert not diagnostic.message.startswith("/")


def test_reports_nothing_when_skill_follows_every_rule() -> None:
    document = read_skill_document(_doc(*_GOOD, "argument-hint: <id>"))

    assert (
        diagnose(
            document,
            kind=ItemKind.SKILL,
            file_name="alpha",
            known_keys=KNOWN_SKILL_KEYS,
            unresolved=(),
        )
        == ()
    )


def test_names_both_references_when_skill_and_agent_unresolved() -> None:
    document = read_skill_document(_doc(*_GOOD))

    messages = [
        diagnostic.message
        for diagnostic in diagnose(
            document,
            kind=ItemKind.SKILL,
            file_name="alpha",
            known_keys=KNOWN_SKILL_KEYS,
            unresolved=("/missing-skill", "ghost"),
        )
    ]

    assert messages == [
        "skill /missing-skill is not in this hub's catalog",
        "agent ghost is not in this hub's catalog",
    ]


def test_checks_agent_keys_when_kind_agent() -> None:
    document = read_skill_document(_doc("name: scout", "description: Looks.", "tools: Read"))

    diagnostics = diagnose(
        document,
        kind=ItemKind.AGENT,
        file_name="scout",
        known_keys=KNOWN_AGENT_KEYS,
        unresolved=(),
    )

    assert diagnostics == ()


def test_reports_only_unparseable_when_frontmatter_unparseable() -> None:
    text = _doc("name: Bad_Name", "colour: &a blue", body="line\n" * (MAX_BODY_LINES + 1))
    document = read_skill_document(text)

    diagnostics = diagnose(
        document,
        kind=ItemKind.SKILL,
        file_name="other",
        known_keys=KNOWN_SKILL_KEYS,
        unresolved=("/missing-skill",),
    )

    assert [diagnostic.code for diagnostic in diagnostics] == [
        DiagnosticCode.FRONTMATTER_UNPARSEABLE
    ]
    assert "anchor" in diagnostics[0].message


@pytest.mark.parametrize(
    ("flag", "kind", "expected"),
    [
        ((), ItemKind.SKILL, ContextCost(always_loaded_tokens=100, on_invoke_tokens=1000)),
        (
            ("disable-model-invocation: true",),
            ItemKind.SKILL,
            ContextCost(always_loaded_tokens=0, on_invoke_tokens=1000),
        ),
        ((), ItemKind.AGENT, ContextCost(always_loaded_tokens=100, on_invoke_tokens=1000)),
    ],
    ids=["context_cost-skill", "context_cost-user-only", "context_cost-agent"],
)
def test_costs_tokens_when_description_and_body_given(
    flag: tuple[str, ...], kind: ItemKind, expected: ContextCost
) -> None:
    document = read_skill_document(
        _doc("name: alpha", "description: " + "d" * 400, *flag, body="b" * 4000)
    )

    assert context_cost(document, kind=kind) == expected


def test_rounds_tokens_up_when_characters_not_multiple_of_four() -> None:
    document = read_skill_document(_doc("name: alpha", "description: abcde", body="xy"))

    cost = context_cost(document, kind=ItemKind.SKILL)

    assert (cost.always_loaded_tokens, cost.on_invoke_tokens) == (2, 1)
    assert cost.approximate is True
