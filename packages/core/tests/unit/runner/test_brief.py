import ast
import inspect
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_hub.core.runner import brief
from agent_hub.core.runner.brief import (
    BRIEF_SECTIONS,
    PLACEHOLDERS,
    check_brief,
    missing_brief_reason,
)
from agent_hub.core.testing.builders import a_brief


class TestSections:
    def test_lists_six_sections_in_order_when_constant_read(self) -> None:
        assert BRIEF_SECTIONS == (
            "Problem",
            "Why",
            "Why now",
            "Outcome",
            "Invariants",
            "Acceptance criteria",
        )

    def test_lists_four_placeholders_when_constant_read(self) -> None:
        assert PLACEHOLDERS == ("TBD", "N/A", "-", "TODO")

    def test_imports_only_stdlib_when_module_parsed(self) -> None:
        tree = ast.parse(inspect.getsource(brief))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, "relative import"
                imported.append(node.module or "")

        assert imported
        assert [
            name for name in imported if name.split(".")[0] not in sys.stdlib_module_names
        ] == []


class TestEmpty:
    @pytest.mark.parametrize(
        "description", ["", "  \n\t\n", "Just fix it.\n"], ids=["empty", "blank", "prose"]
    )
    def test_returns_all_sections_when_description_has_no_heading(self, description: str) -> None:
        assert check_brief(description) == BRIEF_SECTIONS

    def test_returns_nothing_when_brief_full(self) -> None:
        assert check_brief(a_brief()) == ()


VARIED_BRIEF = (
    "# problem\nSynthetic problem.\n"
    "#### why :\nSynthetic why.\n"
    "###### WHY NOW:\nSynthetic why now.\n"
    "## Outcome\nSynthetic outcome.\n"
    "## Invariants\nSynthetic invariants.\n"
    "##   Acceptance Criteria  \nSynthetic acceptance criteria.\n"
)


class TestHeadingVariants:
    @pytest.mark.parametrize(
        "description",
        [
            VARIED_BRIEF,
            a_brief().replace("## Problem", "#\tProblem"),
            a_brief().replace("\n", "\r\n"),
        ],
        ids=["case_level_and_colon", "tab_separator", "crlf"],
    )
    def test_returns_nothing_when_headings_vary_in_case_level_and_colon(
        self, description: str
    ) -> None:
        assert check_brief(description) == ()

    @pytest.mark.parametrize(
        "heading",
        ["#Problem", "####### Problem", "## Problem ##", "## Problems"],
        ids=["no_space", "seven_hashes", "closing_sequence", "plural"],
    )
    def test_misses_problem_when_heading_malformed(self, heading: str) -> None:
        description = a_brief().replace("## Problem", heading)

        assert check_brief(description) == ("Problem",)


def snake(name: str) -> str:
    return name.lower().replace(" ", "_")


class TestPlaceholders:
    @pytest.mark.parametrize(
        ("name", "body"),
        [
            *(
                ("Why now", body)
                for body in ("", "   ", "TBD", "n/a", "-", "todo", " TBD ", "\nTBD\n\n")
            ),
            *((name, "TBD") for name in BRIEF_SECTIONS if name != "Why now"),
        ],
    )
    def test_misses_only_that_section_when_body_is_placeholder(self, name: str, body: str) -> None:
        assert check_brief(a_brief(**{snake(name): body})) == (name,)

    def test_keeps_section_when_placeholder_starts_a_sentence(self) -> None:
        assert check_brief(a_brief(why="TBD by Friday")) == ()

    def test_keeps_section_when_placeholder_repeats(self) -> None:
        assert check_brief(a_brief(why="TBD\nTBD")) == ()

    def test_keeps_section_when_placeholder_is_a_bullet(self) -> None:
        assert check_brief(a_brief(why="- TBD")) == ()


