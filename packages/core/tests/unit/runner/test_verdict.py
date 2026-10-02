import json

import pytest

from agent_hub.core.runner.verdict import (
    MAX_RAW_TAIL_CHARS,
    MAX_REASON_TAIL_CHARS,
    Outcome,
    OutcomeKind,
    SessionReply,
    last_json_line,
    parse_session_output,
    session_outcome,
)


def a_reply(result: str, **overrides: object) -> SessionReply:
    fields: dict[str, object] = {
        "is_error": False,
        "subtype": "success",
        "result": result,
        "cost_usd": 0.5,
        "turns": 7,
    } | overrides
    return SessionReply.model_validate(fields)


def claude_output(result: object, **fields: object) -> str:
    return json.dumps(
        {"type": "result", "is_error": False, "subtype": "success", "result": result}
        | {"total_cost_usd": 1.25, "num_turns": 12}
        | fields
    )


def test_pins_tails_when_module_loaded() -> None:
    assert MAX_RAW_TAIL_CHARS == 2_000
    assert MAX_REASON_TAIL_CHARS == 800


def test_reads_last_json_line_when_fenced() -> None:
    # The hub's test_last_json_line (tests/test_agent_runner.py at hub commit 300559b).
    assert last_json_line('x\n```\n{"status": "done"}\n```') == {"status": "done"}
    assert last_json_line("nothing") is None


def test_reads_last_of_several_when_lines_hold_json() -> None:
    text = '{"status": "blocked"}\nprose\n`{"status": "done", "summary": "s"}`\n'

    assert last_json_line(text) == {"status": "done", "summary": "s"}


def test_skips_broken_line_when_earlier_one_parses() -> None:
    assert last_json_line('{"status": "done"}\n{not json}') == {"status": "done"}


def test_returns_none_when_reply_is_prose() -> None:
    assert last_json_line("I changed the code and ran the tests.") is None
    assert last_json_line("[1, 2]") is None
    assert last_json_line('{"a": 1} trailing') is None


def test_reads_empty_object_when_last_line_is_one() -> None:
    assert last_json_line('{"status": "done"}\n{}') == {}
    assert last_json_line("") is None


def test_reads_fields_when_output_is_claude_result() -> None:
    reply = parse_session_output(claude_output("all done"))

    assert reply == SessionReply(
        is_error=False, subtype="success", result="all done", cost_usd=1.25, turns=12
    )


def test_reads_zero_cost_when_fields_missing_or_wrong_type() -> None:
    text = json.dumps({"is_error": True, "result": None, "total_cost_usd": "1", "num_turns": True})

    reply = parse_session_output(text)

    assert reply == SessionReply(is_error=True, subtype=None, result="", cost_usd=0.0, turns=None)


def test_keeps_tail_when_output_not_json() -> None:
    text = "x" * 3_000 + "the end"

    reply = parse_session_output(text)

    assert reply.is_error
    assert reply.result == text[-MAX_RAW_TAIL_CHARS:]
    assert (reply.subtype, reply.cost_usd, reply.turns) == (None, 0.0, None)
    assert session_outcome(reply) == Outcome(
        kind=OutcomeKind.ERROR,
        text=f"the implementing session errored (None): {text[-MAX_REASON_TAIL_CHARS:]}",
    )


@pytest.mark.parametrize("text", ["[1]", '"text"', "NaN", '{"result": NaN}', ""])
def test_errors_when_output_is_json_but_no_result_object(text: str) -> None:
    reply = parse_session_output(text)

    assert reply.is_error
    assert reply.result == text


def test_errors_when_is_error_set() -> None:
    reply = a_reply("y" * 1_000 + '\n{"status": "done", "summary": "s"}', is_error=True)
    reply = reply.model_copy(update={"subtype": "error_max_turns"})

    outcome = session_outcome(reply)

    assert outcome.kind is OutcomeKind.ERROR
    assert outcome.text == (
        f"the implementing session errored (error_max_turns): {reply.result[-800:]}"
    )


def test_stops_when_blocked_text_without_json() -> None:
    outcome = session_outcome(a_reply("I read the plan.\nBLOCKED: the spec has an open question"))

    assert outcome == Outcome(
        kind=OutcomeKind.STOPPED,
        text="the implementing session stopped: I read the plan.\nBLOCKED: the spec has an"
        " open question",
    )


def test_stops_when_verdict_blocked() -> None:
    result = 'prose\n{"status": "blocked", "summary": "needs an approved plan"}'

    assert session_outcome(a_reply(result)) == Outcome(
        kind=OutcomeKind.STOPPED, text="the implementing session stopped: needs an approved plan"
    )


def test_keeps_tail_when_blocked_verdict_has_no_summary() -> None:
    result = "z" * 900 + '\n{"status": "blocked"}'

    outcome = session_outcome(a_reply(result))

    assert outcome.text == f"the implementing session stopped: {result[-800:]}"


def test_reads_summary_when_done() -> None:
    result = 'Done.\n```\n{"status": "done", "summary": "Adds the parser.", "tests": "make"}\n```'

    assert session_outcome(a_reply(result)) == Outcome(
        kind=OutcomeKind.DONE, text="Adds the parser."
    )


@pytest.mark.parametrize(
    "result",
    ["no verdict at all", '{"status": "done"}', '{"status": "done", "summary": 5}'],
    ids=["prose", "no-summary", "summary-not-text"],
)
def test_leaves_summary_empty_when_verdict_gives_none(result: str) -> None:
    assert session_outcome(a_reply(result)) == Outcome(kind=OutcomeKind.DONE, text="")


def test_names_no_agent_when_reason_built() -> None:
    for reply in (a_reply("BLOCKED: x"), a_reply("x", is_error=True)):
        assert "Agent" not in session_outcome(reply).text
        assert "agent" not in session_outcome(reply).text
