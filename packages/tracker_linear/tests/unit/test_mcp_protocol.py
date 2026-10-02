"""The MCP adapter's request line, prompts, tool table and reply checks (ADR 0015)."""

import json
from typing import Any

import pytest

from agent_hub.core.errors import TrackerError
from agent_hub.core.tracker.tracker_client import Issue
from agent_hub.tracker_linear.mcp_protocol import (
    DENIED,
    LINEAR_TOOL_PREFIX,
    LINEAR_TOOLS,
    MAX_COMMENT_CHARS,
    MAX_LABELS,
    MAX_NAME_CHARS,
    MAX_NAMES,
    MAX_QUOTED_CHARS,
    MAX_READY_ISSUES,
    MAX_REPLY_BYTES,
    TOOLS,
    WRITE_KINDS,
    CallKind,
    CommentSaved,
    IssueSeen,
    LabelsRead,
    LabelsSaved,
    McpCall,
    ReadyIssue,
    ReadyReply,
    StateRead,
    StateSaved,
    call_error,
    comment_read_call,
    get_issue_call,
    label_read_call,
    list_ready_call,
    parse_reply,
    prompt,
    quoted,
    request_line,
    save_comment_call,
    save_labels_call,
    save_state_call,
    state_read_call,
)


def _every_call() -> list[McpCall[Any]]:
    return [
        list_ready_call("DEM", "agent-ready"),
        get_issue_call("DEM-1"),
        state_read_call("DEM-1"),
        label_read_call("add_label", "DEM-1"),
        comment_read_call("DEM-1"),
        save_state_call("DEM-1", "In Review"),
        save_labels_call("remove_label", "DEM-1", ("demo-api", "feature")),
        save_comment_call("DEM-1", "Run 1a2b3c4d opened a PR."),
    ]


_ISSUE_JSON = {
    "id": "DEM-1",
    "title": "A title",
    "description": None,
    "url": "https://linear.app/demo/issue/DEM-1",
    "state": "Todo",
    "labels": ["agent-ready", "demo-api"],
}
_ISSUE = Issue(
    id="DEM-1",
    title="A title",
    description="",
    url="https://linear.app/demo/issue/DEM-1",
    state="Todo",
    labels=("agent-ready", "demo-api"),
)

# One exact reply per call kind, and what it parses to.
_REPLIES: list[tuple[McpCall[Any], dict[str, Any], object]] = [
    (
        list_ready_call("DEM", "agent-ready"),
        {"issues": [{**_ISSUE_JSON, "state_type": "unstarted"}], "more": False},
        ReadyReply(issues=(ReadyIssue(issue=_ISSUE, state_type="unstarted"),), more=False),
    ),
    (
        get_issue_call("DEM-1"),
        {"issue": {**_ISSUE_JSON, "description": "Body\n\n- one"}},
        _ISSUE.model_copy(update={"description": "Body\n\n- one"}),
    ),
    (
        state_read_call("DEM-1"),
        {"id": "DEM-1", "state": "Todo", "states": ["Todo", "In Review", "Done"]},
        StateRead(issue_id="DEM-1", state="Todo", states=("Todo", "In Review", "Done")),
    ),
    (
        label_read_call("add_label", "DEM-1"),
        {"id": "DEM-1", "labels": ["demo-api"], "available_labels": ["demo-api", "bug"]},
        LabelsRead(issue_id="DEM-1", labels=("demo-api",), available_labels=("demo-api", "bug")),
    ),
    (comment_read_call("DEM-1"), {"id": "DEM-1"}, IssueSeen(issue_id="DEM-1")),
    (
        save_state_call("DEM-1", "In Review"),
        {"id": "DEM-1", "state": "In Review"},
        StateSaved(issue_id="DEM-1", state="In Review"),
    ),
    (
        save_labels_call("add_label", "DEM-1", ("demo-api", "bug")),
        {"id": "DEM-1", "labels": ["demo-api", "bug"]},
        LabelsSaved(issue_id="DEM-1", labels=("demo-api", "bug")),
    ),
    (
        save_comment_call("DEM-1", "Run 1a2b3c4d opened a PR."),
        {"id": "DEM-1", "commented": True},
        CommentSaved(issue_id="DEM-1", commented=True),
    ),
]
_REPLY_IDS = [call.kind.value for call, _reply, _parsed in _REPLIES]


