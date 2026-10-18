"""The secret shapes: what text must hold to look like a credential, and the kind it names.

Shared by doctor's ``secrets.config`` (``doctor/text_rules.py``) and ``hub.json``'s environments
and services (``hub_config/environments.py``), which reject such text. This module imports
nothing of either, so neither import pulls in the other.

Each shape runs in time linear in the text: the old lint's JWT pattern retried a run from every
start and is rewritten so each start is tried once, with the same matches.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, kw_only=True, slots=True)
class Shape:
    """What a line must hold to be flagged, and the kind a finding names.

    ``patterns`` are the ones ``matches`` searches with; none anchors at the text's start or end,
    so a line's match is also one of the whole text (the pre-filter in ``_flagged``).
    """

    kind: str
    patterns: tuple[re.Pattern[str], ...]
    matches: Callable[[str], bool]


def searched_shape(kind: str, pattern: str) -> Shape:
    """A shape that one pattern's search decides."""
    compiled = re.compile(pattern)
    return Shape(
        kind=kind,
        patterns=(compiled,),
        matches=lambda text: compiled.search(text) is not None,
    )


# A run of the JWT's characters, which holds its ``eyJ`` and first part.
_JWT_CHARACTER: Final = "[A-Za-z0-9_-]"
# The old ``eyJ[C]{15,}\.[C]{15,}`` retried the run after each ``eyJ`` in it, quadratic in the
# run. The first part ends where its run does (``.`` is not in it), so the first ``eyJ`` of the
# run, which leaves the most after it, decides: each run is tried once, from its start.
_JWT: Final = (
    rf"(?<!{_JWT_CHARACTER})(?>{_JWT_CHARACTER}*?eyJ){_JWT_CHARACTER}{{15,}}+\."
    rf"{_JWT_CHARACTER}{{15}}"
)

# The old lint's shapes, in its order; two shapes share the kind ``API key``.
SECRETS: Final = (
    searched_shape("JWT", _JWT),
    searched_shape("AWS access key", r"AKIA[0-9A-Z]{16}"),
    searched_shape("private key", r"-{5}BEGIN [A-Z ]*PRIVATE KEY-{5}"),
    searched_shape("API key", r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{16,}"),
    searched_shape("API key", r"\bsk-[A-Za-z0-9_-]{20,}"),
    searched_shape("GitHub token", r"\bghp_[A-Za-z0-9]{30,}"),
    searched_shape("Linear API key", r"\blin_api_[A-Za-z0-9]{20,}"),
    searched_shape(
        "credential assignment",
        r"(?i)\b[A-Z_]*(?:PASSWORD|SECRET|TOKEN|ENCRYPTION_KEY)\s*=\s*['\"]?[^\s'\"<>$`{]{6,}",
    ),
    searched_shape("Fernet-like key", r"\b[A-Za-z0-9_-]{43}=(?![A-Za-z0-9])"),
)


def secret_kind(text: str) -> str | None:
    """The kind of the first secret shape ``text`` holds, in ``SECRETS`` order; None if none."""
    return next((shape.kind for shape in SECRETS if shape.matches(text)), None)
