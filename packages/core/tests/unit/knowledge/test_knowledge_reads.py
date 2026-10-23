"""The app's knowledge reads (AGH-393, P-9): a project's hub searched and its backlinks read,
over the in-memory index and checkout, keyed by the registered hub's path (AM-6)."""

from dataclasses import dataclass, field

import pytest

from agent_hub.core.brain.brain_note import BrainNoteNotFoundError
from agent_hub.core.brain.brain_path import BrainPathError
from agent_hub.core.knowledge.knowledge_index import KnowledgeIndex
from agent_hub.core.knowledge.knowledge_reads import (
    KnowledgeResult,
    KnowledgeSearch,
    KnowledgeSkip,
    KnowledgeSources,
    KnowledgeSyncCounts,
    NoteBacklink,
    NoteBacklinks,
    ReadKnowledge,
)
from agent_hub.core.projects.project_views import ProjectDetail, RepoView, TrackerView
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.testing.knowledge_fakes import FakeKnowledgeCheckout, InMemoryKnowledgeIndex
from agent_hub.core.testing.read_model_builders import HUB_ID

HUB = "/work/demo-hub"


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


def _repo(directory: str) -> RepoView:
    return RepoView(
        name=directory,
        dir=directory,
        github=f"acme/{directory}",
        role=None,
        default_branch="main",
        check_fast="make check-fast",
        check="make check",
        agents_md_present=False,
        agents_md_lines=None,
    )


@dataclass
class _Hubs:
    """The two reads ``ReadKnowledge`` makes of ``HubReadModels``, over one project."""

    repos: tuple[str, ...] = ("demo-api", "demo-web")
    calls: list[str] = field(default_factory=list)

    def get_project(self, project: str) -> ProjectDetail:
        self.calls.append(f"get_project {project}")
        if project != "demo":
            raise EntityNotFoundError(entity="project", entity_id=project)
        return _detail()

    def project_repos(self, project: str) -> Page[RepoView]:
        self.calls.append(f"project_repos {project}")
        items = tuple(_repo(directory) for directory in self.repos)
        return Page(items=items, next_cursor=None, total_estimate=len(items))


@dataclass
class _World:
    hubs: _Hubs = field(default_factory=_Hubs)
    checkout: FakeKnowledgeCheckout = field(default_factory=FakeKnowledgeCheckout)
    index: InMemoryKnowledgeIndex = field(default_factory=InMemoryKnowledgeIndex)
    sources_asked: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    def sources(self, hub_path: str, repo_dirs: tuple[str, ...]) -> KnowledgeSources:
        self.sources_asked.append((hub_path, repo_dirs))
        return self.checkout

    def opened_index(self) -> KnowledgeIndex:
        return self.index

    def reads(self) -> ReadKnowledge:
        return ReadKnowledge(self.hubs, sources=self.sources, index=self.opened_index)


def _token() -> str:
    """A GitHub token shape r1 matches, built from parts so no literal is a token."""
    return "gh" + "p_" + "A1b2C3d4E5f6G7h8" * 2 + "xyzw"


def test_answers_results_with_warnings_when_repo_not_checked_out() -> None:
    world = _World()
    world.checkout.write(
        "brain/decisions/0001-worktrees.md",
        b"---\nstatus: accepted\nprovenance: agent\n---\n# Worktrees from origin\n\nworktrees\n",
    )
    world.checkout.write("brain/_inbox/leak.md", f"worktrees {_token()}\n".encode())
    world.checkout.missing = ("demo-web",)

    found = world.reads().search("demo", query="worktrees", kinds=(), limit=50)

    assert found == KnowledgeSearch(
        project="demo",
        query="worktrees",
        results=(
            KnowledgeResult(
                path="brain/decisions/0001-worktrees.md",
                kind="decision",
                title="Worktrees from origin",
                status="accepted",
                provenance="agent",
                snippet="# Worktrees from origin worktrees",
            ),
        ),
        sync=KnowledgeSyncCounts(listed=2, read=2, indexed=1, dropped=0),
        skipped=(KnowledgeSkip(path="brain/_inbox/leak.md", reason="matches a secret rule"),),
        warnings=("demo-web: not checked out; its docs are not searched",),
    )


def test_cuts_results_to_limit_when_more_match() -> None:
    world = _World()
    for number in range(60):
        world.checkout.write(f"brain/playbooks/p{number:02d}.md", b"# Marker\n\nmarker\n")

    found = world.reads().search("demo", query="marker", kinds=("playbook",), limit=8)

    assert [result.path for result in found.results] == [
        f"brain/playbooks/p{number:02d}.md" for number in range(8)
    ]
    assert found.sync.indexed == 60


def test_keys_rows_by_registered_hub_path_when_searched() -> None:
    world = _World()
    world.checkout.write("brain/now.md", b"# Now\n\nmarker\n")

    world.reads().search("demo", query="marker", kinds=(), limit=50)

    assert world.sources_asked == [(HUB, ("demo-api", "demo-web"))]
    assert set(world.index.stored(HUB).files) == {"brain/now.md"}
    assert world.hubs.calls == ["get_project demo", "project_repos demo"]


def test_lists_backlinks_with_total_when_many_link() -> None:
    world = _World()
    for number in range(120):
        world.checkout.write(
            f"brain/playbooks/p{number:03d}.md", f"# P{number}\n\n[x](../now.md)\n".encode()
        )
    world.checkout.write(
        "demo-api/docs/guide.md", b"# Guide\n\n[now](../../demo-hub/brain/now.md)\n"
    )

    found = world.reads().backlinks("demo", "now.md")

    assert (found.project, found.path, found.total) == ("demo", "now.md", 121)
    assert len(found.items) == 100
    assert found.items[0] == NoteBacklink(
        path="brain/playbooks/p000.md", kind="playbook", title="P0"
    )
    assert found.items == tuple(sorted(found.items, key=lambda item: item.path))
    assert isinstance(found, NoteBacklinks)


@pytest.mark.parametrize(
    ("path", "error"),
    [
        ("auto/x.md", BrainNoteNotFoundError),
        ("../hub.json", BrainPathError),
        ("x.txt", BrainPathError),
    ],
)
def test_refuses_backlinks_path_when_note_route_would(path: str, error: type[Exception]) -> None:
    world = _World()

    with pytest.raises(error):
        world.reads().backlinks("demo", path)

    assert world.sources_asked == []
    assert world.checkout.reads == []


def test_raises_not_found_when_project_unknown() -> None:
    world = _World()

    with pytest.raises(EntityNotFoundError):
        world.reads().search("nope", query="marker", kinds=(), limit=50)
    with pytest.raises(EntityNotFoundError):
        world.reads().backlinks("nope", "now.md")

    assert world.sources_asked == []
