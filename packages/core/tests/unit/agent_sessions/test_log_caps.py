from agent_hub.core.agent_sessions.limits import KIB, SessionLimits
from agent_hub.core.agent_sessions.log_caps import Admitted, Full, LogBudget, Truncated
from agent_hub.core.agent_sessions.record_text import text_bytes
from agent_hub.core.testing.read_model_builders import a_log_record

SMALL = SessionLimits(log_records=100, log_bytes=64 * KIB, headroom=16)


def test_admits_record_when_under_caps() -> None:
    budget = LogBudget(SMALL)
    record = a_log_record("text", 1)

    admission = budget.admit(record)

    assert admission == Admitted(
        record=record.model_copy(update={"text_bytes": text_bytes(record.body)})
    )
    assert (budget.records, budget.stored_bytes) == (1, text_bytes(record.body))


def test_truncates_tool_result_when_over_limit() -> None:
    budget = LogBudget(SessionLimits(tool_result_bytes=64 * KIB))
    content = "é" * (40 * KIB)
    record = a_log_record(
        "tool.result", body={"tool_use_id": "toolu_01", "content": content, "is_error": False}
    )

    admission = budget.admit(record)

    assert isinstance(admission, Truncated)
    body = admission.record.body
    assert body["truncated"] is True
    assert body["original_bytes"] == len(content.encode())
    clipped = body["content"]
    assert isinstance(clipped, str)
    assert len(clipped.encode()) <= 64 * KIB
    assert admission.record.text_bytes == text_bytes(body)


def test_truncates_structured_content_when_over_limit() -> None:
    budget = LogBudget(SessionLimits(tool_result_bytes=1024))
    content = [{"type": "text", "text": "y" * 4000}]
    record = a_log_record(
        "tool.result", body={"tool_use_id": "toolu_01", "content": content, "is_error": False}
    )

    admission = budget.admit(record)

    assert isinstance(admission, Truncated)
    clipped = admission.record.body["content"]
    assert isinstance(clipped, str)
    assert len(clipped.encode()) <= 1024


def test_reports_full_when_records_reach_cap() -> None:
    budget = LogBudget(SMALL)
    for seq in range(1, 85):
        assert isinstance(budget.admit(a_log_record("text", seq)), Admitted)

    assert budget.admit(a_log_record("text", 85)) == Full(cap="records", limit=100)
    assert budget.full
    assert isinstance(budget.admit(a_log_record("text", 85)), Full)
    for seq in range(85, 101):
        assert isinstance(budget.admit(a_log_record("close", seq), reserved=True), Admitted)
    assert isinstance(budget.admit(a_log_record("close", 101), reserved=True), Full)


def test_reports_full_when_bytes_reach_cap() -> None:
    budget = LogBudget(SMALL)
    big = a_log_record("text", 1, body={"block": 0, "text": "z" * (40 * KIB)})
    assert isinstance(budget.admit(big), Admitted)

    second = big.model_copy(update={"seq": 2})

    assert budget.admit(second) == Full(cap="bytes", limit=64 * KIB)
    assert isinstance(budget.admit(a_log_record("exited", 2), reserved=True), Admitted)


def test_resumes_counts_when_built_from_stored_totals() -> None:
    budget = LogBudget(SMALL, records=84, stored_bytes=10)

    assert isinstance(budget.admit(a_log_record("text", 85)), Full)