def _line(value: object) -> str:
    return json.dumps(value)


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("MAX_REPLY_BYTES", MAX_REPLY_BYTES, 1 << 20),
        ("MAX_READY_ISSUES", MAX_READY_ISSUES, 100),
        ("MAX_LABELS", MAX_LABELS, 50),
        ("MAX_NAMES", MAX_NAMES, 250),
        ("MAX_NAME_CHARS", MAX_NAME_CHARS, 256),
        ("MAX_COMMENT_CHARS", MAX_COMMENT_CHARS, 10_000),
        ("MAX_QUOTED_CHARS", MAX_QUOTED_CHARS, 200),
        ("LINEAR_TOOL_PREFIX", LINEAR_TOOL_PREFIX, "mcp__Linear__"),
    ],
)
def test_keeps_literal_value_when_constant_read(name: str, value: object, expected: object) -> None:
    assert value == expected, name


def test_writes_one_sorted_line_when_request_built() -> None:
    line = request_line("save_comment", {"issue_id": "DEM-1", "body": 'a\n"b"é'})

    assert line == (
        '{"arguments": {"body": "a\\n\\"b\\"\\u00e9", "issue\\u005fid": "DEM-1"}, '
        '"operation": "save\\u005fcomment"}'
    )
    assert "\n" not in line
    assert line.isascii()
    assert json.loads(line) == {
        "arguments": {"body": 'a\n"b"\u00e9', "issue_id": "DEM-1"},
        "operation": "save_comment",
    }


def test_writes_label_set_as_list_when_request_built() -> None:
    line = request_line("save_labels", {"issue_id": "DEM-1", "labels": ("b", "a")})

    assert json.loads(line) == {
        "arguments": {"issue_id": "DEM-1", "labels": ["b", "a"]},
        "operation": "save_labels",
    }


@pytest.mark.parametrize("call", _every_call(), ids=[call.kind.value for call in _every_call()])
def test_names_no_prefix_when_prompt_built(call: McpCall[Any]) -> None:
    text = prompt(call)

    assert "mcp__" not in text
    assert text.endswith("\n" + request_line(call.kind, call.arguments))
    # The request line is the only line built from caller values.
    assert text.count("DEM-1") == (0 if call.issue_id is None else 1)


def test_prefixes_every_tool_when_table_read() -> None:
    assert set(TOOLS) == set(CallKind)
    assert all(tool.startswith(LINEAR_TOOL_PREFIX) for tools in TOOLS.values() for tool in tools)
    assert {
        kind: [tool.removeprefix(LINEAR_TOOL_PREFIX) for tool in tools]
        for kind, tools in TOOLS.items()
    } == {
        CallKind.LIST_READY: ["list_issues", "list_issue_statuses"],
        CallKind.GET_ISSUE: ["get_issue"],
        CallKind.READ_STATE: ["get_issue", "list_issue_statuses"],
        CallKind.READ_LABELS: ["get_issue", "list_issue_labels"],
        CallKind.READ_ISSUE: ["get_issue"],
        CallKind.SAVE_STATE: ["save_issue"],
        CallKind.SAVE_LABELS: ["save_issue"],
        CallKind.SAVE_COMMENT: ["save_comment"],
    }


def test_allows_no_write_tool_when_call_reads() -> None:
    assert {CallKind.SAVE_STATE, CallKind.SAVE_LABELS, CallKind.SAVE_COMMENT} == WRITE_KINDS
    for kind, tools in TOOLS.items():
        writes = [tool for tool in tools if "save_" in tool]
        assert len(writes) == (1 if kind in WRITE_KINDS else 0), kind
        assert len(tools) == 1 or kind not in WRITE_KINDS, kind


