"""The lines the CLI prints about declared environments (docs/design/environments.md).

``production_line`` is the one explicit line a production environment gets wherever a command
names it (``hub sync``, later ``hub setup`` and ``hub env``): its name, its effective access and
the file that access comes from. ``production_lines`` gives one per production environment of an
effective view, committed ones first. Only the ``production`` flag counts, never a name.

``brief_block`` is the session brief's Environments block: each environment with its access,
``PRODUCTION``, source and credential names, each service's endpoint per environment, then the
blocked words; at most ``MAX_BLOCK_LINES`` lines and ``MAX_BLOCK_CHARS`` characters, then a line
naming how many more. Names and words are code spans (their shapes hold no backtick); a
description, url, resource or note is the project's free text, read by the agent: cut at
``MAX_FREE_TEXT_CHARS`` (a url keeps its own bound) and escaped, so it never reads as Markdown.
"""

import re
from collections.abc import Iterator
from typing import Final

from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    SourcedEndpoint,
)
from agent_hub.core.hub_config.environments import Credentials

BRIEF_HEADING: Final = "## Environments"
MAX_BLOCK_LINES: Final = 60
MAX_BLOCK_CHARS: Final = 2000
MAX_FREE_TEXT_CHARS: Final = 80
ENDPOINTS_LEAD: Final = "Endpoints:"
WORDS_LEAD: Final = "Blocked words (the guard denies them): "
_MORE: Final = "… {count} more: ./hub env list"
_MARKDOWN_SIGNIFICANT: Final = re.compile(r"([\\`*_\[\]<>#|~])")


def production_line(name: str, access: str, source: str) -> str:
    """``production environment: <name> (access <access>, <source>)``."""
    return f"production environment: {name} (access {access}, {source})"


def production_lines(view: EffectiveEnvironments) -> tuple[str, ...]:
    """One line per production environment of ``view``, in its order."""
    return tuple(
        production_line(environment.name, environment.access, environment.source)
        for environment in view.environments
        if environment.production
    )


def escaped_text(text: str) -> str:
    """``text`` with a backslash before each Markdown-significant character."""
    return _MARKDOWN_SIGNIFICANT.sub(r"\\\1", text)


def brief_block(view: EffectiveEnvironments) -> tuple[str, ...]:
    """The brief's Environments block of ``view``; empty when it has no environment."""
    if not view.environments:
        return ()
    lines = [*_environment_lines(view), *_endpoint_lines(view)]
    if view.blocked_words:
        lines.append(WORDS_LEAD + ", ".join(f"`{entry.value}`" for entry in view.blocked_words))
    return (BRIEF_HEADING, *_bounded(lines))


def _environment_lines(view: EffectiveEnvironments) -> Iterator[str]:
    for environment in view.environments:
        flags = ", PRODUCTION" if environment.production else ""
        line = f"- `{environment.name}` ({environment.access}{flags}, {environment.source})"
        if environment.description:
            line += f": {_free_text(environment.description)}"
        yield line + _credentials(environment.credentials)


def _endpoint_lines(view: EffectiveEnvironments) -> Iterator[str]:
    lines = [
        f"- `{service.repo}/{service.name}` on `{endpoint.environment}`: {_target(endpoint)}"
        for service in view.services
        for endpoint in service.endpoints
    ]
    if lines:
        yield ENDPOINTS_LEAD
        yield from lines


def _target(sourced: SourcedEndpoint) -> str:
    endpoint = sourced.endpoint
    parts = []
    if endpoint.url:
        parts.append(escaped_text(endpoint.url))
    if endpoint.resource:
        parts.append(f"resource {_free_text(endpoint.resource)}")
    target = ", ".join(parts)
    if endpoint.note:
        target += f"; note: {_free_text(endpoint.note)}"
    return target + _credentials(endpoint.credentials)


def _credentials(credentials: Credentials | None) -> str:
    """``; credentials: AWS profile `p`, variables `A`, `B```: names only, never a value."""
    if credentials is None:
        return ""
    names = []
    if credentials.aws_profile:
        names.append(f"AWS profile `{credentials.aws_profile}`")
    if credentials.env:
        names.append("variables " + ", ".join(f"`{name}`" for name in credentials.env))
    return f"; credentials: {', '.join(names)}" if names else ""


def _free_text(text: str) -> str:
    cut = text if len(text) <= MAX_FREE_TEXT_CHARS else text[:MAX_FREE_TEXT_CHARS] + "…"
    return escaped_text(cut)


def _bounded(lines: list[str]) -> list[str]:
    """``lines`` whole when the block fits, else the most that fit with the ``more`` line."""
    if len(lines) <= MAX_BLOCK_LINES and _size(lines) <= MAX_BLOCK_CHARS:
        return lines
    kept = lines[:MAX_BLOCK_LINES]
    while kept and _size([*kept, _more(len(lines) - len(kept))]) > MAX_BLOCK_CHARS:
        kept.pop()
    return [*kept, _more(len(lines) - len(kept))]


def _size(lines: list[str]) -> int:
    return len("\n".join((BRIEF_HEADING, *lines)))


def _more(count: int) -> str:
    return _MORE.format(count=count)
