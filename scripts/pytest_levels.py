"""Pytest plugin: the folder a test lives in decides its level marker (ADR 0005).

The level is the path segment right after the last ``tests`` segment, so a ``unit`` directory
elsewhere in the path (for example above the repo) never counts. Unit and contract tests also
get pytest-socket's ``disable_socket`` marker, so they cannot reach the network.

Tests marked ``live`` call a real external API. This plugin is their only gate: each one is
skipped, naming the first missing variable (never a value), unless ``LINEAR_API_KEY``,
``AGENT_HUB_LIVE_ISSUE`` and ``AGENT_HUB_LIVE_LABEL`` are set and ``AGENT_HUB_LIVE`` is ``1``.
"""

import os
from collections.abc import Mapping
from pathlib import PurePath

import pytest

LEVELS = frozenset({"unit", "contract", "integration", "e2e"})
NETWORK_BLOCKED_LEVELS = frozenset({"unit", "contract"})
LIVE_MARKER = "live"
LIVE_SWITCH = "AGENT_HUB_LIVE"
# Checked in this order; the skip reason names the first one missing.
LIVE_VARIABLES = ("LINEAR_API_KEY", LIVE_SWITCH, "AGENT_HUB_LIVE_ISSUE", "AGENT_HUB_LIVE_LABEL")


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


def live_skip_reason(environ: Mapping[str, str]) -> str | None:
    """Why a ``live`` test cannot run under ``environ``, or None when it can."""
    for name in LIVE_VARIABLES:
        value = environ.get(name, "")
        if name == LIVE_SWITCH and value != "1":
            return f"live test: set {name}=1 to call the real API"
        if not value:
            return f"live test: {name} is not set"
    return None


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Add the level marker, socket blocking for unit/contract, and the live gate."""
    for item in items:
        if item.get_closest_marker(LIVE_MARKER) is not None:
            reason = live_skip_reason(os.environ)
            if reason is not None:
                item.add_marker(pytest.mark.skip(reason=reason))
        level = level_of(str(item.path))
        if level is None:
            continue
        item.add_marker(getattr(pytest.mark, level))
        if level in NETWORK_BLOCKED_LEVELS:
            item.add_marker(pytest.mark.disable_socket)
