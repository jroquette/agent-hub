"""Redaction rule set r1 (D10): known secret shapes become ``[redacted: <kind>]`` markers.

The whole value is replaced, never part of it; only the context that names it (a variable name,
a URL scheme, ``Bearer``) is kept. Private key blocks go first (their bodies would otherwise feed
the other rules), then the vendor token shapes, then the context rules. The rules repeat until
the text no longer changes, so redacting twice equals redacting once. ``clip`` shortens text only
after redaction and never cuts inside a marker, so a cut never leaves a prefix of a secret that
no rule would recognise any more.

Every pattern runs in linear time on its input: names and repeats are bounded, and no
quantifier is nested in another.
"""

import re
from functools import partial
from typing import Final

from agent_hub.core.ingestion.ingestion_status import REDACTION_RULESET
from agent_hub.core.json_form import JsonValue

RULESET: Final = REDACTION_RULESET
ELLIPSIS: Final = "…"
# Each pass only turns matches into markers, which no rule matches, so a second pass settles any
# text in practice; the bound keeps a pathological input from looping.
_MAX_PASSES: Final = 8
_MARKER: Final = re.compile(r"\[redacted: [a-z ]+\]")
# A value that is already a marker is left as it is.
_NOT_MARKER: Final = r"(?!\[redacted: )"
_NAME_WORD: Final = r"(?:secret|token|password|passwd|api_key|apikey|private_key|credential)"
_NAME_CHARS: Final = r"[A-Za-z0-9_.\-]"
# ``<name holding a secret word> =``, the context kept before an assigned value.
_ASSIGNED: Final = (
    rf"(?<!{_NAME_CHARS}){_NAME_CHARS}{{0,64}}?{_NAME_WORD}{_NAME_CHARS}{{0,64}}\s*=\s*"
)


def marker(kind: str) -> str:
    """The text that replaces a secret of ``kind``."""
    return f"[redacted: {kind}]"


# (kind, pattern): the optional groups ``head`` and ``tail`` are context kept around the marker.
_RULES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "private key",
        re.compile(
            r"-----BEGIN (?:[A-Z0-9]+ ){0,4}PRIVATE KEY-----"
            r"(?:.*?-----END (?:[A-Z0-9]+ ){0,4}PRIVATE KEY-----|.*)",
            re.DOTALL,
        ),
    ),
    ("github token", re.compile(r"gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,}")),
    ("linear key", re.compile(r"lin_api_[A-Za-z0-9]{8,}")),
    ("anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")),
    ("openai key", re.compile(r"(?<![A-Za-z0-9_\-])sk-(?:proj-)?[A-Za-z0-9_\-]{16,}")),
    ("aws access key", re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}")),
    (
        "url credentials",
        re.compile(r"(?P<head>[A-Za-z][A-Za-z0-9+.\-]{0,31}://)[^/\s:@\[]+:[^/\s@]+(?P<tail>@)"),
    ),
    (
        "aws secret",
        re.compile(
            rf"(?P<head>aws_secret_access_key[\"']?\s*[=:]\s*[\"']?){_NOT_MARKER}[A-Za-z0-9/+=]{{16,}}",
            re.IGNORECASE,
        ),
    ),
    (
        "bearer token",
        re.compile(rf"(?P<head>\bbearer\s+){_NOT_MARKER}[A-Za-z0-9._~+/=\-]{{8,}}", re.IGNORECASE),
    ),
    (
        "secret",
        re.compile(
            rf"(?P<head>\"[^\"\\\n]{{0,64}}?{_NAME_WORD}[^\"\\\n]{{0,64}}\"\s*:\s*\")"
            rf"{_NOT_MARKER}(?:[^\"\\\n]|\\.){{8,}}(?P<tail>\")",
            re.IGNORECASE,
        ),
    ),
    # A quoted value is replaced up to its closing quote (or the end of the line without one),
    # spaces and all; an unquoted one up to the first space or separator.
    (
        "secret",
        re.compile(
            rf"(?P<head>{_ASSIGNED}\"){_NOT_MARKER}(?:[^\"\\\n]|\\.){{8,}}(?P<tail>\")?",
            re.IGNORECASE,
        ),
    ),
    (
        "secret",
        re.compile(rf"(?P<head>{_ASSIGNED}'){_NOT_MARKER}[^'\n]{{8,}}(?P<tail>')?", re.IGNORECASE),
    ),
    (
        "secret",
        re.compile(
            rf"(?P<head>{_ASSIGNED}[\"']?){_NOT_MARKER}[^\s\"'&;,]{{8,}}",
            re.IGNORECASE,
        ),
    ),
)

KINDS: Final = tuple(dict.fromkeys(kind for kind, _ in _RULES))


def redact_text(text: str) -> str:
    """``text`` with every secret r1 recognises replaced by its kind's marker."""
    for _ in range(_MAX_PASSES):
        redacted = _one_pass(text)
        if redacted == text:
            return redacted
        text = redacted
    return text


def redact_value(value: JsonValue) -> JsonValue:
    """``value`` with every string in it redacted, keys included, at any depth."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, dict):
        return {redact_text(key): redact_value(item) for key, item in value.items()}
    return value


def clip(text: str, limit: int) -> str:
    """``text`` cut to at most ``limit`` characters, ending in ``…`` when cut.

    Call it on redacted text: a cut that would fall inside a marker moves to the marker's start.
    """
    if len(text) <= limit:
        return text
    cut = max(limit - len(ELLIPSIS), 0)
    for found in _MARKER.finditer(text):
        if found.start() < cut < found.end():
            cut = found.start()
            break
    return text[:cut] + ELLIPSIS


def _one_pass(text: str) -> str:
    for kind, pattern in _RULES:
        text = pattern.sub(partial(_replacement, kind=kind), text)
    return text


def _replacement(found: re.Match[str], *, kind: str) -> str:
    groups = found.groupdict()
    return (groups.get("head") or "") + marker(kind) + (groups.get("tail") or "")
