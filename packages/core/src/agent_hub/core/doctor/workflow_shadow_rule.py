"""``workflows.shadow``: a hub workflow overrides a built-in, identical to it or not.

Discovery runs a hub workflow over the built-in of its name (ADR 0032), and ``hub sync`` never
refreshes a seeded pack, so after a pin bump a frozen copy hides what the release changed in the
built-in pack, with no other signal. One warning per hub workflow that overrides a built-in,
saying whether its pack is the hub's pack as this release ships it (``WorkflowShadow.identical``,
filled by the generator). An identical copy hides nothing today, but only hides each later
release's changes, so its fix is to delete it; one that differs is to be compared with the
built-in. ``hub init`` seeds every built-in pack, so a fresh hub gets one warning per seeded
workflow (AGH-699 D15). Deleting a pack also deletes the hub's own files in it, so the fix says
to move them out first. An override in a hub pack of another name gets a fix that names its
file, not the pack, which holds the hub's other workflows. A hub file that does not load is
``workflows.valid``'s.
"""

import posixpath
from collections.abc import Iterator
from typing import Final

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import RULE_MODULES, WORKFLOWS_SHADOW_RULE, Severity

# Where the platform repository keeps the built-in packs, at each release's tag.
BUILTIN_SOURCE: Final = "packages/core/src/agent_hub/core/workflows/builtin"
KEEP_OWN: Final = "(move any file of your own out of it first)"
IDENTICAL_MESSAGE: Final = (
    "overrides the built-in workflow {name}, and {pack}/ is identical to the built-in {builtin}"
    " pack of this release ({version}), so it only hides the changes of later releases"
)
IDENTICAL_FIX: Final = "delete {pack}/ to run the built-in " + KEEP_OWN
MESSAGE: Final = (
    "overrides the built-in workflow {name}, and {pack}/ differs from the built-in"
    " {builtin} pack of this release ({version})"
)
FIX: Final = (
    "compare {pack}/ with {source}/{builtin}/ at the platform's tag v{version} and merge what you"
    " need, or delete {pack}/ to run the built-in " + KEEP_OWN
)
OTHER_PACK_IDENTICAL_MESSAGE: Final = (
    "overrides the built-in workflow {name} of the built-in {builtin} pack of this release"
    " ({version}) from another pack, {pack}/, which holds that pack identical, so it only hides"
    " the changes of later releases"
)
OTHER_PACK_IDENTICAL_FIX: Final = "delete {path} to run the built-in"
OTHER_PACK_MESSAGE: Final = (
    "overrides the built-in workflow {name} of the built-in {builtin} pack of this release"
    " ({version}) from another pack, {pack}/"
)
OTHER_PACK_FIX: Final = (
    "compare {path} with {source}/{builtin}/ at the platform's tag v{version} and merge what you"
    " need, or delete {path} to run the built-in"
)
# (message, fix) by (same pack name as the built-in's, identical to it).
_TEXTS: Final = {
    (True, True): (IDENTICAL_MESSAGE, IDENTICAL_FIX),
    (True, False): (MESSAGE, FIX),
    (False, True): (OTHER_PACK_IDENTICAL_MESSAGE, OTHER_PACK_IDENTICAL_FIX),
    (False, False): (OTHER_PACK_MESSAGE, OTHER_PACK_FIX),
}


def _workflows_shadow(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    for shadow in snapshot.workflow_shadows or ():
        words = {
            "name": shadow.name,
            "pack": shadow.pack,
            "path": shadow.path,
            "builtin": shadow.builtin_pack,
            "version": snapshot.running_version,
            "source": BUILTIN_SOURCE,
        }
        same_pack = posixpath.basename(shadow.pack) == shadow.builtin_pack
        message, fix = _TEXTS[same_pack, shadow.identical]
        yield WORKFLOWS_SHADOW.finding(
            path=shadow.path, message=message.format(**words), fix=fix.format(**words)
        )


WORKFLOWS_SHADOW: Final = Rule(
    id=WORKFLOWS_SHADOW_RULE,
    severity=Severity.WARNING,
    summary="no hub workflow overrides the built-in of its name",
    module=RULE_MODULES.get(WORKFLOWS_SHADOW_RULE),
    reads=frozenset({Read.WORKFLOW_SHADOWS}),
    check=_workflows_shadow,
)
