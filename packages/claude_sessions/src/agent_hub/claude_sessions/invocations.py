"""What a user message names as the CLI reads it: the composer's short names made exact.

The composer offers a skill as ``/<name>`` and a subagent as ``/agent-<name>``, without the
plugin prefix the CLI gives what a plugin brings (``hub-workflow:fix``). Before a message reaches
the CLI:

- a leading ``/<name>`` that is not a command of the session, but the suffix of exactly one
  ``<plugin>:<name>`` command, becomes ``/<plugin>:<name>``;
- each ``/agent-<name>`` at the start or after a space becomes the CLI's mention
  ``@agent-<name>``, with ``<name>`` made exact the same way against the session's agents.

Anything else, an unknown name included, is left as typed.
"""

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_NAME = r"[\w:.@-]+"
_LEADING_COMMAND = re.compile(rf"^/({_NAME})(?=\s|$)")
_AGENT_COMMAND = re.compile(rf"(^|\s)/agent-({_NAME})(?=\s|$)")


@dataclass(frozen=True)
class SessionNames:
    """The commands (skills included) and agents a session's CLI knows, by exact name."""

    commands: frozenset[str] = frozenset()
    agents: frozenset[str] = frozenset()

    @classmethod
    def from_server_info(cls, info: Mapping[str, Any] | None) -> SessionNames:
        """The names of the CLI's ``initialize`` answer (``commands`` and ``agents``, each a
        list of objects with a ``name``); what is missing or malformed is ignored."""
        if info is None:
            return cls()
        return cls(commands=_names(info.get("commands")), agents=_names(info.get("agents")))


def _names(items: object) -> frozenset[str]:
    if not isinstance(items, Sequence) or isinstance(items, str):
        return frozenset()
    names = (item.get("name") if isinstance(item, Mapping) else item for item in items)
    return frozenset(name for name in names if isinstance(name, str) and name)


def _exact(name: str, known: Collection[str]) -> str:
    """``name`` itself when known or already prefixed; else the one ``<plugin>:<name>``."""
    if name in known or ":" in name:
        return name
    matches = [candidate for candidate in known if candidate.endswith(f":{name}")]
    return matches[0] if len(matches) == 1 else name


def cli_prompt(text: str, names: SessionNames) -> str:
    """``text`` with its skill and agent short names as the CLI reads them."""

    def command(match: re.Match[str]) -> str:
        return f"/{_exact(match[1], names.commands)}"

    def agent(match: re.Match[str]) -> str:
        return f"{match[1]}@agent-{_exact(match[2], names.agents)}"

    if not text.startswith("/agent-"):
        text = _LEADING_COMMAND.sub(command, text, count=1)
    return _AGENT_COMMAND.sub(agent, text)
