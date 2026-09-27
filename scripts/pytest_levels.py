"""Pytest plugin: the folder a test lives in decides its level marker (ADR 0005).

The level is the path segment right after the last ``tests`` segment, so a ``unit`` directory
elsewhere in the path (for example above the repo) never counts. Unit and contract tests also
get pytest-socket's ``disable_socket`` marker, so they cannot reach the network.
"""

from pathlib import PurePath

import pytest

LEVELS = frozenset({"unit", "contract", "integration", "e2e"})
NETWORK_BLOCKED_LEVELS = frozenset({"unit", "contract"})


def level_of(path: str) -> str | None:
    """Return the test level encoded in ``path``, or None when it is not under a level folder."""
    parts = PurePath(path.replace("\\", "/")).parts
    tests_indexes = [index for index, part in enumerate(parts) if part == "tests"]
    if not tests_indexes:
        return None
    level_index = tests_indexes[-1] + 1
    if level_index >= len(parts) or parts[level_index] not in LEVELS:
        return None
    return parts[level_index]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Add the level marker, and socket blocking for unit/contract, to every collected test."""
    for item in items:
        level = level_of(str(item.path))
        if level is None:
            continue
        item.add_marker(getattr(pytest.mark, level))
        if level in NETWORK_BLOCKED_LEVELS:
            item.add_marker(pytest.mark.disable_socket)