def test_names_port_operation_when_call_built() -> None:
    operations = [(call.operation, call.issue_id) for call in _every_call()]

    assert operations == [
        ("list_ready", None),
        ("get_issue", "DEM-1"),
        ("move_state", "DEM-1"),
        ("add_label", "DEM-1"),
        ("comment", "DEM-1"),
        ("move_state", "DEM-1"),
        ("remove_label", "DEM-1"),
        ("comment", "DEM-1"),
    ]


def test_refuses_comment_when_body_too_long() -> None:
    save_comment_call("DEM-1", "x" * MAX_COMMENT_CHARS)

    with pytest.raises(TrackerError, match=f"comment DEM-1: .*{MAX_COMMENT_CHARS}") as raised:
        save_comment_call("DEM-1", "x" * (MAX_COMMENT_CHARS + 1))

    assert "x" * MAX_QUOTED_CHARS not in str(raised.value)


@pytest.mark.parametrize(("call", "reply", "parsed"), _REPLIES, ids=_REPLY_IDS)
def test_parses_reply_when_shape_exact(
    call: McpCall[Any], reply: dict[str, Any], parsed: object
) -> None:
    assert parse_reply(call, _line(reply)) == parsed
    assert parse_reply(call, "  " + _line(reply) + "\n") == parsed


def _drop_first_key(reply: dict[str, Any]) -> dict[str, Any]:
    first = next(iter(reply))
    return {name: value for name, value in reply.items() if name != first}


@pytest.mark.parametrize(("call", "reply", "_parsed"), _REPLIES, ids=_REPLY_IDS)
@pytest.mark.parametrize(
    "change",
    [
        lambda reply: {**reply, "note": "extra"},
        _drop_first_key,
        lambda reply: dict.fromkeys(reply, 5),
        lambda reply: [reply],
    ],
    ids=["extra-key", "missing-key", "wrong-type", "not-object"],
)
def test_rejects_reply_when_key_extra_or_missing(
    call: McpCall[Any], reply: dict[str, Any], _parsed: object, change: Any
) -> None:
    with pytest.raises(TrackerError, match="another shape") as raised:
        parse_reply(call, _line(change(reply)))

    message = str(raised.value)
    subject = call.operation if call.issue_id is None else f"{call.operation} {call.issue_id}"
    assert message.startswith(f"{subject}: ")
    if call.kind in WRITE_KINDS:
        # A write call ran: its fix is the write's, never a retry.
        assert message.endswith(f"; {_WRITE_FIX}, and it is not retried")
    else:
        assert 'tracker.transport to "api"' in message
        assert "LINEAR_API_KEY" in message


@pytest.mark.parametrize(
    ("issue_change", "fragment"),
    [
        ({"labels": ["x"] * (MAX_LABELS + 1)}, f"more than {MAX_LABELS} labels"),
        ({"labels": [5]}, "another shape"),
        ({"description": 5}, "another shape"),
        ({"state_type": None}, "another shape"),
    ],
    ids=["too-many-labels", "label-not-text", "description-not-text", "state-type-null"],
)
def test_rejects_ready_issue_when_field_wrong(issue_change: dict[str, Any], fragment: str) -> None:
    issue = {**_ISSUE_JSON, "state_type": "started", **issue_change}

    with pytest.raises(TrackerError, match=fragment):
        parse_reply(
            list_ready_call("DEM", "agent-ready"), _line({"issues": [issue], "more": False})
        )


def test_rejects_reply_when_issues_over_bound() -> None:
    issues = [
        {**_ISSUE_JSON, "id": f"DEM-{number}", "state_type": "started"}
        for number in range(1, MAX_READY_ISSUES + 2)
    ]
    call = list_ready_call("DEM", "agent-ready")

    parse_reply(call, _line({"issues": issues[:MAX_READY_ISSUES], "more": False}))
    with pytest.raises(TrackerError, match=f"more than {MAX_READY_ISSUES} issues"):
        parse_reply(call, _line({"issues": issues, "more": False}))


