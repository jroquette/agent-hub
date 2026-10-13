"""The shared Linear GraphQL transport: failure kinds at each raise site and nullable shapes."""

import json
from collections.abc import Callable, Mapping

import pytest

from agent_hub.core.errors import TrackerError, TrackerFailure
from agent_hub.tracker_linear.graphql_transport import (
    LINEAR_API_KEY_VARIABLE,
    MAX_RESPONSE_BYTES,
    Nullable,
    Shape,
    fits,
    request_data,
)

type Reply = Callable[[], tuple[int, bytes]]


def _answer(status: int, payload: object) -> Reply:
    return lambda: (status, json.dumps(payload).encode())


def _raw(status: int, body: bytes) -> Reply:
    return lambda: (status, body)


def _raising(error: OSError) -> Reply:
    def reply() -> tuple[int, bytes]:
        raise error

    return reply


def _errors(**extensions: str) -> dict[str, object]:
    return {"errors": [{"message": "synthetic", "extensions": extensions}], "data": None}


_FAILURES: list[tuple[str, Reply, TrackerFailure, int | None]] = [
    ("http-401", _answer(401, {}), "unauthorized", 401),
    ("http-403", _answer(403, {}), "unauthorized", 403),
    ("http-302", _raw(302, b"moved"), "unexpected", 302),
    ("http-429", _answer(429, {}), "rate_limited", 429),
    ("http-500", _answer(500, {}), "unavailable", 500),
    ("http-503", _raw(503, b"down"), "unavailable", 503),
    ("http-400", _answer(400, {"data": None}), "unexpected", 400),
    ("not-json", _raw(200, b"<html>"), "unexpected", 200),
    ("too-deep", _raw(200, b"[" * 100_000 + b"]" * 100_000), "unexpected", 200),
    ("too-long", _raw(200, b" " * (MAX_RESPONSE_BYTES + 1)), "unexpected", 200),
    ("other-shape", _answer(200, {"data": {"viewer": {"id": 1}}}), "unexpected", 200),
    ("errors-ratelimited", _answer(200, _errors(code="RATELIMITED")), "rate_limited", 200),
    ("errors-auth", _answer(200, _errors(type="authentication error")), "unauthorized", 200),
    ("errors-other", _answer(200, _errors(code="INVALID_INPUT")), "unexpected", 200),
    ("timeout", _raising(TimeoutError("slow")), "timeout", None),
    ("os-error", _raising(ConnectionRefusedError("refused")), "unreachable", None),
]


def _request(reply: Reply, environ: Mapping[str, str]) -> object:
    def post(
        url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
    ) -> tuple[int, bytes]:
        del url, headers, body, timeout_s
        return reply()

    return request_data(
        post=post,
        environ=environ,
        timeout_s=10.0,
        operation="issue_summaries",
        issue_id=None,
        operation_name="Viewer",
        query="query Viewer { viewer { id } }",
        variables={},
        shape={"viewer": {"id": str}},
    )


@pytest.mark.parametrize(
    ("reply", "kind", "http_status"),
    [pytest.param(reply, kind, status, id=name) for name, reply, kind, status in _FAILURES],
)
def test_sets_kind_when_status_is_each_failure(
    *, reply: Reply, kind: TrackerFailure, http_status: int | None, synthetic_key: str
) -> None:
    with pytest.raises(TrackerError) as raised:
        _request(reply, {LINEAR_API_KEY_VARIABLE: synthetic_key})

    assert (raised.value.kind, raised.value.http_status) == (kind, http_status)
    assert synthetic_key not in str(raised.value)


@pytest.mark.parametrize(
    ("environ", "kind"),
    [
        pytest.param({}, "not_connected", id="no-key"),
        pytest.param({LINEAR_API_KEY_VARIABLE: ""}, "not_connected", id="empty-key"),
        pytest.param({LINEAR_API_KEY_VARIABLE: "lin api"}, "unauthorized", id="malformed-key"),
    ],
)
def test_sets_kind_before_any_request_when_key_missing_or_malformed(
    environ: dict[str, str], kind: TrackerFailure
) -> None:
    def never() -> tuple[int, bytes]:
        raise AssertionError("no request may be sent")

    with pytest.raises(TrackerError) as raised:
        _request(never, environ)

    assert (raised.value.kind, raised.value.http_status) == (kind, None)


def test_returns_data_when_answer_fits(synthetic_key: str) -> None:
    data = _request(
        _answer(200, {"data": {"viewer": {"id": "u1"}}}), {LINEAR_API_KEY_VARIABLE: synthetic_key}
    )

    assert data == {"viewer": {"id": "u1"}}


_NULLABLE_PERSON: Shape = {"assignee": Nullable({"displayName": str})}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param({"assignee": None}, True, id="null"),
        pytest.param({"assignee": {"displayName": "Ada"}}, True, id="object"),
        pytest.param({"assignee": {"displayName": None}}, False, id="null-inside"),
        pytest.param({"assignee": {"name": "Ada"}}, False, id="other-fields"),
        pytest.param({}, False, id="field-absent"),
        pytest.param({"assignee": "Ada"}, False, id="leaf-for-object"),
    ],
)
def test_accepts_null_when_shape_nullable(value: object, *, expected: bool) -> None:
    assert fits(value, _NULLABLE_PERSON) is expected


def test_refuses_null_when_shape_not_nullable() -> None:
    assert fits({"assignee": None}, {"assignee": {"displayName": str}}) is False
    assert fits([None], [Nullable(int)]) is True
    assert fits([None], [int]) is False
