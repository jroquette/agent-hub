"""Which repositories a session worked in, and what ``AgentSessionControl.repo_changes`` reads."""

from collections.abc import Callable, Sequence

import pytest

from agent_hub.core.agent_sessions.agent_session import AgentSession, ChangedFile
from agent_hub.core.agent_sessions.repo_changes import (
    MAX_REPOS,
    RepoChanges,
    RepoChangesError,
    RepoCommitDiff,
    relative_to_root,
    repo_roots,
)
from agent_hub.core.agent_sessions.workdirs import ResolvedWorkdir, WorkdirListing
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.testing.agent_session_rig import HUB_PATH, Rig
from agent_hub.core.testing.read_model_builders import WORKDIR_ID, a_workdir

REPO_PATH = "/hubs/api"
WORKTREE_PATH = "/hubs/api/.claude/worktrees/tip-1"
REPO_ID = "1111111111111111"
WORKTREE_ID = "2222222222222222"

type MakeRig = Callable[..., Rig]

pytestmark = pytest.mark.anyio


def _listing() -> WorkdirListing:
    return WorkdirListing(
        entries=(
            ResolvedWorkdir(workdir=a_workdir(), path=HUB_PATH),
            ResolvedWorkdir(
                workdir=a_workdir(workdir_id=REPO_ID, kind="repo", label="api", repo="api"),
                path=REPO_PATH,
            ),
            ResolvedWorkdir(
                workdir=a_workdir(
                    workdir_id=WORKTREE_ID,
                    kind="worktree",
                    label="api/tip-1",
                    repo="api",
                    worktree="tip-1",
                ),
                path=WORKTREE_PATH,
            ),
        )
    )


def _labels(roots: tuple[ResolvedWorkdir, ...]) -> list[str]:
    return [root.workdir.label for root in roots]


def test_a_file_in_a_worktree_picks_the_worktree_not_its_repo() -> None:
    roots = repo_roots(_listing(), workdir_id=WORKDIR_ID, paths=[f"{WORKTREE_PATH}/src/app.py"])

    assert _labels(roots) == ["api/tip-1"]


def test_the_hub_is_never_a_repository_even_when_the_session_started_there() -> None:
    roots = repo_roots(_listing(), workdir_id=WORKDIR_ID, paths=[f"{HUB_PATH}/brain/a.md"])

    assert roots == ()


def test_the_session_s_own_repo_comes_first_then_each_repo_once() -> None:
    roots = repo_roots(
        _listing(),
        workdir_id=REPO_ID,
        paths=[f"{WORKTREE_PATH}/a.py", f"{REPO_PATH}/b.py", f"{WORKTREE_PATH}/c.py"],
    )

    assert _labels(roots) == ["api", "api/tip-1"]


def test_a_path_that_only_starts_like_a_repo_folder_is_not_in_it() -> None:
    roots = repo_roots(_listing(), workdir_id=WORKDIR_ID, paths=["/hubs/api-old/a.py", "/etc/x"])

    assert roots == ()


def test_at_most_max_repos_are_read() -> None:
    entries = tuple(
        ResolvedWorkdir(
            workdir=a_workdir(workdir_id=f"{n:016x}", kind="repo", label=f"r{n}", repo=f"r{n}"),
            path=f"/hubs/r{n}",
        )
        for n in range(1, MAX_REPOS + 3)
    )
    roots = repo_roots(
        WorkdirListing(entries=entries),
        workdir_id=WORKDIR_ID,
        paths=[f"/hubs/r{n}/a.py" for n in range(1, MAX_REPOS + 3)],
    )

    assert len(roots) == MAX_REPOS


class _Reader:
    def __init__(self, failing: frozenset[str] = frozenset()) -> None:
        self.read_roots: list[str] = []
        self._failing = failing

    def read(self, root: str, *, label: str) -> RepoChanges:
        self.read_roots.append(root)
        if root in self._failing:
            raise RepoChangesError(label)
        return RepoChanges(root=root, label=label, branch="tip-1", base="origin/main")

    def commit_diff(self, root: str, *, sha: str, paths: Sequence[str]) -> RepoCommitDiff:
        self.read_roots.append(root)
        if root in self._failing:
            raise RepoChangesError(root)
        return RepoCommitDiff(sha=sha * 2, path=paths[0], diff=f"diff of {','.join(paths)}")