@pytest.mark.parametrize(
    ("call", "field"),
    [
        (state_read_call("DEM-1"), "states"),
        (label_read_call("add_label", "DEM-1"), "available_labels"),
    ],
    ids=["states", "labels"],
)
def test_rejects_reply_when_names_over_bound(call: McpCall[Any], field: str) -> None:
    reply = {"id": "DEM-1", "state": "Todo", "labels": [], "available_labels": [], "states": []}
    keys = {
        "states": ("id", "state", "states"),
        "available_labels": ("id", "labels", "available_labels"),
    }[field]
    exact = {name: reply[name] for name in keys}

    parse_reply(call, _line({**exact, field: ["n"] * MAX_NAMES}))
    with pytest.raises(TrackerError, match=f"more than {MAX_NAMES} names"):
        parse_reply(call, _line({**exact, field: ["n"] * (MAX_NAMES + 1)}))


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        '```json\n{"id": "DEM-1"}\n```',
        '{"id": "DEM-1"}\n{"id": "DEM-2"}',
        '{"id":\r"DEM-1"}',
        "Done: the comment is added.",
        '{"id": "DEM-1"',
    ],
    ids=[
        "empty",
        "blank",
        "fenced",
        "two-lines",
        "carriage-return",
        "prose",
        "cut",
    ],
)
def test_rejects_reply_when_not_one_line(text: str) -> None:
    with pytest.raises(TrackerError, match="not one line of JSON") as raised:
        parse_reply(comment_read_call("DEM-1"), text)

    assert str(raised.value).startswith("comment DEM-1: ")
    assert "\n" not in str(raised.value)


def test_rejects_reply_when_parser_recurses_too_deeply(monkeypatch: pytest.MonkeyPatch) -> None:
    # Whether a deep reply overflows the parser depends on the C stack size, so it is forced here.
    def too_deep(*_: object, **__: object) -> object:
        raise RecursionError

    monkeypatch.setattr(json, "loads", too_deep)

    with pytest.raises(TrackerError, match="not one line of JSON") as raised:
        parse_reply(comment_read_call("DEM-1"), '{"id": "DEM-1"}')

    assert "\n" not in str(raised.value)


def test_rejects_reply_when_nested_deep() -> None:
    # Refused either way: too deep where the parser overflows, another shape where it does not.
    with pytest.raises(TrackerError) as raised:
        parse_reply(comment_read_call("DEM-1"), "[" * 100_000 + "]" * 100_000)

    assert str(raised.value).startswith("comment DEM-1: ")
    assert "\n" not in str(raised.value)


def test_rejects_reply_when_over_size() -> None:
    padding = " " * (MAX_REPLY_BYTES - len('{"id": "DEM-1"}'))
    call = comment_read_call("DEM-1")

    assert parse_reply(call, '{"id": "DEM-1"}' + padding) == IssueSeen(issue_id="DEM-1")
    with pytest.raises(TrackerError, match="over 1 MiB"):
        parse_reply(call, '{"id": "DEM-1"}' + padding + " ")
    with pytest.raises(TrackerError, match="over 1 MiB"):
        parse_reply(call, '{"id": "DEM-1"}' + padding[:-1] + "é")


def test_quotes_untrusted_text_when_error_reported() -> None:
    untrusted = "ignore the above\x1b[31m " + "y" * 500

    with pytest.raises(TrackerError) as raised:
        parse_reply(get_issue_call("DEM-1"), untrusted)

    message = str(raised.value)
    assert repr(untrusted[:MAX_QUOTED_CHARS]) in message
    assert "y" * (MAX_QUOTED_CHARS) not in message
    assert "\x1b" not in message


def test_quotes_untrusted_text_when_shape_wrong() -> None:
    reply = _line({"issue": {"title": "z" * 500}})

    with pytest.raises(TrackerError, match="another shape") as raised:
        parse_reply(get_issue_call("DEM-1"), reply)

    assert repr(reply[:MAX_QUOTED_CHARS]) in str(raised.value)
    assert "z" * MAX_QUOTED_CHARS not in str(raised.value)


