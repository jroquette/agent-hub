import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_hub.core.brain.frontmatter import split_frontmatter
from agent_hub.core.skills.skill_frontmatter import (
    MAX_SKILL_FRONTMATTER_LINES,
    read_skill_document,
)
from agent_hub.core.skills.skill_view import KNOWN_SKILL_KEYS, SkillFrontmatterValue


def _doc(*lines: str, body: str = "# Body\n") -> str:
    return "---\n" + "".join(f"{line}\n" for line in lines) + "---\n" + body


def _values(text: str) -> dict[str, SkillFrontmatterValue]:
    document = read_skill_document(text)
    assert document.problem is None, document.problem
    return {pair.key: pair.value for pair in document.pairs}


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (">", "Plans a feature from an idea.\nKeep it short.\n"),
        (">-", "Plans a feature from an idea.\nKeep it short."),
        (">+", "Plans a feature from an idea.\nKeep it short.\n\n"),
    ],
)
def test_folds_description_when_folded_block_scalar(header: str, expected: str) -> None:
    text = _doc(
        f"description: {header}",
        "  Plans a feature",
        "  from an idea.",
        "",
        "  Keep it short.",
        "",
        "name: plan",
    )

    values = _values(text)

    assert values["description"] == expected
    assert values["name"] == "plan"


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("| # c", "kept\n"),
        (">- # c", "kept"),
        ("|\t# c", "kept\n"),
        (">" + " " * 4000 + "# c", "kept\n"),
    ],
)
def test_drops_comment_when_block_scalar_header_has_one(header: str, expected: str) -> None:
    assert _values(_doc(f"description: {header}", "  kept"))["description"] == expected


def test_keeps_more_indented_lines_when_folded_block_scalar() -> None:
    text = _doc("description: >", "  One", "    indented", "  two")

    assert _values(text)["description"] == "One\n  indented\ntwo\n"


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("|", "line one\n  line two\n\nline three\n"),
        ("|-", "line one\n  line two\n\nline three"),
        ("|+", "line one\n  line two\n\nline three\n\n"),
    ],
)
def test_keeps_newlines_when_literal_block_scalar(header: str, expected: str) -> None:
    text = _doc(
        f"when_to_use: {header}",
        "  line one",
        "    line two",
        "",
        "  line three",
        "",
    )

    assert _values(text)["when_to_use"] == expected


def test_joins_lines_when_plain_scalar_continues() -> None:
    text = _doc(
        "description: Reviews a change",
        "  against its spec",
        "",
        "  and reports.",
        "model: sonnet",
    )

    values = _values(text)

    assert values["description"] == "Reviews a change against its spec\nand reports."
    assert values["model"] == "sonnet"


def test_reads_plain_scalar_when_value_starts_on_next_line() -> None:
    text = _doc("description:", "  Starts below", "  the key.")

    assert _values(text)["description"] == "Starts below the key."


def test_keeps_order_when_pairs_read() -> None:
    text = _doc("name: alpha", "zeta: 1", "description: First.", "allowed-tools: [Read, Grep]")

    document = read_skill_document(text, known_keys=KNOWN_SKILL_KEYS)

    assert [pair.key for pair in document.pairs] == ["name", "zeta", "description", "allowed-tools"]
    assert [pair.known for pair in document.pairs] == [True, False, True, True]
    assert document.pairs[3].value == ("Read", "Grep")
    assert document.body == "# Body\n"


def test_reads_hub_skill_shapes_when_frontmatter_plain() -> None:
    text = _doc(
        "# a comment line",
        "name: feature",
        "description: Turn an idea into a delivered feature (spec, plan, code).",
        'argument-hint: "<idea or tracker issue id>"',
        "tools: Read, Grep",
        "disable-model-invocation: true",
        "skills:",
        "  - plan",
        "  - 'review'",
        "paths:",
        "- src/**",
    )

    values = _values(text)

    assert values == {
        "name": "feature",
        "description": "Turn an idea into a delivered feature (spec, plan, code).",
        "argument-hint": "<idea or tracker issue id>",
        "tools": "Read, Grep",
        "disable-model-invocation": "true",
        "skills": ("plan", "review"),
        "paths": ("src/**",),
    }