def _workdirs(project: str) -> WorkdirListing:
    if project != "demo":
        raise EntityNotFoundError(entity="project", entity_id=project)
    return _listing()


async def _ended_session_with_files(
    rig_maker: MakeRig, reader: _Reader | None, *paths: str
) -> tuple[Rig, AgentSession]:
    rig = rig_maker(workdirs=_workdirs, repo_changes=reader)
    session = await rig.create()
    await rig.control.close(session.id)
    rig.store.update(
        session.id,
        changed_files=tuple(
            ChangedFile(path=path, last_change_id=f"t{n}") for n, path in enumerate(paths)
        ),
    )
    return rig, session


async def test_repo_changes_reads_each_repository_the_session_changed_a_file_in(
    make_rig: MakeRig,
) -> None:
    reader = _Reader()
    rig, session = await _ended_session_with_files(
        make_rig, reader, f"{WORKTREE_PATH}/a.py", f"{HUB_PATH}/brain/x.md"
    )

    changes = await rig.control.repo_changes(session.id)

    assert reader.read_roots == [WORKTREE_PATH]
    assert [(repo.label, repo.base) for repo in changes.repos] == [("api/tip-1", "origin/main")]
    assert changes.warnings == ()


async def test_a_repository_git_cannot_read_is_named_in_the_warnings(make_rig: MakeRig) -> None:
    reader = _Reader(failing=frozenset({REPO_PATH}))
    rig, session = await _ended_session_with_files(
        make_rig, reader, f"{REPO_PATH}/a.py", f"{WORKTREE_PATH}/b.py"
    )

    changes = await rig.control.repo_changes(session.id)

    assert [repo.label for repo in changes.repos] == ["api/tip-1"]
    assert changes.warnings == ("api could not be read by git",)


async def test_without_a_reader_there_are_no_repositories(make_rig: MakeRig) -> None:
    rig, session = await _ended_session_with_files(make_rig, None, f"{REPO_PATH}/a.py")

    changes = await rig.control.repo_changes(session.id)

    assert (changes.repos, changes.warnings) == ((), ())


async def test_a_commit_s_diff_is_read_in_the_repository_that_holds_the_file(
    make_rig: MakeRig,
) -> None:
    reader = _Reader()
    rig, session = await _ended_session_with_files(make_rig, reader)

    diff = await rig.control.repo_commit_diff(
        session.id,
        path=f"{WORKTREE_PATH}/src/new.py",
        sha="abc1234",
        old_path=f"{WORKTREE_PATH}/src/old.py",
    )

    assert reader.read_roots == [WORKTREE_PATH]
    assert (diff.path, diff.diff) == (
        f"{WORKTREE_PATH}/src/new.py",
        "diff of src/new.py,src/old.py",
    )


@pytest.mark.parametrize("path", [f"{HUB_PATH}/brain/a.md", "/etc/passwd", WORKTREE_PATH])
async def test_a_commit_s_diff_outside_the_session_s_repositories_is_not_found(
    make_rig: MakeRig, path: str
) -> None:
    rig, session = await _ended_session_with_files(make_rig, _Reader())

    with pytest.raises(EntityNotFoundError):
        await rig.control.repo_commit_diff(session.id, path=path, sha="abc1234")


async def test_a_commit_git_cannot_read_is_not_found(make_rig: MakeRig) -> None:
    rig, session = await _ended_session_with_files(
        make_rig, _Reader(failing=frozenset({REPO_PATH}))
    )

    with pytest.raises(EntityNotFoundError):
        await rig.control.repo_commit_diff(session.id, path=f"{REPO_PATH}/a.py", sha="abc1234")


def test_relative_to_root_keeps_only_files_inside_the_root() -> None:
    assert relative_to_root(REPO_PATH, f"{REPO_PATH}/src/a.py") == "src/a.py"
    assert relative_to_root(REPO_PATH, REPO_PATH) is None
    assert relative_to_root(REPO_PATH, f"{REPO_PATH}/../x.py") is None
    assert relative_to_root(REPO_PATH, "/hubs/api-old/a.py") is None