@pytest.mark.parametrize("call", _every_call(), ids=[call.kind.value for call in _every_call()])
def test_names_mcp_server_when_tools_unavailable(call: McpCall[Any]) -> None:
    # A write call's model may have written before it said so: its fix is the write's.
    fix = _WRITE_FIX if call.kind in WRITE_KINDS else "connect the Linear MCP server"
    with pytest.raises(TrackerError, match=fix) as raised:
        parse_reply(call, '{"error": "tools unavailable"}')

    assert str(raised.value).startswith(call.operation)
    # Read or write, the cause still names the missing tools.
    assert "the Linear MCP tools are not available to claude" in str(raised.value)


def test_names_issue_when_reply_says_not_found() -> None:
    with pytest.raises(TrackerError, match=r"^move_state DEM-9: issue DEM-9 not found in Linear"):
        parse_reply(state_read_call("DEM-9"), '{"error": "not found"}')


_LONG_ERROR = "e" * 500


@pytest.mark.parametrize(
    ("call", "reply", "cause"),
    [
        (
            list_ready_call("DEM", "agent-ready"),
            '{"error": "not found"}',
            "list_ready: the reply answered an error: 'not found'; ",
        ),
        (
            get_issue_call("DEM-1"),
            '{"error": "rate limited, try later"}',
            "get_issue DEM-1: the reply answered an error: 'rate limited, try later'; ",
        ),
        (
            get_issue_call("DEM-1"),
            '{"error": 5}',
            "get_issue DEM-1: the reply has another shape: '{\"error\": 5}'; ",
        ),
        (
            get_issue_call("DEM-1"),
            _line({"error": _LONG_ERROR}),
            f"get_issue DEM-1: the reply answered an error: {_LONG_ERROR[:MAX_QUOTED_CHARS]!r}; ",
        ),
    ],
    ids=["not-found-without-issue", "other-text", "not-text", "long-text"],
)
def test_quotes_error_when_reply_error_unknown(call: McpCall[Any], reply: str, cause: str) -> None:
    with pytest.raises(TrackerError) as raised:
        parse_reply(call, reply)

    message = str(raised.value)
    assert message.startswith(cause)
    assert message.endswith('retry or set tracker.transport to "api" with LINEAR_API_KEY')
    assert "e" * (MAX_QUOTED_CHARS + 1) not in message


_PREFIXED = "see mcp__Linear__save_issue, then mcp__x"


@pytest.mark.parametrize(
    ("call", "argument", "value"),
    [
        (save_comment_call("DEM-1", _PREFIXED), "body", _PREFIXED),
        (save_labels_call("add_label", "DEM-1", ("mcp__x", "a_b")), "labels", ["mcp__x", "a_b"]),
        (save_state_call("DEM-1", "mcp__Done"), "state", "mcp__Done"),
        (list_ready_call("DEM", "mcp__ready"), "label", "mcp__ready"),
    ],
    ids=["comment", "labels", "state", "ready-label"],
)
def test_hides_prefix_when_argument_holds_it(
    call: McpCall[Any], argument: str, value: object
) -> None:
    text = prompt(call)

    assert "mcp__" not in text
    assert json.loads(text.splitlines()[-1])["arguments"][argument] == value


_LONG_NAME = "n" * (MAX_NAME_CHARS + 1)


@pytest.mark.parametrize(
    ("build", "operation"),
    [
        (lambda name: list_ready_call("DEM", name), "list_ready"),
        (lambda name: list_ready_call(name, "agent-ready"), "list_ready"),
        (lambda name: save_state_call("DEM-1", name), "move_state DEM-1"),
        (lambda name: save_labels_call("add_label", "DEM-1", ("a", name)), "add_label DEM-1"),
    ],
    ids=["ready-label", "team", "state", "label"],
)
def test_refuses_name_when_request_name_over_cap(build: Any, operation: str) -> None:
    build("n" * MAX_NAME_CHARS)

    with pytest.raises(TrackerError, match=f"^{operation}: .*over {MAX_NAME_CHARS} characters"):
        build(_LONG_NAME)


