"""``workflows.shadow``: a hub workflow overrides a built-in whose pack has changed since the copy.

Discovery runs a hub workflow over the built-in of its name (ADR 0032), and ``hub sync`` never
refreshes a seeded pack, so after a pin bump a frozen copy hides what the release changed in the
built-in pack, with no other signal. One warning per hub workflow that overrides a built-in whose
pack is not the hub's pack as this release ships it (``WorkflowShadow.identical``, filled by the
generator). A pack as ``hub init`` seeds it is identical and hides nothing, so it is not flagged:
every hub starts with one per built-in. An override in a hub pack of another name gets a fix
that names its file, not the pack, which holds the hub's other workflows. A hub file that does
not load is ``workflows.valid``'s.
"""

import posixpath
from collections.abc import Iterator
from typing import Final

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import RULE_MODULES, WORKFLOWS_SHADOW_RULE, Severity

# Where the platform repository keeps the built-in packs, at each release's tag.
BUILTIN_SOURCE: Final = "packages/core/src/agent_hub/core/workflows/builtin"
MESSAGE: Final = (
    "overrides the built-in workflow {name}, and {pack}/ differs from the built-in"
    " {builtin} pack of this release ({version})"
)
FIX: Final = (
    "compare {pack}/ with {source}/{builtin}/ at the platform's tag v{version} and merge what you"
    " need, or delete {pack}/ to run the built-in"
)
OTHER_PACK_MESSAGE: Final = (
    "overrides the built-in workflow {name} of the built-in {builtin} pack of this release"
    " ({version}) from another pack, {pack}/"
)
OTHER_PACK_FIX: Final = (
    "compare {path} with {source}/{builtin}/ at the platform's tag v{version} and merge what you"
    " need, or delete {path} to run the built-in"
)


def _workflows_shadow(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    for shadow in snapshot.workflow_shadows or ():
        if shadow.identical:
            continue
        words = {
            "name": shadow.name,
            "pack": shadow.pack,
            "path": shadow.path,
            "builtin": shadow.builtin_pack,
            "version": snapshot.running_version,
            "source": BUILTIN_SOURCE,
        }
        same_pack = posixpath.basename(shadow.pack) == shadow.builtin_pack
        message, fix = (MESSAGE, FIX) if same_pack else (OTHER_PACK_MESSAGE, OTHER_PACK_FIX)
        yield WORKFLOWS_SHADOW.finding(
            path=shadow.path, message=message.format(**words), fix=fix.format(**words)
        )


WORKFLOWS_SHADOW: Final = Rule(
    id=WORKFLOWS_SHADOW_RULE,
    severity=Severity.WARNING,
    summary="no hub workflow overrides a built-in whose pack changed since it was copied",
    module=RULE_MODULES.get(WORKFLOWS_SHADOW_RULE),
    reads=frozenset({Read.WORKFLOW_SHADOWS}),
    check=_workflows_shadow,
)
