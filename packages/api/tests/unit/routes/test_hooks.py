import pytest

from agent_hub.api.routes.hooks import json_depth_exceeds


@pytest.mark.parametrize(
    ("body", "exceeds"),
    [
        (b'{"a": [1, {"b": 2}]}', False),
        (b"[" * 64 + b"]" * 64, False),
        (b"[" * 65 + b"]" * 65, True),
        (b'{"a": "' + b"[" * 100 + b'"}', False),
        (b'{"a": "\\"' + b"[" * 100 + b'"}', False),
        (b'{"a": "\\\\"' + b", " + b"[" * 70, True),
    ],
)
def test_measures_nesting_outside_strings_when_maps_body_checked(
    *, body: bytes, exceeds: bool
) -> None:
    assert json_depth_exceeds(body) is exceeds


def test_counts_depth_against_given_limit_when_limit_given() -> None:
    assert json_depth_exceeds(b"[[[]]]", limit=2)
