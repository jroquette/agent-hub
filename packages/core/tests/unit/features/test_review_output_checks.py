"""The review file name rule (AGH-139 E11), shared by the review check and the round listing."""

import pytest

from agent_hub.core.features.review_output_checks import is_review_round


@pytest.mark.parametrize(
    "name", ["spec-r1.json", "quality-r12.json", "ux-r1.json", "overengineering-r3.json"]
)
def test_names_a_round_when_file_name_follows_review_rule(name: str) -> None:
    assert is_review_round(name)


@pytest.mark.parametrize(
    "name",
    [
        "spec-r01.json",
        "lint-r1.json",
        "ux-r01.json",
        "over-engineering-r1.json",
        "spec-r1.md",
        "spec-r1.json.bak",
        "spec-r1\n.json",
    ],
)
def test_names_no_round_when_file_name_breaks_review_rule(name: str) -> None:
    assert not is_review_round(name)
