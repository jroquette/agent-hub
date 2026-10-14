from typing import Any

import pytest

from agent_hub.core.skills.skill_view import SkillFileTooLargeError
from agent_hub.core.testing.read_model_builders import (
    a_bundled_file_text,
    a_hook_detail,
    a_skill_catalog,
    a_skill_detail,
    an_agent_detail,
)

ALPHA = "/api/v1/projects/demo/skills/skill/hub-workflow/alpha"


def test_returns_catalog_when_port_answers(wired: Any) -> None:
    wired.hubs.skill_catalogs["demo"] = a_skill_catalog()

    response = wired.client.get("/api/v1/projects/demo/skills")

    assert response.status_code == 200
    assert response.json() == a_skill_catalog().model_dump(mode="json")
    assert wired.hubs.calls[-1] == ("skill_catalog", "demo")


def test_returns_detail_when_port_answers(wired: Any) -> None:
    for detail in (a_skill_detail(), an_agent_detail(), a_hook_detail()):
        wired.hubs.skill_details[("demo", detail.id)] = detail

    skill = wired.client.get(ALPHA)
    agent = wired.client.get("/api/v1/projects/demo/skills/agent/hub-workflow/evaluator")
    hook = wired.client.get("/api/v1/projects/demo/skills/hook/settings/settings-pretooluse-1")

    assert skill.json() == a_skill_detail().model_dump(mode="json")
    assert agent.json()["tools"] == ["Read", "Grep"]
    assert hook.json()["hook"]["matcher"] == "Bash"
    assert wired.hubs.calls[0] == ("skill_detail", ("demo", "skill/hub-workflow/alpha"))


def test_returns_bundled_file_when_port_answers(wired: Any) -> None:
    text = a_bundled_file_text()
    wired.hubs.skill_texts[("demo", "skill/hub-workflow/alpha", text.id)] = text

    response = wired.client.get(f"{ALPHA}/files/{text.id}")

    assert response.json() == text.model_dump(mode="json")


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/projects/demo/skills/plugin/hub-workflow/alpha",
        "/api/v1/projects/demo/skills/skill/hub-workflow/a.b",
        "/api/v1/projects/demo/skills/skill/hub.workflow/alpha",
        "/api/v1/projects/demo/skills/skill/hub-workflow/%2e%2e",
        "/api/v1/projects/demo/skills/skill/hub-workflow/a%5Cb",
        "/api/v1/projects/demo/skills/skill/hub-workflow/" + "a" * 129,
        f"{ALPHA}/files/ABCDEF0123456789",
        f"{ALPHA}/files/0123",
    ],
)
def test_answers_bad_request_when_kind_unknown(wired: Any, path: str) -> None:
    response = wired.client.get(path)

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    assert wired.hubs.calls == []


def test_answers_not_found_when_item_unknown(wired: Any) -> None:
    wired.hubs.skill_catalogs["demo"] = a_skill_catalog()

    item = wired.client.get("/api/v1/projects/demo/skills/skill/hub-workflow/missing")
    project = wired.client.get("/api/v1/projects/other/skills")
    nested = wired.client.get("/api/v1/projects/demo/skills/skill/hub-workflow/a/b")

    assert (item.status_code, item.json()["title"]) == (404, "Skill not found")
    assert project.status_code == 404
    assert nested.status_code == 404


def test_answers_payload_too_large_when_file_over_cap(wired: Any) -> None:
    wired.hubs.failure = SkillFileTooLargeError(limit=262_144, size=300_000)

    response = wired.client.get(f"{ALPHA}/files/0123456789abcdef")

    assert (response.status_code, response.json()["title"]) == (413, "Skill file too large")


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_answers_method_not_allowed_when_skills_written(wired: Any, method: str) -> None:
    for path in ("/api/v1/projects/demo/skills", ALPHA, f"{ALPHA}/files/0123456789abcdef"):
        response = wired.client.request(method.upper(), path)

        assert response.status_code == 405, (method, path)
