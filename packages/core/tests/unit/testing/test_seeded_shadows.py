from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.testing.seeded_shadows import seeded_shadow_findings, seeded_workflows


def test_lists_each_pack_workflow_when_builtins_read() -> None:
    workflows = seeded_workflows()

    assert ("brain-care", "context") in workflows
    assert ("brain-care", "inbox") in workflows
    assert ("sdlc", "preflight-check") in workflows
    assert all(not name.startswith(".") for _, name in workflows)
    paths = [f"workflows/{pack}/{name}.yaml" for pack, name in workflows]
    assert paths == sorted(paths)


def test_gives_one_delete_warning_per_workflow_when_version_given() -> None:
    found = seeded_shadow_findings("1.2.3")

    assert len(found) == len(seeded_workflows())
    inbox = next(f for f in found if f.path == "workflows/brain-care/inbox.yaml")
    assert (inbox.rule, inbox.severity, inbox.line) == ("workflows.shadow", Severity.WARNING, None)
    assert inbox.message == (
        "overrides the built-in workflow inbox, and workflows/brain-care/ is identical to the"
        " built-in brain-care pack of this release (1.2.3), so it only hides the changes of later"
        " releases"
    )
    assert inbox.fix == (
        "delete workflows/brain-care/ to run the built-in (move any file of your own out of it"
        " first)"
    )
