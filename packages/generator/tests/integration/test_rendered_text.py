"""The rendered text of configured hubs, against their checked-in copies (AGH-56 E2, AGH-57 E3).

Each case's files are stored byte for byte under ``rendered/<case>/<path>.golden`` (``-text`` in
``.gitattributes``; the suffix keeps an agent from reading a nested ``AGENTS.md`` as its own
instructions): ``two_teams`` a hub with two tracker teams, ``conventions`` the mixed conventions
hub. ``GOLDEN_UPDATE=1`` rewrites them, refused under ``CI``: review the diff and commit it. A
one-team, unconfigured hub's bytes stay pinned by the sha constants of ``test_render_hub.py`` and
the ``hub init`` lock.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_conventions_document, a_two_team_document
from agent_hub.generator.render_hub import render_hub

RENDERED_ROOT = Path(__file__).resolve().parent / "rendered"
TEXT_SUFFIX = ".golden"


class TextCase(NamedTuple):
    """A configured hub: its folder under ``rendered/``, its builder and the files it pins."""

    folder: str
    document: Callable[[], dict[str, Any]]
    paths: tuple[str, ...]


CASES = (
    # The rendered files whose text names the tracker teams.
    TextCase(
        "two_teams",
        a_two_team_document,
        (
            "AGENTS.md",
            "plugin/hub-workflow/agents/planner.md",
            "plugin/hub-workflow/agents/requirements-analyst.md",
            "plugin/hub-workflow/skills/feature/SKILL.md",
        ),
    ),
    # The rendered files whose text shows the conventions.
    TextCase(
        "conventions",
        a_conventions_document,
        (
            "AGENTS.md",
            "plugin/hub-workflow/skills/fix/SKILL.md",
            "plugin/hub-workflow/skills/kickoff/SKILL.md",
        ),
    ),
)
CASE_PATHS = [
    pytest.param(case, path, id=f"{case.folder}-{path}") for case in CASES for path in case.paths
]


@pytest.mark.parametrize(("case", "path"), CASE_PATHS)
def test_matches_checked_in_text_when_hub_rendered(case: TextCase, path: str, golden: Any) -> None:
    rendered = {
        file.path: file.content
        for file in render_hub(HubConfig.model_validate(case.document())).files
    }
    actual = rendered[path]
    assert actual is not None, path
    expected_file = RENDERED_ROOT / case.folder / f"{path}{TEXT_SUFFIX}"

    if golden.update_mode():
        expected_file.parent.mkdir(parents=True, exist_ok=True)
        expected_file.write_bytes(actual)
    if not expected_file.is_file():
        pytest.fail(f"{expected_file} is missing; write it with GOLDEN_UPDATE=1 and review it")

    assert actual == expected_file.read_bytes(), f"{path}: rerun with GOLDEN_UPDATE=1 and review"


@pytest.mark.parametrize("case", CASES, ids=[case.folder for case in CASES])
def test_holds_only_rendered_paths_when_text_folder_listed(case: TextCase) -> None:
    root = RENDERED_ROOT / case.folder
    held = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())

    assert held == sorted(f"{path}{TEXT_SUFFIX}" for path in case.paths)