def test_accepts_crlf_when_lines_end_with_carriage_return() -> None:
    text = "---\r\nname: alpha\r\ndescription: >-\r\n  Two\r\n  lines\r\n---\r\nBody\r\n"

    document = read_skill_document(text)

    assert document.problem is None
    assert {pair.key: pair.value for pair in document.pairs} == {
        "name": "alpha",
        "description": "Two lines",
    }
    assert document.body == "Body\r\n"


def test_reads_one_level_map_when_metadata_holds_strings() -> None:
    text = _doc("name: alpha", "metadata:", "  author: Someone", '  version: "1.0"', "license: MIT")

    values = _values(text)

    assert values["metadata"] == {"author": "Someone", "version": "1.0"}
    assert values["license"] == "MIT"


def test_gives_whole_text_when_no_frontmatter() -> None:
    document = read_skill_document("# Just a body\n")

    assert document.pairs == ()
    assert document.body == "# Just a body\n"
    assert document.problem is None


UNPARSEABLE = {
    "nested map": _doc("hooks:", "  PreToolUse:", "    matcher: Bash"),
    "map outside metadata": _doc("other:", "  key: value"),
    "metadata nested twice": _doc("metadata:", "  a:", "    b: c"),
    "anchor": _doc("description: &desc Plans things."),
    "alias": _doc("description: *desc"),
    "tag": _doc("description: !!str Plans things."),
    "flow map": _doc("metadata: {author: me}"),
    "indentation indicator": _doc("description: |2", "  text"),
    "tab indent": _doc("skills:", "\t- plan"),
    "unclosed": "---\nname: alpha\n# Body\n",
    "too long": _doc(*[f"key{n}: v" for n in range(MAX_SKILL_FRONTMATTER_LINES + 1)]),
    "not a field": _doc("just words"),
    "repeated key": _doc("name: a", "name: b"),
    "unclosed quote": _doc('description: "open'),
    "map in a list": _doc("skills:", "  - name: plan"),
}


@pytest.mark.parametrize("text", UNPARSEABLE.values(), ids=UNPARSEABLE.keys())
def test_reports_unparseable_when_construct_unsupported(text: str) -> None:
    document = read_skill_document(text)

    assert document.problem
    assert "\n" not in document.problem
    assert document.pairs == ()
    assert document.body == text


_KEYS = st.from_regex(r"[a-z][a-z0-9_-]{0,11}", fullmatch=True)
_WORDS = st.from_regex(r"[A-Za-z0-9][A-Za-z0-9 ,.()/<>-]{0,30}[A-Za-z0-9.)]", fullmatch=True)
_VALUES = st.one_of(
    _WORDS.map(lambda word: (word, word)),
    _WORDS.map(lambda word: (f'"{word}"', word)),
    st.lists(st.from_regex(r"[A-Za-z0-9_-]{1,8}", fullmatch=True), max_size=4).map(
        lambda items: (f"[{', '.join(items)}]", tuple(items))
    ),
    st.lists(st.from_regex(r"[A-Za-z0-9_-]{1,8}", fullmatch=True), min_size=1, max_size=4).map(
        lambda items: ("\n" + "".join(f"  - {item}\n" for item in items), tuple(items))
    ),
)


@settings(max_examples=200, deadline=None)
@given(
    fields=st.dictionaries(_KEYS, _VALUES, max_size=8),
    comment=st.sampled_from(["", "# note"]),
)
def test_matches_brain_reader_when_text_in_brain_subset_property(
    fields: dict[str, tuple[str, SkillFrontmatterValue]], comment: str
) -> None:
    lines = [comment] if comment else []
    for key, (written, _) in fields.items():
        lines.append(
            f"{key}:{written}".rstrip("\n") if written.startswith("\n") else f"{key}: {written}"
        )
    text = _doc(*lines)

    brain = split_frontmatter(text)
    document = read_skill_document(text)

    assert brain.problem is None
    assert document.problem is None
    assert document.body == brain.body
    read = {pair.key: pair.value for pair in document.pairs}
    assert read == {
        key: tuple(value) if isinstance(value, list) else value
        for key, value in brain.fields.items()
    }
    assert read == {key: expected for key, (_, expected) in fields.items()}