@pytest.mark.parametrize(
    ("call", "reply"),
    [
        (state_read_call("DEM-1"), {"id": "DEM-1", "state": "Todo", "states": [_LONG_NAME]}),
        (state_read_call("DEM-1"), {"id": "DEM-1", "state": _LONG_NAME, "states": []}),
        (
            label_read_call("add_label", "DEM-1"),
            {"id": "DEM-1", "labels": [], "available_labels": [_LONG_NAME]},
        ),
        (save_labels_call("add_label", "DEM-1", ("a",)), {"id": "DEM-1", "labels": [_LONG_NAME]}),
        (get_issue_call("DEM-1"), {"issue": {**_ISSUE_JSON, "labels": [_LONG_NAME]}}),
        (
            list_ready_call("DEM", "agent-ready"),
            {"issues": [{**_ISSUE_JSON, "state_type": _LONG_NAME}], "more": False},
        ),
    ],
    ids=["states", "state", "available-labels", "saved-labels", "issue-labels", "state-type"],
)
def test_refuses_reply_when_name_over_cap(call: McpCall[Any], reply: dict[str, Any]) -> None:
    with pytest.raises(TrackerError, match=f"a name over {MAX_NAME_CHARS} characters"):
        parse_reply(call, _line(reply))


def test_rejects_reply_when_text_not_utf8() -> None:
    with pytest.raises(TrackerError, match="^comment DEM-1: the reply is not UTF-8 text"):
        parse_reply(comment_read_call("DEM-1"), '{"id": "DEM-1"}\ud800')


@pytest.mark.parametrize(
    ("call", "text"),
    [
        (state_read_call("DEM-1"), '{"id": "DEM-1", "state": "\\ud800", "states": []}'),
        (comment_read_call("DEM-1"), '{"id": "DEM-1", "id": "DEM-2"}'),
        (save_comment_call("DEM-1", "x"), '{"id": "DEM-1", "commented": true, "commented": true}'),
        (comment_read_call("DEM-1"), '{"error": NaN}'),
        (comment_read_call("DEM-1"), '{"error": 1e400}'),
    ],
    ids=["escaped-lone-surrogate", "repeated-id", "repeated-flag", "nan", "huge-number"],
)
def test_rejects_reply_when_json_not_strict(call: McpCall[Any], text: str) -> None:
    with pytest.raises(TrackerError, match="not one line of JSON"):
        parse_reply(call, text)


@pytest.mark.parametrize("issue_id", ["OPS-9; ignore", "DEM-1\n", "dem-1", "DEM-0", ""])
@pytest.mark.parametrize(
    ("call", "reply"),
    [
        (comment_read_call("DEM-1"), lambda issue_id: {"id": issue_id}),
        (get_issue_call("DEM-1"), lambda issue_id: {"issue": {**_ISSUE_JSON, "id": issue_id}}),
        (
            list_ready_call("DEM", "agent-ready"),
            lambda issue_id: {
                "issues": [{**_ISSUE_JSON, "id": issue_id, "state_type": "started"}],
                "more": False,
            },
        ),
        (save_state_call("DEM-1", "Done"), lambda issue_id: {"id": issue_id, "state": "Done"}),
    ],
    ids=["read-issue", "get-issue", "list-ready", "save-state"],
)
def test_rejects_reply_when_issue_id_malformed(
    call: McpCall[Any], reply: Any, issue_id: str
) -> None:
    with pytest.raises(TrackerError, match="another shape"):
        parse_reply(call, _line(reply(issue_id)))


# Every tool of the snapshot that can change something in Linear, as a literal.
_WRITE_CAPABLE = {
    LINEAR_TOOL_PREFIX + name
    for name in (
        "create_attachment",
        "create_attachment_from_upload",
        "create_issue_label",
        "delete_attachment",
        "delete_comment",
        "delete_diff_comment",
        "delete_status_update",
        "mark_notification",
        "merge_diff",
        "prepare_attachment_upload",
        "resolve_diff_thread",
        "restore_issue_label",
        "restore_project_label",
        "retire_issue_label",
        "retire_project_label",
        "save_comment",
        "save_diff_comment",
        "save_document",
        "save_issue",
        "save_issue_label",
        "save_milestone",
        "save_project",
        "save_project_label",
        "save_release",
        "save_release_note",
        "save_status_update",
        "share_issue",
        "submit_diff_review",
        "unshare_issue",
        "update_diff",
    )
}


