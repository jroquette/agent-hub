from agent_hub.core.events.event import EventType
from agent_hub.core.events.payload_keys import (
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
