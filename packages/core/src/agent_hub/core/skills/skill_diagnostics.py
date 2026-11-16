"""What a skill or agent file breaks, as advice, and what it costs in context (AGH-164, D5, P6,
P8).

Diagnostics never block: the item is still listed and shown. Their messages are one line and
name only the item's own names, never a path. Context cost is approximate: characters / 4,
rounded up.
"""

import math
import re
from collections.abc import Iterable
from typing import Final

from agent_hub.core.redaction.redact import clip
from agent_hub.core.skills.skill_view import (
    SEVERITY,
    ContextCost,
    Diagnostic,
    DiagnosticCode,
    ItemKind,
    SkillDocument,
    SkillFrontmatterValue,
)

# The Agent Skills name rule: lowercase letters and digits in hyphen-separated runs.
NAME_RULE: Final = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME_CHARS: Final = 64
MAX_DESCRIPTION_CHARS: Final = 1024
MAX_BODY_LINES: Final = 500
CHARS_PER_TOKEN: Final = 4
DISABLE_MODEL_INVOCATION: Final = "disable-model-invocation"

_SHOWN_CHARS: Final = 80
_SKILL_REFERENCE: Final = "/"


def _shown(value: str) -> str:
    return clip(" ".join(value.split()), _SHOWN_CHARS)


def _diagnostic(code: DiagnosticCode, message: str) -> Diagnostic:
    return Diagnostic(code=code, severity=SEVERITY[code], message=message)


def _values(document: SkillDocument) -> dict[str, SkillFrontmatterValue]:
    return {pair.key: pair.value for pair in document.pairs}


def _text(value: SkillFrontmatterValue | None) -> str | None:
    return value if isinstance(value, str) else None


def _name_diagnostics(
    name: SkillFrontmatterValue | None, *, kind: ItemKind, file_name: str
) -> list[Diagnostic]:
    if name is None:
        return []
    text = _text(name)
    if text is None or len(text) > MAX_NAME_CHARS or not NAME_RULE.match(text):
        shown = _shown(text) if text is not None else "(not a single value)"
        return [
            _diagnostic(
                DiagnosticCode.NAME_INVALID,
                f"name {shown} is not lowercase letters, digits and hyphens"
                f" of at most {MAX_NAME_CHARS} characters",
            )
        ]
    if text != file_name:
        where = "folder" if kind is ItemKind.SKILL else "file name"
        return [
            _diagnostic(
                DiagnosticCode.NAME_MISMATCH,
                f"name {text} differs from its {where} {_shown(file_name)}",
            )
        ]
    return []


def _description_diagnostics(description: SkillFrontmatterValue | None) -> list[Diagnostic]:
    text = _text(description)
    if text is None or not text.strip():
        return [
            _diagnostic(
                DiagnosticCode.DESCRIPTION_MISSING,
                "no description: Claude Code cannot tell when to use it",
            )
        ]
    if len(text) > MAX_DESCRIPTION_CHARS:
        return [
            _diagnostic(
                DiagnosticCode.DESCRIPTION_TOO_LONG,
                f"description is {len(text)} characters, over {MAX_DESCRIPTION_CHARS}",
            )
        ]
    return []


def _reference_diagnostics(unresolved: Iterable[str]) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    for reference in unresolved:
        what = "skill" if reference.startswith(_SKILL_REFERENCE) else "agent"
        found.append(
            _diagnostic(
                DiagnosticCode.REFERENCE_NOT_FOUND,
                f"{what} {_shown(reference)} is not in this hub's catalog",
            )
        )
    return found


def diagnose(
    document: SkillDocument,
    *,
    kind: ItemKind,
    file_name: str,
    known_keys: frozenset[str],
    unresolved: Iterable[str],
) -> tuple[Diagnostic, ...]:
    """The diagnostics of a skill (``file_name`` = its folder) or agent (its file stem).

    An unparseable frontmatter gives only ``frontmatter_unparseable``. Otherwise, in order: the
    name rule and the name against ``file_name`` (when a name is set), the description (missing
    or over 1024 characters), a body over 500 lines, one ``reference_not_found`` per
    ``unresolved`` name (``/name`` a skill, else an agent), one ``unknown_key`` per key not in
    ``known_keys``.
    """
    if document.problem is not None:
        return (
            _diagnostic(
                DiagnosticCode.FRONTMATTER_UNPARSEABLE,
                f"frontmatter not read: {_shown(document.problem)}",
            ),
        )
    values = _values(document)
    found = [
        *_name_diagnostics(values.get("name"), kind=kind, file_name=file_name),
        *_description_diagnostics(values.get("description")),
    ]
    lines = len(document.body.splitlines())
    if lines > MAX_BODY_LINES:
        found.append(
            _diagnostic(
                DiagnosticCode.BODY_TOO_LONG, f"body is {lines} lines, over {MAX_BODY_LINES}"
            )
        )
    found.extend(_reference_diagnostics(unresolved))
    found.extend(
        _diagnostic(
            DiagnosticCode.UNKNOWN_KEY, f"{_shown(pair.key)} is not understood by Claude Code"
        )
        for pair in document.pairs
        if pair.key not in known_keys
    )
    return tuple(found)


def _tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def model_can_invoke(document: SkillDocument) -> bool:
    """False when the skill sets ``disable-model-invocation: true``."""
    flag = _text(_values(document).get(DISABLE_MODEL_INVOCATION))
    return flag is None or flag.strip().lower() != "true"


def context_cost(document: SkillDocument, *, kind: ItemKind) -> ContextCost:
    """Approximate tokens (P8): ``always_loaded_tokens`` from the description (0 for a skill the
    model cannot invoke), ``on_invoke_tokens`` from the body (an agent's system prompt)."""
    description = _text(_values(document).get("description")) or ""
    always = kind is not ItemKind.SKILL or model_can_invoke(document)
    return ContextCost(
        always_loaded_tokens=_tokens(description) if always else 0,
        on_invoke_tokens=_tokens(document.body),
    )
