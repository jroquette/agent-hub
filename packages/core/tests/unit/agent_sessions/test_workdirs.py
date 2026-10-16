import os
from collections.abc import Mapping, Sequence

import pytest

from agent_hub.core.agent_sessions.errors import InvalidWorkdirError
from agent_hub.core.agent_sessions.workdirs import (
    MAX_WORKTREES,
    WorkdirListing,
    list_workdirs,
    workdir_id,
)

ME = 1000
HUB = "/work/demo-hub"
REPO = "/work/agent-hub"
WORKTREES = "/work/agent-hub/.claude/worktrees"


class FakeTree:
    """Folders by path (sub-folder names), symlinks by path, unreadable paths."""

    def __init__(
        self,
        folders: Mapping[str, Sequence[str]],
        links: Mapping[str, str] | None = None,
        *,
        unreadable: Sequence[str] = (),
        owners: Mapping[str, int] | None = None,
        modes: Mapping[str, int] | None = None,
    ) -> None:
        self.folders = folders
        self.links = links or {}
        self.unreadable = unreadable
        self.owners = owners or {}
        self.modes = modes or {}
        self.stated: list[str] = []

    def list_dir(self, path: str) -> Sequence[str]:
        if path in self.unreadable:
            raise PermissionError(path)
        if path not in self.folders:
            raise FileNotFoundError(path)
        return self.folders[path]

    def realpath(self, path: str) -> str:
        normal = os.path.normpath(path)
        for link, target in self.links.items():
            if normal == link or normal.startswith(link + "/"):
                return target + normal[len(link) :]
        return normal

    def stat(self, path: str) -> os.stat_result:
        self.stated.append(path)
        mode = self.modes.get(path, 0o40755)
        uid = self.owners.get(path, ME)
        return os.stat_result((mode, 0, 0, 0, uid, 0, 0, 0, 0, 0))


def _layout(**extra: Sequence[str]) -> dict[str, Sequence[str]]:
    folders: dict[str, Sequence[str]] = {
        "/work": ["demo-hub", "agent-hub", "unrelated"],
        f"{HUB}/.claude/skills": ["feature", "fix"],
        WORKTREES: ["agh-7-collector"],
    }
    return folders | extra


def _list(tree: FakeTree, repos: Sequence[str] = ("agent-hub",)) -> WorkdirListing:
    return list_workdirs(
        HUB, repos, list_dir=tree.list_dir, realpath=tree.realpath, stat=tree.stat, uid=ME
    )


def test_lists_hub_repo_and_worktree_when_layout_present() -> None:
    listing = _list(FakeTree(_layout()))

    items = listing.view().items
    assert [(item.kind, item.label, item.repo, item.worktree) for item in items] == [
        ("hub", "demo-hub", None, None),
        ("repo", "agent-hub", "agent-hub", None),
        ("worktree", "agent-hub/agh-7-collector", "agent-hub", "agh-7-collector"),
    ]
    assert items[0].skills == ("feature", "fix")
    assert [entry.path for entry in listing.entries] == [HUB, REPO, f"{WORKTREES}/agh-7-collector"]
    assert listing.view().warnings == ()


def test_drops_worktree_when_symlink_leaves_root() -> None:
    tree = FakeTree(
        _layout(**{WORKTREES: ["agh-7-collector", "escape"]}),
        links={f"{WORKTREES}/escape": "/etc"},
    )

    labels = [item.label for item in _list(tree).view().items]

    assert labels == ["demo-hub", "agent-hub", "agent-hub/agh-7-collector"]


def test_drops_repo_when_symlink_leaves_hub_parent() -> None:
    tree = FakeTree(_layout(), links={REPO: "/elsewhere/agent-hub"})

    assert [item.kind for item in _list(tree).view().items] == ["hub"]


def test_skips_repo_when_not_checked_out() -> None:
    tree = FakeTree(_layout(**{"/work": ["demo-hub"]}))

    assert [item.kind for item in _list(tree).view().items] == ["hub"]