class TestOrderAndExtras:
    def test_returns_nothing_when_sections_reversed_with_extras(self) -> None:
        sections = a_brief().split("## ")[1:]
        description = (
            "## Notes\nSome notes.\n"
            + "".join(f"## {section}" for section in reversed(sections))
            + "## Links\n- https://example.com\n"
        )

        assert check_brief(description) == ()


class TestDuplicates:
    def test_keeps_section_when_any_duplicate_has_text(self) -> None:
        assert check_brief(a_brief(why="") + "## Why\nBecause it is synthetic.\n") == ()

    @pytest.mark.parametrize("second", ["", "TBD"], ids=["both_empty", "empty_then_placeholder"])
    def test_misses_section_when_every_duplicate_is_empty(self, second: str) -> None:
        assert check_brief(a_brief(why="") + f"## Why\n{second}\n") == ("Why",)


WITHOUT_INVARIANTS_AND_OUTCOME = a_brief(omit=("Invariants", "Outcome"))
HEADINGS = "## Invariants\nSynthetic invariants.\n## Outcome\nSynthetic outcome.\n"


class TestCodeBlocks:
    @pytest.mark.parametrize(
        "code",
        [
            f"```\n{HEADINGS}```\n",
            f"~~~\n{HEADINGS}~~~\n",
            f"```md\n{HEADINGS}",
            "".join(f"    {line}\n" for line in HEADINGS.splitlines()),
            f"~~~\n{HEADINGS}```\n",
            f"````\n{HEADINGS}```\n",
        ],
        ids=[
            "backticks",
            "tildes",
            "unclosed",
            "indented",
            "tilde_fence_not_closed_by_backticks",
            "shorter_closing_fence",
        ],
    )
    def test_misses_sections_when_headings_only_in_code(self, code: str) -> None:
        assert check_brief(WITHOUT_INVARIANTS_AND_OUTCOME + code) == ("Outcome", "Invariants")

    def test_counts_heading_when_after_closed_fence(self) -> None:
        description = WITHOUT_INVARIANTS_AND_OUTCOME + f"  ~~~~\n# x\n  ~~~~~ \n{HEADINGS}"

        assert check_brief(description) == ()

    def test_counts_headings_when_backtick_run_is_an_inline_code_span(self) -> None:
        assert check_brief("```x``` is a code span\n" + a_brief()) == ()

    def test_misses_sections_when_tilde_fence_info_string_holds_a_backtick(self) -> None:
        description = WITHOUT_INVARIANTS_AND_OUTCOME + f"~~~ a`b\n{HEADINGS}"

        assert check_brief(description) == ("Outcome", "Invariants")

    def test_keeps_section_when_body_is_only_a_code_block(self) -> None:
        assert check_brief(a_brief(invariants="```\n## Why\n```")) == ()


class TestBodies:
    @pytest.mark.parametrize(
        "body", ["### PR 1\n- the first slice", "### PR 1"], ids=["with_bullet", "alone"]
    )
    def test_keeps_section_when_body_is_only_subsections(self, body: str) -> None:
        assert check_brief(a_brief(acceptance_criteria=body)) == ()

    def test_misses_section_when_next_heading_follows_directly(self) -> None:
        description = a_brief(omit=("Problem", "Why")) + "## Problem\n## Why\nSynthetic why.\n"

        assert check_brief(description) == ("Problem",)

    def test_closes_section_when_higher_level_heading_follows(self) -> None:
        description = a_brief(omit=("Why",)) + "### Why\n# Notes\nSynthetic notes.\n"

        assert check_brief(description) == ("Why",)

    def test_counts_nested_canonical_heading_when_inside_another_section(self) -> None:
        description = a_brief(omit=("Problem", "Why")) + (
            "# Problem\nSynthetic problem.\n## Why\nSynthetic why.\n"
        )

        assert check_brief(description) == ()

    def test_keeps_section_when_subheading_names_a_placeholder(self) -> None:
        assert check_brief(a_brief(problem="### TBD")) == ()


