import pytest

from agent_hub.core.events.event import EventType
from agent_hub.core.events.payload_keys import (
    ADDED_KEYS_V2,
    COMMON_PAYLOAD_KEYS,
    PAYLOAD_KEYS,
    kept_payload,
)


def test_lists_keys_for_every_type_when_table_read() -> None:
    assert set(PAYLOAD_KEYS) == set(EventType)


def test_drops_body_keys_when_payload_holds_text() -> None:
    payload = {
        "tool": "Bash",
        "command": "make check",
        "tool_input": {"command": "make check"},
        "output": "the whole output",
    }

    kept = kept_payload(EventType.TOOL_CALL, payload)

    assert kept == {"tool": "Bash", "command": "make check"}


def test_keeps_attribution_keys_when_any_type() -> None:
    payload = dict.fromkeys(COMMON_PAYLOAD_KEYS, "x") | {"prompt": "body"}

    for event_type in EventType:
        assert kept_payload(event_type, payload) == dict.fromkeys(COMMON_PAYLOAD_KEYS, "x")


def test_keeps_only_cap_names_when_caps_nested() -> None:
    caps = {"budget": 5.0, "max_turns": 40, "model": "opus", "transport": "api", "prompt": "x"}

    kept = kept_payload(EventType.STEP_START, {"stage": "PICKED", "caps": caps})

    assert kept == {"stage": "PICKED", "caps": {k: v for k, v in caps.items() if k != "prompt"}}


def test_keeps_payload_unchanged_when_every_key_allowed() -> None:
    payload = {"role": "user", "chars": 12, "turn": 1, "slash_command": "/feature"}

    assert kept_payload(EventType.MESSAGE, payload) == payload


@pytest.mark.parametrize(
    ("event_type", "key"),
    [
        (EventType.TOOL_CALL, "skill"),
        (EventType.TOOL_CALL, "to"),
        (EventType.TOOL_RESULT, "error_message"),
        (EventType.TOOL_RESULT, "git_branch"),
        (EventType.MESSAGE, "git_branch"),
        (EventType.LEARNING_ACCEPTED, "pr_url"),
        (EventType.LEARNING_ACCEPTED, "branch"),
        (EventType.LEARNING_REJECTED, "state"),
    ],
    ids=lambda value: str(value),
)
def test_keeps_key_when_key_is_new_in_clarity(event_type: EventType, key: str) -> None:
    assert kept_payload(event_type, {key: "x", "prompt": "body"}) == {key: "x"}


def test_declares_added_keys_when_allow_list_widened() -> None:
    added = {(event_type, key) for event_type, keys in ADDED_KEYS_V2.items() for key in keys}
    not_branch = {pair for pair in added if pair[1] != "git_branch"}

    assert not_branch == {
        (EventType.TOOL_CALL, "skill"),
        (EventType.TOOL_CALL, "to"),
        (EventType.TOOL_RESULT, "error_message"),
    }
    assert {event_type for event_type, key in added if key == "git_branch"} == (
        set(PAYLOAD_KEYS) - {EventType.SESSION_START}
    )
    assert all(key in PAYLOAD_KEYS[event_type] for event_type, key in added)
