"""The rules an eval's scope follows (AGH-136 S6, S7): pure, no I/O.

The AC id, commit and re-run patterns, the ticket aliases (a plan key and its tracker id are the
same ticket) and the expansion of a named scope to AC ids. ``feature_evals`` reads eval records
with them; the agent output checks hold an eval's JSON to the same rules.
"""

import re
from collections.abc import Iterable
from typing import Final, Literal

from agent_hub.core.features.feature_record import PlannedTicket, RecordAc

AC_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
COMMIT_PATTERN: Final = re.compile(r"[0-9a-f]{7,40}")
# A re-run of a delivery ends in ``-r2``, ``-r3``...; ``group(1)`` is its number.
RERUN_PATTERN: Final = re.compile(r"-r([1-9][0-9]{0,3})$")
_ALL: Final = "all"


def ticket_aliases(tickets: Iterable[PlannedTicket]) -> dict[str, frozenset[str]]:
    """Each ticket ref (upper case) with every ref of the same ticket (its key and its id)."""
    aliases: dict[str, frozenset[str]] = {}
    for ticket in tickets:
        refs = frozenset(ref.upper() for ref in (ticket.key, ticket.id) if ref is not None)
        for ref in refs:
            aliases[ref] = aliases.get(ref, frozenset()) | refs
    return aliases


def named_scope(
    *,
    acs: tuple[str, ...] | Literal["all"],
    tickets: tuple[str, ...],
    live: tuple[RecordAc, ...],
    aliases: dict[str, frozenset[str]],
) -> tuple[str, ...] | None:
    """The AC ids a scope names: ``all`` is every ``live`` AC, a list of ``acs`` is as named,
    else the ``live`` ACs of the ``tickets`` (through ``aliases``); None when it names nothing."""
    if acs == _ALL:
        return tuple(ac.id for ac in live)
    if acs:
        return acs
    if tickets:
        named: set[str] = set()
        for ref in tickets:
            named |= aliases.get(ref.upper(), frozenset({ref.upper()}))
        return tuple(ac.id for ac in live if ac.ticket is not None and ac.ticket.upper() in named)
    return None
