"""The rendered text of a hub with two tracker teams, against its checked-in copies (AGH-56 E2).

Each file is stored byte for byte under ``rendered/two_teams/<path>.golden`` (``-text`` in
``.gitattributes``; the suffix keeps an agent from reading a nested ``AGENTS.md`` as its own
instructions). ``GOLDEN_UPDATE=1`` rewrites them, refused under ``CI``: review the diff and commit
it. A one-team hub's bytes stay pinned by the sha constants of ``test_render_hub.py`` and the
``hub init`` lock.
"""

from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_two_team_document
from agent_hub.generator.render_hub import render_hub

TEXT_ROOT = Path(__file__).resolve().parent / "rendered" / "two_teams"
TEXT_SUFFIX = ".golden"
# The rendered files whose text names the tracker teams.
TEAM_TEXT_PATHS = (
    "AGENTS.md",
    "plugin/hub-workflow/agents/planner.md",
    "plugin/hub-workflow/agents/requirements-analyst.md",
    "plugin/hub-workflow/skills/feature/SKILL.md",
)


@pytest.mark.parametrize("path", TEAM_TEXT_PATHS)
def test_matches_checked_in_text_when_two_team_hub_rendered(path: str, golden: Any) -> None:
    rendered = {
        file.path: file.content
        for file in render_hub(HubConfig.model_validate(a_two_team_document())).files
    }
    actual = rendered[path]
    assert actual is not None, path
    expected_file = TEXT_ROOT / f"{path}{TEXT_SUFFIX}"

    if golden.update_mode():
        expected_file.parent.mkdir(parents=True, exist_ok=True)
        expected_file.write_bytes(actual)
    if not expected_file.is_file():
        pytest.fail(f"{expected_file} is missing; write it with GOLDEN_UPDATE=1 and review it")

    assert actual == expected_file.read_bytes(), f"{path}: rerun with GOLDEN_UPDATE=1 and review"


def test_holds_only_rendered_paths_when_text_folder_listed() -> None:
    held = sorted(
        path.relative_to(TEXT_ROOT).as_posix() for path in TEXT_ROOT.rglob("*") if path.is_file()
    )

    assert held == sorted(f"{path}{TEXT_SUFFIX}" for path in TEAM_TEXT_PATHS)
