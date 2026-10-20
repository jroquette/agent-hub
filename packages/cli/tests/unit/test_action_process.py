"""Redaction of injected credential values from what an action prints (AC-350.9)."""

from agent_hub.cli.action_process import redacted, redacted_value


def test_replaces_merged_span_when_redacted_values_overlap() -> None:
    credentials = {"DEMO_A": "abcdef", "DEMO_B": "defghi"}

    assert redacted("xx-abcdefghi-yy", credentials) == "xx-<credential DEMO_A>-yy"
    assert redacted("defghi then abcdef", credentials) == (
        "<credential DEMO_B> then <credential DEMO_A>"
    )


def test_keeps_short_values_when_redacted_values_under_four_characters() -> None:
    assert redacted("pin 123 and 1234", {"DEMO_PIN": "123", "DEMO_CODE": "1234"}) == (
        "pin 123 and <credential DEMO_CODE>"
    )


def test_redacts_keys_and_numbers_when_redacted_value_walked() -> None:
    value = {"k-1234-k": [12345678, True, None, "a1234"], "n": 5.5}

    assert redacted_value(value, {"DEMO_CODE": "1234"}) == {
        "k-<credential DEMO_CODE>-k": [
            "<credential DEMO_CODE>5678",
            True,
            None,
            "a<credential DEMO_CODE>",
        ],
        "n": 5.5,
    }
