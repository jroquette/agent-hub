import socket

import pytest
import pytest_socket

from scripts.pytest_levels import level_of


@pytest.mark.parametrize(
    ("path", "level"),
    [
        ("packages/core/tests/unit/x/test_a.py", "unit"),
        ("packages/storage/tests/integration/test_m.py", "integration"),
        ("tests/e2e/test_hub_cli.py", "e2e"),
        ("packages/core/tests/contract/test_c.py", "contract"),
    ],
)
def test_returns_level_when_path_is_under_tests_level_folder(path: str, level: str) -> None:
    assert level_of(path) == level


def test_returns_none_when_level_folder_is_outside_tests() -> None:
    assert level_of("/home/unit/repo/packages/core/tests/test_a.py") is None


# pytest-socket warns before raising; the raise is what this test checks.
@pytest.mark.filterwarnings("ignore:A test tried to use socket.socket")
def test_blocks_socket_when_test_is_unit_level() -> None:
    with pytest.raises(pytest_socket.SocketBlockedError):
        socket.socket()