def test_resolves_only_listed_id_when_path_or_dotdot_given() -> None:
    listing = _list(FakeTree(_layout()))
    repo = listing.view().items[1]

    assert listing.resolve(repo.workdir_id).path == REPO
    for given in ("/etc", "../agent-hub", REPO, "0123456789abcdef", ""):
        with pytest.raises(InvalidWorkdirError):
            listing.resolve(given)


def test_keeps_id_stable_when_listed_twice() -> None:
    first = _list(FakeTree(_layout())).view().items
    second = _list(FakeTree(_layout())).view().items

    assert [item.workdir_id for item in first] == [item.workdir_id for item in second]
    assert first[1].workdir_id == workdir_id("repo", REPO)
    assert len({item.workdir_id for item in first}) == 3


def test_warns_and_keeps_repo_when_worktrees_unreadable() -> None:
    tree = FakeTree(_layout(), unreadable=[WORKTREES])

    view = _list(tree).view()

    assert [item.kind for item in view.items] == ["hub", "repo"]
    assert view.warnings == ("cannot read agent-hub/.claude/worktrees",)


def test_caps_worktrees_when_over_limit() -> None:
    names = [f"agh-{n:04d}" for n in range(MAX_WORKTREES + 5)]
    tree = FakeTree(_layout(**{WORKTREES: list(reversed(names))}))

    view = _list(tree).view()

    worktrees = [item.worktree for item in view.items if item.kind == "worktree"]
    assert worktrees == names[:MAX_WORKTREES]
    assert view.warnings == (f"agent-hub has more than {MAX_WORKTREES} worktrees",)


def test_lists_nothing_when_hub_owned_by_other_user() -> None:
    tree = FakeTree(_layout(), owners={HUB: ME + 1})

    view = _list(tree).view()

    assert view.items == ()
    assert view.warnings == ("refused demo-hub: not owned by the current user",)


def test_drops_repo_when_owned_by_other_user() -> None:
    tree = FakeTree(_layout(), owners={REPO: ME + 1})

    view = _list(tree).view()

    assert [item.kind for item in view.items] == ["hub"]
    assert view.warnings == ("refused agent-hub: not owned by the current user",)


def test_drops_worktree_when_group_or_world_writable() -> None:
    tree = FakeTree(
        _layout(**{WORKTREES: ["agh-7-collector", "agh-8-shared"]}),
        modes={f"{WORKTREES}/agh-7-collector": 0o40775, f"{WORKTREES}/agh-8-shared": 0o40757},
    )

    view = _list(tree).view()

    assert [item.kind for item in view.items] == ["hub", "repo"]
    assert view.warnings == (
        "refused agent-hub/agh-7-collector: writable by group or others",
        "refused agent-hub/agh-8-shared: writable by group or others",
    )


def test_checks_real_path_when_worktree_is_link() -> None:
    tree = FakeTree(
        _layout(**{WORKTREES: ["agh-7-collector"]}),
        links={f"{WORKTREES}/agh-7-collector": f"{WORKTREES}/agh-7-real"},
        owners={f"{WORKTREES}/agh-7-real": ME + 1},
    )

    view = _list(tree).view()

    assert [item.kind for item in view.items] == ["hub", "repo"]
    assert f"{WORKTREES}/agh-7-real" in tree.stated
    assert f"{WORKTREES}/agh-7-collector" not in tree.stated


def test_warns_when_stat_fails() -> None:
    tree = FakeTree(_layout())

    def stat(path: str) -> os.stat_result:
        if path == REPO:
            raise PermissionError(path)
        return tree.stat(path)

    view = list_workdirs(
        HUB, ("agent-hub",), list_dir=tree.list_dir, realpath=tree.realpath, stat=stat, uid=ME
    ).view()

    assert [item.kind for item in view.items] == ["hub"]
    assert view.warnings == ("cannot read agent-hub",)


def test_matches_known_vector_when_id_derived() -> None:
    # The web dev client derives the same ids (apps/web/src/lib/devCheckout.test.ts, E6).
    assert workdir_id("repo", "/srv/demo/agent-hub") == "5703fef9dd5a3894"
    assert workdir_id("worktree", "/srv/demo/agent-hub") == "51735bb2177a46eb"
