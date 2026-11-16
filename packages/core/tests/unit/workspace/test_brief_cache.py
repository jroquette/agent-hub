import json

import pytest

from agent_hub.core.workspace.brief_cache import brief_cache_document

# A brief with what JSON must escape (quotes, a backslash, newlines) and non-ASCII text.
BRIEF = (
    '# Brief\n## Repos\n- api: trunk, 2 changed file(s)\n  ⚠ failing on trunk: "lint" \\ build\n'
)


@pytest.mark.parametrize("made_at", [1768478400.0, 1768478400.25])
def test_round_trips_brief_when_document_built(made_at: float) -> None:
    document = json.loads(brief_cache_document(BRIEF, made_at=made_at).decode("utf-8"))

    assert document == {"made_at": made_at, "brief": BRIEF}
