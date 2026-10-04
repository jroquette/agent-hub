"""``secrets.config`` and ``attribution.ai`` (spec AC-11.23, plan E11).

The port of the hub's old config lint script's text checks. Each line (``text_lines``, E29)
of the scanned files is searched for the old lint's nine secret shapes and three AI-attribution
patterns; a finding names the kind at the file's line, never the text it matched.

The scanned files: the instruction files, the plugins' agent and skill files, and those of
``.mcp.json``, ``.claude/settings.json`` (not ``settings.project.json``, which merges into it at
every sync, E11), ``CONTRIBUTING.md``, ``.github/PULL_REQUEST_TEMPLATE.md`` and
``.github/pull_request_template.md`` that are among the hub's files (E31: listed, or a fixed path
present) as regular files; a link is never followed (D3). An instruction or plugin file that is
not text is the runner's to report (E28); every other file that is not text is skipped (Q-19).

Each shape runs in time linear in the line: the old lint's JWT and co-author patterns retried a
run from every start and are rewritten so each start is tried once, with the same matches.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Final

from agent_hub.core.doctor.config_lint import (
    file_text,
    instruction_files,
    known_paths,
    plugin_files,
    text_lines,
)
from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot, HubFiles
from agent_hub.core.hub_config.doctor_rules import (
    ATTRIBUTION_AI_RULE,
    RULE_MODULES,
    SECRETS_CONFIG_RULE,
    Severity,
)
from agent_hub.core.hub_config.model import PREFIX_PLACEHOLDER, HubConfig
from agent_hub.core.hub_config.versions import cut_echo

# The files read beyond the instruction and plugin files, when among the hub's files.
EXTRA_FILES: Final = (
    ".mcp.json",
    ".claude/settings.json",
    "CONTRIBUTING.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/pull_request_template.md",
)

ROTATE_FIX: Final = "remove it and rotate the credential; reference an env var name instead"


@dataclass(frozen=True, kw_only=True, slots=True)
class Shape:
    """What a line must hold to be flagged, and the kind a finding names.

    ``patterns`` are the ones ``matches`` searches with; none anchors at the text's start or end,
    so a line's match is also one of the whole text (the pre-filter in ``_flagged``).
    """

    kind: str
    patterns: tuple[re.Pattern[str], ...]
    matches: Callable[[str], bool]


def _searched(kind: str, pattern: str) -> Shape:
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
    _searched("JWT", _JWT),
    _searched("AWS access key", r"AKIA[0-9A-Z]{16}"),
    _searched("private key", r"-{5}BEGIN [A-Z ]*PRIVATE KEY-{5}"),
    _searched("API key", r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{16,}"),
    _searched("API key", r"\bsk-[A-Za-z0-9_-]{20,}"),
    _searched("GitHub token", r"\bghp_[A-Za-z0-9]{30,}"),
    _searched("Linear API key", r"\blin_api_[A-Za-z0-9]{20,}"),
    _searched(
        "credential assignment",
        r"(?i)\b[A-Z_]*(?:PASSWORD|SECRET|TOKEN|ENCRYPTION_KEY)\s*=\s*['\"]?[^\s'\"<>$`{]{6,}",
    ),
    _searched("Fernet-like key", r"\b[A-Za-z0-9_-]{43}=(?![A-Za-z0-9])"),
)

_CO_AUTHOR_TAG: Final = re.compile(r"(?i)co-authored-by:")
_CO_AUTHOR_NAMED: Final = re.compile(r"(?i)co-authored-by:\s*(?:claude|copilot)")
_AI_VENDOR: Final = re.compile(r"(?i)anthropic|openai")


def _names_ai_co_author(text: str) -> bool:
    """The old ``co-authored-by:\\s*(claude|.*anthropic|.*openai|copilot)``, linear.

    The old ``.*`` rescanned the rest of the line from each tag; a vendor named anywhere after
    the first tag's colon is the same match, so the rest is searched once.
    """
    tag = _CO_AUTHOR_TAG.search(text)
    if tag is None:
        return False
    return (
        _CO_AUTHOR_NAMED.search(text, tag.start()) is not None
        or _AI_VENDOR.search(text, tag.end()) is not None
    )


ATTRIBUTIONS: Final = (
    Shape(
        kind="AI co-author trailer",
        patterns=(_CO_AUTHOR_TAG, _CO_AUTHOR_NAMED, _AI_VENDOR),
        matches=_names_ai_co_author,
    ),
    _searched(
        '"Generated with Claude Code"',
        r"(?i)generated with \[?claude code",
    ),
    _searched("`claude/` branch prefix", r"\bclaude/(?:<|[a-z0-9-]+-)"),
)


def _secrets_config(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    for path, line, kind in _flagged(snapshot.hub, config=snapshot.hub_config, shapes=SECRETS):
        yield SECRETS_CONFIG.finding(
            path=path, line=line, message=f"possible secret ({kind})", fix=ROTATE_FIX
        )


def _attribution_ai(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    config = snapshot.hub_config
    fix = f"branches are `{cut_echo(branch_shape(config))}`; commits/PRs carry no AI trailer"
    for path, line, kind in _flagged(snapshot.hub, config=config, shapes=ATTRIBUTIONS):
        yield ATTRIBUTION_AI.finding(
            path=path, line=line, message=f"AI attribution: {kind}", fix=fix
        )


def branch_shape(config: HubConfig) -> str:
    """``<branch_prefix><team lowercase>-<N>-<desc>``, the branch names ``hub.json`` sets.

    A hub that sets no prefix (each developer has their own) shows ``<prefix>`` in its place.
    """
    prefix = config.project.branch_prefix or PREFIX_PLACEHOLDER
    return f"{prefix}{config.tracker.team.lower()}-<N>-<desc>"


def _flagged(
    hub: HubFiles, *, config: HubConfig, shapes: tuple[Shape, ...]
) -> Iterator[tuple[str, int, str]]:
    """Each scanned file's line and the kinds it holds: once per kind, in shape order."""
    for path in _scanned_paths(hub, config=config):
        text = file_text(hub.entries.get(path))
        if not isinstance(text, str):
            continue
        # A shape a line matches also matches the whole text (no shape can need the line's end
        # or start to be the text's), so most files are passed over by one search per shape.
        present = tuple(shape for shape in shapes if shape.matches(text))
        if not present:
            continue
        for number, line in enumerate(text_lines(text), start=1):
            kinds = dict.fromkeys(shape.kind for shape in present if shape.matches(line))
            for kind in kinds:
                yield path, number, kind


def _scanned_paths(hub: HubFiles, *, config: HubConfig) -> list[str]:
    """The files the text rules read, once each, sorted by path."""
    extras = frozenset(EXTRA_FILES)
    found = {path for path in known_paths(hub, config=config) if path in extras}
    return sorted({*instruction_files(hub), *plugin_files(hub), *found})


SECRETS_CONFIG: Final = Rule(
    id=SECRETS_CONFIG_RULE,
    severity=Severity.ERROR,
    summary="no secret-shaped text in agent instructions, plugin files or config",
    module=RULE_MODULES.get(SECRETS_CONFIG_RULE),
    reads=frozenset({Read.INSTRUCTION_FILES, Read.PLUGIN_FILES}),
    check=_secrets_config,
)
ATTRIBUTION_AI: Final = Rule(
    id=ATTRIBUTION_AI_RULE,
    severity=Severity.ERROR,
    summary="no AI co-author trailer, Claude Code credit or claude/ branch in agent config",
    module=RULE_MODULES.get(ATTRIBUTION_AI_RULE),
    reads=frozenset({Read.INSTRUCTION_FILES, Read.PLUGIN_FILES}),
    check=_attribution_ai,
)
