from typing import Any

import pytest
from pydantic import ValidationError

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.schedules import EVENT_INPUTS, MAX_STARTS
from agent_hub.core.testing.builders import an_environments_document

# Assembled at run time, so the repo holds no secret-shaped text.
AWS_KEY = "AK" + "IA" + "A" * 16


def a_document_with_starts(**starts: list[dict[str, Any]]) -> dict[str, Any]:
    document = an_environments_document()
    document.update(starts)
    return document


def errors_of(document: dict[str, Any]) -> list[tuple[tuple[str | int, ...], str]]:
    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(document)
    return [(error["loc"], error["msg"]) for error in caught.value.errors()]


def test_accepts_schedules_and_events_when_hub_json_declares_them() -> None:
    document = a_document_with_starts(
        schedules=[
            {
                "workflow": "retro",
                "cron": "0 9 * * 1",
                "inputs": {"_note": "a comment", "days": 7, "label": "weekly"},
                "environment": "staging",
            }
        ],
        events=[{"workflow": "post-merge-verify", "on": "merge", "repo": "demo-api"}],
    )

    config = HubConfig.model_validate(document)

    (schedule,) = config.schedules
    assert (schedule.workflow, schedule.cron, schedule.environment) == (
        "retro",
        "0 9 * * 1",
        "staging",
    )
    assert schedule.inputs == {"days": 7, "label": "weekly"}
    (event,) = config.events
    assert (event.workflow, event.on, event.repo, event.inputs) == (
        "post-merge-verify",
        "merge",
        "demo-api",
        {},
    )
    assert EVENT_INPUTS["merge"] == ("sha",)


def test_reads_no_starts_when_hub_json_declares_no_schedule() -> None:
    config = HubConfig.model_validate(an_environments_document())

    assert (config.schedules, config.events) == ((), ())


@pytest.mark.parametrize("cron", ["0 9 * *", "0 0 30 2 *", "61 * * * *"])
def test_refuses_schedule_cron_when_it_is_invalid_or_never_fires(cron: str) -> None:
    document = a_document_with_starts(schedules=[{"workflow": "retro", "cron": cron}])

    assert [loc for loc, _ in errors_of(document)] == [("schedules", 0, "cron")]


def test_refuses_schedule_input_when_value_has_a_secret_shape() -> None:
    document = a_document_with_starts(
        schedules=[{"workflow": "retro", "cron": "0 9 * * 1", "inputs": {"token": AWS_KEY}}]
    )

    errors = errors_of(document)

    assert [loc for loc, _ in errors] == [("schedules", 0, "inputs", "token", "str")]
    assert all(AWS_KEY not in message for _, message in errors)


def test_refuses_schedules_when_more_than_the_cap_are_declared() -> None:
    document = a_document_with_starts(
        schedules=[
            {"workflow": f"flow-{index}", "cron": "0 9 * * 1"} for index in range(MAX_STARTS + 1)
        ]
    )

    assert [loc for loc, _ in errors_of(document)] == [("schedules",)]
