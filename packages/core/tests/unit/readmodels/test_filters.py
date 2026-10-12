from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent_hub.core.readmodels.filters import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    ApprovalFilter,
    LearningFilter,
    RunFilter,
    Scope,
    SessionFilter,
)
from agent_hub.core.readmodels.page import MAX_CURSOR_CHARS


def test_applies_defaults_when_session_filter_empty() -> None:
    session_filter = SessionFilter()

    assert session_filter.limit == DEFAULT_PAGE_LIMIT == 50
    assert session_filter.sort == "-started_at"
    assert session_filter.cursor is None


def test_keeps_scope_when_project_given() -> None:
    assert Scope(project="demo").project == "demo"


@pytest.mark.parametrize("filter_type", [SessionFilter, RunFilter, ApprovalFilter, LearningFilter])
@pytest.mark.parametrize("limit", [0, MAX_PAGE_LIMIT + 1])
def test_rejects_limit_when_out_of_range(filter_type: type[Scope], limit: int) -> None:
    with pytest.raises(ValidationError, match="limit"):
        filter_type.model_validate({"limit": limit})


def test_rejects_cursor_when_longer_than_bound() -> None:
    with pytest.raises(ValidationError, match="cursor"):
        SessionFilter(cursor="c" * (MAX_CURSOR_CHARS + 1))


def test_rejects_cost_range_when_min_above_max() -> None:
    with pytest.raises(ValidationError, match="cost_min"):
        SessionFilter(cost_min=Decimal(2), cost_max=Decimal(1))


def test_rejects_cost_when_negative() -> None:
    with pytest.raises(ValidationError, match="cost_min"):
        SessionFilter(cost_min=Decimal(-1))


def test_rejects_time_range_when_start_after_end() -> None:
    with pytest.raises(ValidationError, match="started_from"):
        SessionFilter(
            started_from=datetime(2026, 10, 2, tzinfo=UTC),
            started_to=datetime(2026, 10, 1, tzinfo=UTC),
        )


def test_rejects_sort_when_key_unknown() -> None:
    with pytest.raises(ValidationError, match="sort"):
        SessionFilter.model_validate({"sort": "name"})


def test_rejects_run_stage_when_unknown() -> None:
    with pytest.raises(ValidationError, match="stage"):
        RunFilter.model_validate({"stage": "DEPLOYING"})


def test_applies_open_status_when_approval_filter_empty() -> None:
    assert ApprovalFilter().status == "open"


def test_rejects_learning_status_when_unknown() -> None:
    with pytest.raises(ValidationError, match="status"):
        LearningFilter.model_validate({"status": "snoozed"})


def test_rejects_approval_kind_when_unknown() -> None:
    with pytest.raises(ValidationError, match="kind"):
        ApprovalFilter.model_validate({"kind": "deploy"})
