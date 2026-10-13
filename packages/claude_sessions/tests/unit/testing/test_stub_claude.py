"""The stub ``claude`` CLI in-process: scripted stdin in, scripted stream-json out (P17)."""

import io
import json
from pathlib import Path
from typing import Any

import pytest

from agent_hub.claude_sessions.testing.scenarios import (
    FORK_SESSION_ID,
    RECORD_ENV,
    SCENARIO_ENV,
    Scenario,
    held_turn,
    permission_turn,
    read_records,
    simple_turn,
    write_scenario,
)
from agent_hub.claude_sessions.testing.stub_claude import main

STREAM = ["--output-format", "stream-json", "--verbose", "--input-format", "stream-json"]
PROMPTS = ["--permission-prompt-tool", "stdio"]
PARTIALS = ["--include-partial-messages"]


def _user(text: str) -> dict[str, Any]:
    message = {"role": "user", "content": text}
    return {"type": "user", "message": message, "parent_tool_use_id": None, "session_id": "default"}


def _control(request_id: str, subtype: str, **fields: Any) -> dict[str, Any]:
    return {
        "type": "control_request",
        "request_id": request_id,
        "request": {"subtype": subtype, **fields},
    }


def _answer(request_id: str, answer: dict[str, Any]) -> dict[str, Any]:
    response = {"subtype": "success", "request_id": request_id, "response": answer}
    return {"type": "control_response", "response": response}


