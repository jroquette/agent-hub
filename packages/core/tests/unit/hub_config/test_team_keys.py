import pytest

from agent_hub.core.hub_config.team_keys import team_of, team_segment, teams_text


@pytest.mark.parametrize(
    ("identifier", "teams", "expected"),
    [
        ("OPS-12", ("APP", "OPS"), "OPS"),
        ("ops-12-x", ("APP", "OPS"), "OPS"),
        ("APP-1", ("app",), "app"),
    ],
)
def test_finds_configured_key_when_identifier_segment_matches(
    identifier: str, teams: tuple[str, ...], expected: str
) -> None:
    assert team_of(identifier, teams) == expected


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [("APX-1", None), ("AP-1", "AP"), ("APP-1", "APP"), ("OPS", None)],
)
def test_finds_nothing_when_segment_only_shares_prefix(
    identifier: str, expected: str | None
) -> None:
    assert team_of(identifier, ("AP", "APP", "OPS")) == expected


def test_joins_keys_in_order_when_teams_listed() -> None:
    assert teams_text(("OPS", "APP")) == "OPS, APP"
    assert teams_text(("DEM",)) == "DEM"


def test_writes_segment_when_one_or_several_teams() -> None:
    assert team_segment(("DEM",)) == "dem"
    assert team_segment(("APP", "OPS")) == "<app|ops>"


@pytest.mark.parametrize("identifier", ["KEY-1", "Key-1-x"])
def test_finds_nothing_when_segment_not_ascii(identifier: str) -> None:
    # The Kelvin sign lowercases to ASCII ``k``; a non-ASCII segment still matches no key.
    assert team_of(identifier, ("KEY",)) is None