def test_holds_every_allowed_tool_when_snapshot_read() -> None:
    assert len(LINEAR_TOOLS) == 68
    assert len(set(LINEAR_TOOLS)) == len(LINEAR_TOOLS)
    assert all(tool.startswith(LINEAR_TOOL_PREFIX) for tool in LINEAR_TOOLS)
    assert {tool for tools in TOOLS.values() for tool in tools} <= set(LINEAR_TOOLS)


@pytest.mark.parametrize("kind", list(CallKind))
def test_denies_every_other_tool_when_kind_built(kind: CallKind) -> None:
    allowed, denied = set(TOOLS[kind]), set(DENIED[kind])

    assert allowed & denied == set()
    assert allowed | denied == set(LINEAR_TOOLS)
    assert len(DENIED[kind]) == len(denied)


@pytest.mark.parametrize("kind", sorted(set(CallKind) - WRITE_KINDS))
def test_denies_every_write_tool_when_call_reads(kind: CallKind) -> None:
    writes = {
        tool
        for tool in LINEAR_TOOLS
        if tool.removeprefix(LINEAR_TOOL_PREFIX).startswith(
            ("save_", "create_", "delete_", "update_")
        )
    }

    assert len(writes) == 19
    assert writes <= _WRITE_CAPABLE <= set(LINEAR_TOOLS)
    assert len(_WRITE_CAPABLE) == 30
    assert set(DENIED[kind]) >= _WRITE_CAPABLE


_WRITE_FIX = "check the issue in Linear: the write may have been made"
_WRITE_CALLS = [call for call in _every_call() if call.kind in WRITE_KINDS]


@pytest.mark.parametrize(
    "reply",
    [
        "not json",
        '{"answer": "done"}',
        '{"error": "tools unavailable"}',
        '{"error": "not found"}',
        '{"error": "rate limited"}',
        " " * (MAX_REPLY_BYTES + 1),
        '{"id": "DEM-1"}\ud800',
    ],
    ids=[
        "not-json",
        "other-shape",
        "tools-unavailable",
        "not-found",
        "other-error",
        "too-big",
        "not-utf8",
    ],
)
@pytest.mark.parametrize("call", _WRITE_CALLS, ids=[call.kind.value for call in _WRITE_CALLS])
def test_never_says_retry_when_write_reply_fails(call: McpCall[Any], reply: str) -> None:
    with pytest.raises(TrackerError) as raised:
        parse_reply(call, reply)

    fix = str(raised.value).partition("; ")[2]
    assert fix.startswith(_WRITE_FIX), fix
    assert "retry" not in fix


def test_keeps_fix_when_read_reply_fails() -> None:
    with pytest.raises(TrackerError) as raised:
        parse_reply(comment_read_call("DEM-1"), "not json")

    assert str(raised.value).endswith(
        '; retry or set tracker.transport to "api" with LINEAR_API_KEY'
    )


def test_names_operation_and_issue_when_call_error_built() -> None:
    error = call_error(state_read_call("DEM-1"), "a cause", "a fix")
    write_error = call_error(save_state_call("DEM-1", "Done"), "a cause", "a fix")

    assert str(error) == "move_state DEM-1: a cause; a fix"
    assert str(write_error).startswith(f"move_state DEM-1: a cause; {_WRITE_FIX}")
    assert quoted("x" * 500) == repr("x" * MAX_QUOTED_CHARS)


def test_rejects_reply_when_issue_listed_twice() -> None:
    first = {**_ISSUE_JSON, "state_type": "started"}
    again = {**first, "title": "Another title"}

    with pytest.raises(TrackerError, match=r"^list_ready: the reply has another shape"):
        parse_reply(
            list_ready_call("DEM", "agent-ready"), _line({"issues": [first, again], "more": False})
        )
