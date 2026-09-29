import pytest

from agent_hub.core.hub_files.tree_snapshot import TEMP_NAME, is_leftover_name, temp_name


@pytest.mark.parametrize("name", [".Makefile.hub-tmp-0a1b2c3d", ".x.hub-tmp-ffffffff"])
def test_matches_leftover_when_name_has_temp_shape(name: str) -> None:
    assert is_leftover_name(name)
    assert TEMP_NAME.fullmatch(name)


@pytest.mark.parametrize(
    "name",
    [
        pytest.param(".x.hub-tmp-0a1b2c3", id="seven-hex"),
        pytest.param(".x.hub-tmp-0a1b2c3d4", id="nine-hex"),
        pytest.param(".x.hub-tmp-0A1B2C3D", id="uppercase"),
        pytest.param("x.hub-tmp-0a1b2c3d", id="no-leading-dot"),
        pytest.param(".hub-tmp-0a1b2c3d", id="empty-name"),
        pytest.param(".x.hub-tmp-0a1b2c3d.bak", id="suffix-after-hex"),
    ],
)
def test_rejects_name_when_shape_differs(name: str) -> None:
    assert not is_leftover_name(name)


def test_builds_temp_name_when_token_given() -> None:
    name = temp_name("Makefile", "0a1b2c3d")

    assert name == ".Makefile.hub-tmp-0a1b2c3d"
    assert is_leftover_name(name)


@pytest.mark.parametrize("token", ["0a1b2c3", "0a1b2c3d4", "0A1B2C3D", "0a1b2c3g", ""])
def test_rejects_token_when_not_eight_hex(token: str) -> None:
    with pytest.raises(ValueError, match="8 lowercase hex"):
        temp_name("Makefile", token)