MIB = 1024 * 1024
MAX_OPEN_SECTIONS = 6
TYPICAL_LINE = "x" * 59 + "\n"
SIX_OPEN_SECTIONS = (
    "# Problem\n## Why\n### Why now\n#### Outcome\n##### Invariants\n###### Acceptance criteria\n"
)


class TestHostileText:
    @pytest.mark.parametrize(
        "description",
        ["\x00## Problem\ud800", "## Problem\x00\nText.\n", "\ud800\udfff\n## \ud800\n\x00"],
        ids=["nul_in_heading", "nul_after_heading", "lone_surrogates"],
    )
    def test_returns_all_sections_when_text_holds_nul_and_surrogates(
        self, description: str
    ) -> None:
        assert check_brief(description) == BRIEF_SECTIONS

    @pytest.mark.parametrize(
        ("description", "expected"),
        [
            (TYPICAL_LINE * (MIB // len(TYPICAL_LINE)) + a_brief(), ()),
            ("#\n" * (MIB // 2) + a_brief(), ()),
            (SIX_OPEN_SECTIONS + TYPICAL_LINE * (MIB // len(TYPICAL_LINE)), ()),
        ],
        ids=["typical", "every_line_a_heading", "six_open_sections"],
    )
    def test_reads_each_line_at_most_six_times_when_description_is_large(
        self, monkeypatch: pytest.MonkeyPatch, description: str, expected: tuple[str, ...]
    ) -> None:
        reads = 0
        read = brief._OpenSection.read

        def counting_read(section: brief._OpenSection, line: str) -> None:
            nonlocal reads
            reads += 1
            read(section, line)

        monkeypatch.setattr(brief._OpenSection, "read", counting_read)

        missing = check_brief(description)

        assert missing == expected
        assert reads <= MAX_OPEN_SECTIONS * len(description.splitlines())


class TestReason:
    def test_names_missing_sections_when_reason_built(self) -> None:
        reason = missing_brief_reason("DEM-1", ("Why now", "Acceptance criteria"))

        assert reason == (
            "DEM-1 brief is missing: Why now, Acceptance criteria"
            " (add these headings to the issue description)"
        )


UNFENCED_FRAGMENTS = (
    "",
    "TBD",
    "- n/a",
    "## Problem",
    "# why",
    "###### WHY NOW:",
    "### Outcome",
    "    ## Invariants",
    "## Acceptance criteria ##",
    "#",
)
FRAGMENTS = (*UNFENCED_FRAGMENTS, "```", "~~~~", "    ```")


def markdown_lines(
    fragments: tuple[str, ...], alphabet: st.SearchStrategy[str]
) -> st.SearchStrategy[str]:
    """Text built from lines: brief-like fragments mixed with arbitrary text."""
    line = st.one_of(st.sampled_from(fragments), st.text(alphabet=alphabet, max_size=40))
    return st.lists(line, max_size=30).map("\n".join)


NO_FENCE = st.characters(exclude_characters="`~")


class TestProperties:
    @settings(max_examples=200, deadline=None)
    @given(text=st.one_of(st.text(max_size=500), markdown_lines(FRAGMENTS, st.characters())))
    def test_returns_ordered_subsequence_when_any_text_checked_property(self, text: str) -> None:
        missing = check_brief(text)

        assert missing == tuple(name for name in BRIEF_SECTIONS if name in missing)
        assert len(set(missing)) == len(missing)
        assert check_brief(text) == missing

    @settings(max_examples=200, deadline=None)
    @given(
        text=st.one_of(
            st.text(alphabet=NO_FENCE, max_size=500),
            markdown_lines(UNFENCED_FRAGMENTS, NO_FENCE),
        )
    )
    def test_returns_nothing_when_full_brief_appended_property(self, text: str) -> None:
        assert check_brief(text + "\n" + a_brief()) == ()