def _run(
    tmp_path: Path,
    args: list[str],
    lines: list[dict[str, Any]],
    *,
    scenario: Scenario | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    environ = {RECORD_ENV: str(tmp_path / "record.jsonl")}
    if scenario is not None:
        environ[SCENARIO_ENV] = str(write_scenario(tmp_path, scenario))
    stdin = io.StringIO("".join(json.dumps(line) + "\n" for line in lines))
    stdout = io.StringIO()
    code = main(args, stdin=stdin, stdout=stdout, environ=environ)
    return code, [json.loads(line) for line in stdout.getvalue().splitlines()]


def _of(
    messages: list[dict[str, Any]], kind: str, subtype: str | None = None
) -> list[dict[str, Any]]:
    return [
        m
        for m in messages
        if m["type"] == kind and (subtype is None or m.get("subtype") == subtype)
    ]


def test_answers_scripted_stdout_when_protocol_turn_scripted(tmp_path: Path) -> None:
    scenario = Scenario(turns=[simple_turn("Hello there")])
    lines = [_control("req_1", "initialize", hooks=None), _user("hi")]

    code, out = _run(tmp_path, STREAM + PARTIALS, lines, scenario=scenario)

    assert code == 0
    assert [m["type"] for m in out] == [
        "control_response",
        "system",
        "stream_event",
        "stream_event",
        "assistant",
        "result",
    ]
    assert out[0]["response"]["request_id"] == "req_1"
    assert [c["name"] for c in out[0]["response"]["response"]["commands"]] == ["compact", "review"]
    assert out[1]["subtype"] == "init"
    assert out[1]["session_id"] == scenario.session_id
    deltas = "".join(m["event"]["delta"]["text"] for m in _of(out, "stream_event"))
    assert deltas == "Hello there"
    assert out[4]["message"]["content"] == [{"type": "text", "text": "Hello there"}]
    result = out[5]
    assert (result["subtype"], result["terminal_reason"], result["is_error"]) == (
        "success",
        "completed",
        False,
    )
    assert result["total_cost_usd"] == pytest.approx(0.0012)
    assert result["result"] == "Hello there"


def test_skips_deltas_when_partial_messages_not_requested(tmp_path: Path) -> None:
    _, out = _run(tmp_path, STREAM, [_user("hi")], scenario=Scenario(turns=[simple_turn()]))

    assert _of(out, "stream_event") == []
    assert [m["type"] for m in out] == ["system", "assistant", "result"]


def test_parks_permission_until_answered_when_protocol_tool_needs_approval(tmp_path: Path) -> None:
    scenario = Scenario(turns=[permission_turn("npm run build")])
    allow = _answer("stub-permission-1", {"behavior": "allow", "updatedInput": {}})

    _, parked = _run(tmp_path, STREAM + PROMPTS, [_user("build")], scenario=scenario)
    _, answered = _run(tmp_path, STREAM + PROMPTS, [_user("build"), allow], scenario=scenario)

    request = parked[-1]
    assert request["type"] == "control_request"
    assert request["request"]["subtype"] == "can_use_tool"
    assert request["request"]["tool_name"] == "Bash"
    assert request["request"]["input"]["command"] == "npm run build"
    assert request["request"]["permission_suggestions"][0]["destination"] == "localSettings"
    assert _of(parked, "result") == []
    tool_result = _of(answered, "user")[0]["message"]["content"][0]
    assert (tool_result["content"], tool_result["is_error"]) == ("ok", False)
    assert _of(answered, "result")[0]["terminal_reason"] == "completed"


def test_reports_denial_when_permission_denied(tmp_path: Path) -> None:
    deny = _answer("stub-permission-1", {"behavior": "deny", "message": "not now"})

    _, out = _run(
        tmp_path,
        STREAM + PROMPTS,
        [_user("build"), deny],
        scenario=Scenario(turns=[permission_turn()]),
    )

    tool_result = _of(out, "user")[0]["message"]["content"][0]
    assert (tool_result["content"], tool_result["is_error"]) == ("not now", True)
    records = read_records(tmp_path / "record.jsonl")
    assert [r.data.get("behavior") for r in records if r.subtype == "can_use_tool_answer"] == [
        "deny"
    ]


def test_ignores_answer_when_request_id_unknown(tmp_path: Path) -> None:
    stray = _answer("someone-else", {"behavior": "allow"})

    _, out = _run(
        tmp_path,
        STREAM + PROMPTS,
        [_user("build"), stray],
        scenario=Scenario(turns=[permission_turn()]),
    )

    assert out[-1]["type"] == "control_request"


def test_denies_tool_when_prompts_not_routed_to_stdio(tmp_path: Path) -> None:
    _, out = _run(tmp_path, STREAM, [_user("build")], scenario=Scenario(turns=[permission_turn()]))

    assert _of(out, "control_request") == []
    assert _of(out, "user")[0]["message"]["content"][0]["is_error"] is True


def test_ends_turn_aborted_when_interrupt_arrives(tmp_path: Path) -> None:
    lines = [_user("long"), _control("req_2", "interrupt"), _user("again")]

    _, out = _run(
        tmp_path, STREAM + PARTIALS, lines, scenario=Scenario(turns=[held_turn(), simple_turn()])
    )

    results = _of(out, "result")
    assert [(r["subtype"], r["terminal_reason"]) for r in results] == [
        ("error_during_execution", "aborted_streaming"),
        ("success", "completed"),
    ]
    assert _of(out, "control_response")[0]["response"]["request_id"] == "req_2"


def test_ends_turn_aborted_tools_when_interrupted_during_permission(tmp_path: Path) -> None:
    lines = [_user("build"), _control("req_3", "interrupt")]

    _, out = _run(tmp_path, STREAM + PROMPTS, lines, scenario=Scenario(turns=[permission_turn()]))

    assert _of(out, "result")[0]["terminal_reason"] == "aborted_tools"


def test_answers_success_when_interrupt_arrives_between_turns(tmp_path: Path) -> None:
    _, out = _run(tmp_path, STREAM, [_control("req_4", "interrupt")], scenario=Scenario())

    assert [m["type"] for m in out] == ["control_response"]


@pytest.mark.parametrize(
    ("flags", "reported"),
    [
        ([], "auto"),
        (["--permission-mode", "manual"], "default"),
        (["--permission-mode", "plan"], "plan"),
    ],
)
def test_reports_mode_in_init_when_mode_flag_given(
    tmp_path: Path, flags: list[str], reported: str
) -> None:
    _, out = _run(tmp_path, STREAM + flags, [_user("hi")], scenario=Scenario(turns=[simple_turn()]))

    assert _of(out, "system", "init")[0]["permissionMode"] == reported


def test_applies_mode_and_model_when_set_between_turns(tmp_path: Path) -> None:
    lines = [
        _user("one"),
        _control("req_5", "set_permission_mode", mode="acceptEdits"),
        _control("req_6", "set_model", model="sonnet"),
        _user("two"),
    ]

    _, out = _run(tmp_path, STREAM, lines, scenario=Scenario(turns=[simple_turn()]))

    assert _of(out, "system", "status")[0]["permissionMode"] == "acceptEdits"
    second_init = _of(out, "system", "init")[1]
    assert (second_init["permissionMode"], second_init["model"]) == ("acceptEdits", "sonnet")


@pytest.mark.parametrize(
    ("flags", "session_id"),
    [
        (
            ["--session-id=11111111-1111-4111-8111-111111111111"],
            "11111111-1111-4111-8111-111111111111",
        ),
        (["--resume=22222222-2222-4222-8222-222222222222"], "22222222-2222-4222-8222-222222222222"),
        (["--resume=22222222-2222-4222-8222-222222222222", "--fork-session"], FORK_SESSION_ID),
        (
            ["--model", "opus", "--session-id", "33333333-3333-4333-8333-333333333333"],
            "33333333-3333-4333-8333-333333333333",
        ),
    ],
)
def test_reports_session_id_when_session_flags_given(
    tmp_path: Path, flags: list[str], session_id: str
) -> None:
    _, out = _run(tmp_path, STREAM + flags, [_user("hi")], scenario=Scenario(turns=[simple_turn()]))

    assert _of(out, "system", "init")[0]["session_id"] == session_id
    assert _of(out, "result")[0]["session_id"] == session_id


def test_records_args_and_environment_keys_when_started(tmp_path: Path) -> None:
    _run(tmp_path, STREAM, [_user("hi")], scenario=Scenario(turns=[simple_turn()]))

    records = read_records(tmp_path / "record.jsonl")
    start = records[0]
    assert start.event == "start"
    assert start.args == STREAM
    assert RECORD_ENV in start.env_keys
    assert [r.event for r in records[1:]] == ["spawn", "user"]
    assert records[2].data == {"text": "hi"}


def test_prints_version_when_version_asked(tmp_path: Path) -> None:
    stdout = io.StringIO()

    code = main(["-v"], stdin=io.StringIO(), stdout=stdout, environ={})

    assert (code, stdout.getvalue()) == (0, "2.1.296 (Claude Code)\n")


@pytest.mark.parametrize(("cloud", "listed"), [(True, True), (False, False)])
def test_lists_cloud_flags_when_help_asked(tmp_path: Path, *, cloud: bool, listed: bool) -> None:
    environ = {SCENARIO_ENV: str(write_scenario(tmp_path, Scenario(cloud=cloud)))}
    stdout = io.StringIO()

    code = main(["--help"], stdin=io.StringIO(), stdout=stdout, environ=environ)

    assert code == 0
    assert ("--cloud" in stdout.getvalue(), "--teleport" in stdout.getvalue()) == (listed, listed)


def test_refuses_cloud_start_when_not_interactive(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["--cloud", "synthetic task"], stdin=io.StringIO(), stdout=io.StringIO(), environ={}
    )

    assert code == 1
    assert "interactive terminal" in capsys.readouterr().err


def test_prints_cloud_output_when_followup_printed(tmp_path: Path) -> None:
    output = (
        '{"ok": true, "session_id": "cse_synthetic", "url": "https://claude.ai/code/cse_synthetic"}'
    )
    environ = {SCENARIO_ENV: str(write_scenario(tmp_path, Scenario(cloud_output=output)))}
    stdout = io.StringIO()
    args = ["-p", "follow up", "--cloud", "cse_synthetic", "--output-format", "json"]

    code = main(args, stdin=io.StringIO(), stdout=stdout, environ=environ)

    assert (code, stdout.getvalue()) == (0, output)


def test_refuses_text_mode_when_stream_not_requested(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["-p", "hi"], stdin=io.StringIO(), stdout=io.StringIO(), environ={})

    assert code == 1
    assert "stream-json" in capsys.readouterr().err


def test_ends_turn_with_result_when_steps_run_out(tmp_path: Path) -> None:
    scenario = Scenario.model_validate({"turns": [[{"kind": "text", "text": "no result step"}]]})

    _, out = _run(tmp_path, STREAM, [_user("hi")], scenario=scenario)

    assert _of(out, "result")[0]["result"] == "no result step"


def test_reuses_last_turn_when_messages_outnumber_turns(tmp_path: Path) -> None:
    _, out = _run(
        tmp_path, STREAM, [_user("one"), _user("two")], scenario=Scenario(turns=[simple_turn("x")])
    )

    assert len(_of(out, "result")) == 2
