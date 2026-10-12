"""Secret redaction r1 (D10): one synthetic sample per kind, nested values, properties, clipping.

Every sample is built here from fragments, so no format-valid secret is ever one literal.
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_hub.core.json_form import JsonValue
from agent_hub.core.redaction.redact import (
    KINDS,
    RULESET,
    clip,
    marker,
    redact_text,
    redact_value,
)

_ALNUM = "A1b2C3d4E5f6G7h8"
_PEM_BODY = "\n".join(["MIIEow" + _ALNUM * 4, _ALNUM * 4 + "Zz", "QwErTy" + _ALNUM])


def _github_token() -> str:
    return "gh" + "p_" + _ALNUM * 2 + "xyzw"


def _github_pat() -> str:
    return "github" + "_pat_" + "11AB" + _ALNUM * 3


def _linear_key() -> str:
    return "lin" + "_api_" + _ALNUM * 2 + "Qq"


def _anthropic_key() -> str:
    return "sk" + "-ant-" + "api03-" + _ALNUM * 3


def _openai_key() -> str:
    return "sk" + "-proj-" + _ALNUM * 3


def _openai_legacy_key() -> str:
    return "sk" + "-" + _ALNUM * 3


def _aws_access_key() -> str:
    return "AK" + "IA" + "QWERTY2345ZXCV78"


def _aws_secret_value() -> str:
    return "wJalr" + "XUtnFEMI/K7MDENG/bPxRfiCY" + "EXAMPLEKEY"


def _bearer_value() -> str:
    return "eyJ" + _ALNUM * 2 + ".payload" + _ALNUM


def _pem_block() -> str:
    return "-----BEGIN " + "RSA PRIVATE KEY-----\n" + _PEM_BODY + "\n-----END RSA PRIVATE KEY-----"


def _url_password() -> str:
    return "s3cr3t" + "Passw0rd"


def _secret_value() -> str:
    return "hunter2" + "Hunter2"


# (kind, text holding the secret, the secret part that must never survive)
SAMPLES: tuple[tuple[str, str, str], ...] = (
    ("github token", _github_token(), _github_token()),
    ("github token", _github_pat(), _github_pat()),
    ("linear key", _linear_key(), _linear_key()),
    ("anthropic key", _anthropic_key(), _anthropic_key()),
    ("openai key", _openai_key(), _openai_key()),
    ("openai key", _openai_legacy_key(), _openai_legacy_key()),
    ("aws access key", _aws_access_key(), _aws_access_key()),
    (
        "aws secret",
        "aws_secret_access_key" + " = " + _aws_secret_value(),
        _aws_secret_value(),
    ),
    ("bearer token", "Authorization: Bearer " + _bearer_value(), _bearer_value()),
    ("private key", _pem_block(), _PEM_BODY),
    (
        "url credentials",
        "https://" + "deploy:" + _url_password() + "@git.example.com/acme/repo.git",
        "deploy:" + _url_password(),
    ),
    ("secret", "DB_PASSWORD=" + _secret_value(), _secret_value()),
    ("secret", '{"client_secret": "' + _secret_value() + '"}', _secret_value()),
)
SAMPLE_IDS = [f"{kind}-{index}" for index, (kind, _, _) in enumerate(SAMPLES)]


def _survives(secret: str, text: str, *, window: int = 8) -> bool:
    """Whether any ``window``-long piece of ``secret`` is still in ``text``."""
    pieces = {secret[start : start + window] for start in range(len(secret) - window + 1)}
    return any(piece in text for piece in pieces)


def test_names_every_kind_when_ruleset_is_r1() -> None:
    assert RULESET == "r1"
    assert set(KINDS) == {kind for kind, _, _ in SAMPLES}


@pytest.mark.parametrize(("kind", "text", "secret"), SAMPLES, ids=SAMPLE_IDS)
def test_replaces_whole_value_when_kind_embedded_in_command(
    kind: str, text: str, secret: str
) -> None:
    command = f"run --flag {text} && echo done"

    redacted = redact_text(command)

    assert marker(kind) in redacted
    assert not _survives(secret, redacted)
    assert redacted.startswith("run --flag ")
    assert redacted.endswith(" && echo done")


@pytest.mark.parametrize(("kind", "text", "secret"), SAMPLES, ids=SAMPLE_IDS)
def test_replaces_value_when_kind_nested_in_payload(kind: str, text: str, secret: str) -> None:
    payload: JsonValue = {
        "command": f"curl {text}",
        "path": f"/work/{text}/notes.md",
        "pattern": f"grep {text}",
        "nested": {"list": [1, True, None, f"x {text} y", {"deep": text}]},
    }

    redacted = redact_value(payload)

    flat = repr(redacted)
    assert marker(kind) in flat
    assert not _survives(secret, flat)
    assert isinstance(redacted, dict)
    nested = redacted["nested"]
    assert isinstance(nested, dict)
    assert nested["list"][:3] == [1, True, None]  # type: ignore[index]


def test_keeps_text_when_no_secret_present() -> None:
    text = "uv run pytest -k 'tokenizer' --password-file=./p sk-short task-runner-something"

    assert redact_text(text) == text


def test_keeps_secret_name_when_assignment_redacted() -> None:
    redacted = redact_text("export API_TOKEN=" + _secret_value())

    assert redacted == "export API_TOKEN=[redacted: secret]"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            'export DB_PASSWORD="correct horse & battery; staple" next',
            'export DB_PASSWORD="[redacted: secret]" next',
        ),
        (
            "api_token = 'two words, and more' --flag",
            "api_token = '[redacted: secret]' --flag",
        ),
        (
            'SECRET="esc \\" aped quote here"',
            'SECRET="[redacted: secret]"',
        ),
        ('PASSWORD="no closing quote on this line', 'PASSWORD="[redacted: secret]'),
    ],
)
def test_redacts_to_closing_quote_when_secret_value_quoted(text: str, expected: str) -> None:
    assert redact_text(text) == expected


def test_redacts_rest_of_text_when_private_key_block_unterminated() -> None:
    text = "key: -----BEGIN " + "PRIVATE KEY-----\n" + _PEM_BODY

    redacted = redact_text(text)

    assert redacted == "key: [redacted: private key]"


def test_redacts_keys_when_payload_key_holds_secret() -> None:
    redacted = redact_value({_github_token(): "value"})

    assert redacted == {marker("github token"): "value"}


_SECRET_TEXTS = [text for _, text, _ in SAMPLES]
_SECRETS = [secret for _, _, secret in SAMPLES]


@settings(max_examples=300, deadline=None)
@given(
    before=st.text(max_size=80),
    after=st.text(max_size=80),
    index=st.integers(min_value=0, max_value=len(SAMPLES) - 1),
    offset=st.integers(min_value=0, max_value=80),
)
def test_never_keeps_secret_when_inserted_at_random_offset_property(
    *, before: str, after: str, index: int, offset: int
) -> None:
    surrounding = before + after
    cut = min(offset, len(surrounding))
    text = f"{surrounding[:cut]} {_SECRET_TEXTS[index]} {surrounding[cut:]}"

    redacted = redact_text(text)

    assert not _survives(_SECRETS[index], redacted)
    assert redact_text(redacted) == redacted


@settings(max_examples=500, deadline=None)
@given(text=st.text(max_size=200))
def test_equals_single_pass_when_redacted_twice_property(text: str) -> None:
    once = redact_text(text)

    assert redact_text(once) == once


@settings(max_examples=200, deadline=None)
@given(
    text=st.lists(
        st.sampled_from(
            [*"aB9=:\"' -_/@.[]\n", "token", "Bearer ", "://", "sk-", "ghp_", "[redacted: secret]"]
        ),
        max_size=40,
    ).map("".join)
)
def test_equals_single_pass_when_text_is_near_secret_syntax_property(text: str) -> None:
    once = redact_text(text)

    assert redact_text(once) == once


def test_drops_token_prefix_when_token_starts_at_character_490_truncation() -> None:
    command = "x" * 490 + _github_token() + " --more args"

    clipped = clip(redact_text(command), 500)

    assert len(clipped) < 501
    assert not any(_github_token()[:size] in clipped for size in range(3, len(_github_token())))
    assert "[redacted" not in clipped or clipped.count("[") == clipped.count("]")


def test_keeps_text_when_shorter_than_limit_truncation() -> None:
    assert clip("short", 500) == "short"


def test_cuts_before_marker_when_limit_falls_inside_it_truncation() -> None:
    text = "abc " + marker("secret") + " tail"

    clipped = clip(text, 10)

    assert clipped == "abc …"


def test_ends_with_ellipsis_when_text_cut_truncation() -> None:
    clipped = clip("a" * 20, 10)

    assert clipped == "a" * 9 + "…"
    assert len(clipped) == 10
