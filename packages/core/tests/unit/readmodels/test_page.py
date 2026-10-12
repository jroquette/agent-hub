import json

import pytest
from pydantic import ValidationError

from agent_hub.core.readmodels.page import MAX_CURSOR_CHARS, Page
from agent_hub.core.sessions.session import Session
from agent_hub.core.testing.read_model_builders import a_session


def test_serializes_items_cursor_and_estimate_when_page_dumped() -> None:
    page = Page[Session](items=(a_session(),), next_cursor="abc", total_estimate=120)

    document = json.loads(page.model_dump_json())

    assert [item["id"] for item in document["items"]] == ["session-1"]
    assert (document["next_cursor"], document["total_estimate"]) == ("abc", 120)


def test_builds_empty_page_when_nothing_matches() -> None:
    page = Page[Session].empty()

    assert (page.items, page.next_cursor, page.total_estimate) == ((), None, 0)


def test_rejects_page_when_total_estimate_negative() -> None:
    with pytest.raises(ValidationError, match="total_estimate"):
        Page[Session](items=(), next_cursor=None, total_estimate=-1)


def test_rejects_page_when_cursor_too_long() -> None:
    with pytest.raises(ValidationError, match="next_cursor"):
        Page[Session](items=(), next_cursor="x" * (MAX_CURSOR_CHARS + 1), total_estimate=0)


def test_names_schema_after_item_when_parametrized() -> None:
    assert Page[Session].model_json_schema()["title"] == "Page[Session]"
