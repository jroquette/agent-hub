"""A workaround option's plan and whether it can be picked (AC-350.21, AC-350.23; P-6)."""

from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    effective_environments,
)
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.scenarios.action_catalog import ActionEntry
from agent_hub.core.scenarios.action_document import parse_action
from agent_hub.core.scenarios.investigation import ProposedStep
from agent_hub.core.scenarios.workaround import (
    changed_step,
    needs_acceptance,
    pick_refusal,
    plan_changed,
    plan_option,
)
from agent_hub.core.testing.builders import an_environments_document

HASH = "sha256:" + "0" * 64


def an_entry(name: str, effect: str, *, draft: bool = False, content: str = HASH) -> ActionEntry:
    document = parse_action(
        {
            "version": 1,
            "name": name,
            "description": "A demo action",
            "effect": effect,
            "runtime": "sh",
            "script": f"scripts/{name}.sh",
            "inputs": {"target": {"type": "service", "required": True}},
            "output_format": {"type": "object"},
        }
    )
    return ActionEntry(
        pack="demo",
        document=document,
        document_path=f"actions/demo/{name}.yaml",
        script_path=f"actions/demo/scripts/{name}.sh",
        content_hash=content,
        draft=draft,
    )


def a_view() -> EffectiveEnvironments:
    return effective_environments(
        HubConfig.model_validate(an_environments_document()), LocalConfig()
    )


READ_STEP = ProposedStep(action="get-order", inputs={"target": "api"})
WRITE_STEP = ProposedStep(action="demo/release-hold", inputs={"target": "api"})
ENTRIES = (an_entry("get-order", "read"), an_entry("release-hold", "write"))


def test_plans_each_step_with_agent_origin_when_option_planned() -> None:
    plan = plan_option(
        (READ_STEP, WRITE_STEP), entries=ENTRIES, pack="demo", view=a_view(), environment="local"
    )

    assert [(step.index, step.action, step.decision, step.reason_kind) for step in plan] == [
        (1, "demo/get-order", "allow", "table"),
        # An agent's write in an environment of access write asks: the pick answers it.
        (2, "demo/release-hold", "ask", "agent_origin"),
    ]
    assert plan[0].endpoint == {"target": {"url": "http://localhost:8000", "resource": None}}
    assert pick_refusal(plan) is None
    assert not needs_acceptance(plan)


def test_refuses_pick_when_workaround_option_holds_deny() -> None:
    plan = plan_option(
        (READ_STEP, WRITE_STEP), entries=ENTRIES, pack="demo", view=a_view(), environment="live"
    )

    refused = pick_refusal(plan)
    assert refused is not None
    assert (refused.index, refused.decision, refused.reason_kind) == (2, "deny", "production")


def test_refuses_pick_when_workaround_option_holds_draft() -> None:
    entries = (an_entry("get-order", "read"), an_entry("release-hold", "write", draft=True))

    plan = plan_option(
        (READ_STEP, WRITE_STEP), entries=entries, pack="demo", view=a_view(), environment="local"
    )

    refused = pick_refusal(plan)
    assert refused is not None
    assert (refused.index, refused.draft, refused.reason_kind) == (2, True, "draft")
    assert needs_acceptance(plan)


def test_refuses_pick_when_workaround_option_names_unknown_action() -> None:
    unknown = ProposedStep(action="demo/nope", inputs={})

    plan = plan_option((unknown,), entries=ENTRIES, pack="demo", view=a_view(), environment="local")

    refused = pick_refusal(plan)
    assert refused is not None
    assert refused.problem == "unknown action 'demo/nope'"


def test_detects_change_when_workaround_plan_differs() -> None:
    shown = plan_option(
        (READ_STEP, WRITE_STEP), entries=ENTRIES, pack="demo", view=a_view(), environment="local"
    )
    recorded = [step.model_dump(mode="json") for step in shown]
    edited = (an_entry("get-order", "read"), an_entry("release-hold", "write", content="sha256:1"))

    same = plan_option(
        (READ_STEP, WRITE_STEP), entries=ENTRIES, pack="demo", view=a_view(), environment="local"
    )
    now = plan_option(
        (READ_STEP, WRITE_STEP), entries=edited, pack="demo", view=a_view(), environment="local"
    )

    assert not plan_changed(recorded, same)
    assert plan_changed(recorded, now)
    changed = changed_step(recorded, now)
    assert changed is not None
    assert changed.index == 2
