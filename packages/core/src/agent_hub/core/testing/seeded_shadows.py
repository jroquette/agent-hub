"""The ``workflows.shadow`` warnings of a hub holding each built-in pack as ``hub init`` seeds it.

``hub init`` seeds every built-in pack byte for byte (AGH-227), and each workflow of a seeded pack
overrides the built-in of its name, so ``hub doctor`` on a fresh hub names each one, identical to
the built-in, with the fix "delete it" (AGH-699 D15). The workflows come from the shipped packs
(each ``*.yaml`` file directly in a pack folder), not from discovery, and the text is written out
here, not taken from the rule.
"""

from importlib.resources import files
from typing import Final

from agent_hub.core.doctor.finding import Finding
from agent_hub.core.hub_config.doctor_rules import Severity

SHADOW_RULE: Final = "workflows.shadow"
_BUILTIN: Final = ("workflows", "builtin")


def seeded_workflows() -> tuple[tuple[str, str], ...]:
    """Each built-in ``(pack, workflow)``, in the order of its hub path ``workflows/<pack>/…``."""
    root = files("agent_hub.core").joinpath(*_BUILTIN)
    found = [
        (pack.name, entry.name.removesuffix(".yaml"))
        for pack in root.iterdir()
        if pack.is_dir() and not pack.name.startswith((".", "_"))
        for entry in pack.iterdir()
        if entry.is_file() and entry.name.endswith(".yaml")
    ]
    return tuple(sorted(found, key=lambda pair: f"workflows/{pair[0]}/{pair[1]}.yaml"))


def seeded_shadow_findings(version: str) -> tuple[Finding, ...]:
    """The warning ``hub doctor`` gives each seeded workflow at release ``version``, sorted."""
    return tuple(
        Finding(
            rule=SHADOW_RULE,
            severity=Severity.WARNING,
            path=f"workflows/{pack}/{name}.yaml",
            line=None,
            message=(
                f"overrides the built-in workflow {name}, and workflows/{pack}/ is identical to"
                f" the built-in {pack} pack of this release ({version}), so it only hides the"
                " changes of later releases"
            ),
            fix=(
                f"delete workflows/{pack}/ to run the built-in (move any file of your own out of"
                " it first)"
            ),
        )
        for pack, name in seeded_workflows()
    )
