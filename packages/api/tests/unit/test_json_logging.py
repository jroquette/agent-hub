import io
import json
import logging
from typing import Any

import pytest

from agent_hub.api.json_logging import (
    LOGGER,
    LOGGER_NAME,
    JsonFormatter,
    configure_logging,
    request_fields,
)

LEAK_SAMPLE = "ghp_SYNTHETIC0123456789abcdefghijklmnopqr"


def _request_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.getMessage() == "request"]


def test_logs_route_template_without_payload_when_request_served(
    wired: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    wired.client.get(
        "/api/v1/sessions/session-1/events", params={"cursor": LEAK_SAMPLE, "limit": "5"}
    )
    wired.client.post("/api/v1/hubs", json={"path": f"/home/demo/{LEAK_SAMPLE}"})

    records = _request_records(caplog)
    assert [(record.method, record.path) for record in records] == [  # type: ignore[attr-defined]
        ("GET", "/api/v1/sessions/{session_id}/events"),
        ("POST", "/api/v1/hubs"),
    ]
    assert records[0].session_id == "session-1"  # type: ignore[attr-defined]
    assert records[0].status == 404  # type: ignore[attr-defined]
    rendered = "".join(JsonFormatter().format(record) for record in caplog.records)
    assert LEAK_SAMPLE not in rendered
    assert "limit" not in rendered


def test_logs_project_of_path_when_route_names_one(
    wired: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    wired.client.get("/api/v1/projects/demo/now")

    (record,) = _request_records(caplog)
    assert record.project == "demo"  # type: ignore[attr-defined]
    assert record.path == "/api/v1/projects/{project}/now"  # type: ignore[attr-defined]


def test_logs_unmatched_marker_when_no_route_matched(
    client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    client.get(f"/sessions/{LEAK_SAMPLE}")

    (record,) = _request_records(caplog)
    assert record.path == "<unmatched>"  # type: ignore[attr-defined]
    assert record.status == 200  # type: ignore[attr-defined]


def test_writes_allowed_fields_only_when_record_formatted() -> None:
    record = logging.LogRecord(LOGGER_NAME, logging.INFO, __file__, 1, "request", None, None)
    record.method = "GET"
    record.status = 200
    record.payload = {"prompt": LEAK_SAMPLE}

    document = json.loads(JsonFormatter().format(record))

    assert document["message"] == "request"
    assert (document["method"], document["status"], document["level"]) == ("GET", 200, "info")
    assert "payload" not in document


def test_leaves_out_exception_text_when_record_has_one() -> None:
    try:
        raise ValueError(LEAK_SAMPLE)
    except ValueError:
        record = LOGGER.makeRecord(
            LOGGER_NAME, logging.ERROR, __file__, 1, "unhandled error", None, None
        )
        record.exc_text = LEAK_SAMPLE

    assert LEAK_SAMPLE not in JsonFormatter().format(record)


def test_omits_session_when_path_has_none() -> None:
    scope = {"method": "GET", "path_params": {}}

    fields = request_fields(scope, status=204, ms=1.234)

    assert fields == {"method": "GET", "path": "<unmatched>", "status": 204, "ms": 1.2}


def test_writes_json_lines_once_when_configured_twice() -> None:
    stream = io.StringIO()
    handlers = list(LOGGER.handlers)
    try:
        configure_logging(stream)
        configure_logging(stream)
        LOGGER.info("request", extra={"method": "GET"})
    finally:
        LOGGER.handlers = handlers
        LOGGER.propagate = True

    (line,) = stream.getvalue().splitlines()
    assert json.loads(line)["method"] == "GET"
