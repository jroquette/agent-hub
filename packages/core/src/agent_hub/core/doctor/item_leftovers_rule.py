"""``items.leftovers``: no temp-named entry an interrupted item write left beside a unit (AGH-297).

``hub web``'s Publish and Restore write a unit through ``.<name>.hub-tmp-<8 hex>`` entries
beside it (``generator/hub_item_writer.py``): a file's temp file, a skill folder's stage and
its old folder. A crash mid-write, a roll back that failed, or an old folder that could not be
removed leaves one behind, and a skill's hidden files (which no version records) may then be
only there. ``hub init`` and ``hub sync`` remove only temp-shaped files and links in the folders
they plan, so this rule lists every temp-shaped entry (folder, file or link) directly in the
item folders, which the generator scans without following a link: ``.claude``,
``.claude/skills``, ``.claude/agents``, ``plugin/<p>/skills``, ``plugin/<p>/agents``,
``plugin/<p>/hooks``, ``plugin/<p>/scripts`` and ``workflows/<pack>``, and ``.hub-drafts``, where
a Publish's draft removal renames the draft aside before removing it (AGH-298). One warning
per entry, in path order, at most 10, then one ``N more`` at the hub root. It reads nothing
inside an entry and removes nothing.
"""

from collections.abc import Iterator
from typing import Final

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import ITEM_LEFTOVERS_RULE, RULE_MODULES, Severity

MAX_FINDINGS: Final = 10
MESSAGE: Final = "temporary entry left by an interrupted item write"
FIX: Final = (
    "check it holds nothing you need (a skill's hidden files may be only there), then remove it"
)


def _item_leftovers(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    leftovers = snapshot.item_leftovers or ()
    for path in leftovers[:MAX_FINDINGS]:
        yield ITEM_LEFTOVERS.finding(path=path, message=MESSAGE, fix=FIX)
    more = len(leftovers) - MAX_FINDINGS
    if more > 0:
        shown = MESSAGE if more == 1 else f"{MESSAGE}s"
        yield ITEM_LEFTOVERS.finding(
            path=".", message=f"{more} more {shown} besides the {MAX_FINDINGS} shown", fix=FIX
        )


ITEM_LEFTOVERS: Final = Rule(
    id=ITEM_LEFTOVERS_RULE,
    severity=Severity.WARNING,
    summary="no temporary entry of an interrupted item write beside a unit",
    module=RULE_MODULES.get(ITEM_LEFTOVERS_RULE),
    reads=frozenset({Read.ITEM_FOLDERS}),
    check=_item_leftovers,
)
