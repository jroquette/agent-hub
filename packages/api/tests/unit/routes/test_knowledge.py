"""The knowledge routes over ``ReadKnowledge`` on the in-memory index and checkout and the route
tests' hub fake (AGH-393, D-search-route, D-backlinks-route, P-11)."""

from typing import Any

import pytest

from agent_hub.core.knowledge.knowledge_reads import ReadKnowledge
from agent_hub.core.projects.project_views import ProjectDetail, TrackerView
from agent_hub.core.testing.knowledge_fakes import FakeKnowledgeCheckout, InMemoryKnowledgeIndex
from agent_hub.core.testing.read_model_builders import HUB_ID

HUB = "/home/demo/demo-hub"
QUERY = "zanzibarquery"


def _detail() -> ProjectDetail:
    return ProjectDetail(
        name="demo",
        hub_id=HUB_ID,
        hub_path=HUB,
        hub_repo="acme/demo-hub",
        tracker=TrackerView(kind="linear", teams=("DEM",), ready_label=None, failed_label=None),
        default_branch="main",
        branch_prefix="jdoe/",
        platform_version="0.8.0",
        lock_version=None,
        lock_state=None,
        modules=(),
    )


@pytest.fixture
def checkout(wired: Any) -> FakeKnowledgeCheckout:
    """A checkout of the project ``demo``'s hub, wired through ``ReadKnowledge``."""
    found = FakeKnowledgeCheckout()
    index = InMemoryKnowledgeIndex()
    wired.hubs.details["demo"] = _detail()
    wired.hubs.repos["demo"] = []
    wired.wire(
        knowledge_reads=ReadKnowledge(
            wired.hubs, sources=lambda _path, _dirs: found, index=lambda: index
        )
    )
    return found


def test_answers_search_body_when_hub_matches(wired: Any, checkout: FakeKnowledgeCheckout) -> None:
    checkout.write(
        "brain/decisions/0001-worktrees.md",
        b"---\nstatus: accepted\n---\n# Worktrees from origin\n\nworktrees\n",
    )
    checkout.write("brain/playbooks/a.md", b"# A\n\nworktrees\n")

    response = wired.client.get(
        "/api/v1/projects/demo/knowledge/search",
        params={"q": "worktrees", "kind": ["decision"], "limit": 8},
    )

    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["project", "query", "results", "sync", "skipped", "warnings"]
    assert (body["project"], body["query"], body["skipped"], body["warnings"]) == (
        "demo",
        "worktrees",
        [],
        [],
    )
    assert body["sync"] == {"listed": 2, "read": 2, "indexed": 2, "dropped": 0}
    assert [list(result) for result in body["results"]] == [
        ["path", "kind", "title", "status", "provenance", "snippet"]
    ]
    assert body["results"][0]["path"] == "brain/decisions/0001-worktrees.md"
    assert body["results"][0]["status"] == "accepted"


@pytest.mark.parametrize(
    "case",
    [
        ({"q": "!!!"}, "q"),
        ({"q": "("}, "q"),
        ({"q": QUERY + "x" * (501 - len(QUERY))}, "q"),
        ({"q": QUERY, "limit": 0}, "limit"),
        ({"q": QUERY, "limit": 51}, "limit"),
        ({"q": QUERY, "kind": "nope"}, "kind"),
        ({"q": QUERY, "kind": ["doc"] * 11}, "kind"),
    ],
)
def test_refuses_query_when_wordless_or_out_of_bounds(
    wired: Any, checkout: FakeKnowledgeCheckout, case: tuple[dict[str, Any], str]
) -> None:
    params, parameter = case
    response = wired.client.get("/api/v1/projects/demo/knowledge/search", params=params)

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    errors = response.json()["errors"]
    assert [error["parameter"] for error in errors] == [parameter]
    assert QUERY not in response.text
    assert checkout.reads == []
    if params["q"] in {"!!!", "("}:
        assert errors[0]["message"] == "the query has no words"
        assert f'"{params["q"]}"' not in response.text


def test_answers_backlinks_body_when_note_linked(
    wired: Any, checkout: FakeKnowledgeCheckout
) -> None:
    checkout.write("brain/playbooks/cleanup.md", b"# Cleanup\n\n[w](../decisions/0001-w.md)\n")
    checkout.write("brain/now.md", b"# Now\n")

    response = wired.client.get(
        "/api/v1/projects/demo/brain/backlinks", params={"path": "decisions/0001-w.md"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "project": "demo",
        "path": "decisions/0001-w.md",
        "items": [{"path": "brain/playbooks/cleanup.md", "kind": "playbook", "title": "Cleanup"}],
        "total": 1,
    }


def test_answers_not_implemented_when_knowledge_unwired(wired: Any) -> None:
    search = wired.client.get("/api/v1/projects/demo/knowledge/search", params={"q": "x"})
    backlinks = wired.client.get("/api/v1/projects/demo/brain/backlinks", params={"path": "a.md"})

    assert (search.status_code, backlinks.status_code) == (501, 501)
