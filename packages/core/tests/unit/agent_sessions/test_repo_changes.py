"""Which repositories a session worked in, and what ``AgentSessionControl.repo_changes`` reads."""

from collections.abc import Callable, Sequence

import pytest

from agent_hub.core.agent_sessions.agent_session import AgentSession, ChangedFile, ReviewTarget
from agent_hub.core.agent_sessions.repo_changes import (
    MAX_REPOS,
    RepoChanges,
    RepoChangesError,
    RepoCommitDiff,
    RepoFileText,
    RepoPullRequest,
    relative_to_root,
    repo_roots,
)
from agent_hub.core.agent_sessions.workdirs import ResolvedWorkdir, WorkdirListing
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.testing.agent_session_rig import HUB_PATH, Rig
from agent_hub.core.testing.read_model_builders import WORKDIR_ID, a_log_record, a_workdir

REPO_PATH = "/hubs/api"
WORKTREE_PATH = "/hubs/api/.claude/worktrees/dem-1"
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
                    label="api/dem-1",
                    repo="api",
                    worktree="dem-1",
                ),
                path=WORKTREE_PATH,
            ),
        )
    )


def _labels(roots: tuple[ResolvedWorkdir, ...]) -> list[str]:
    return [root.workdir.label for root in roots]


def test_picks_the_worktree_not_its_repo_when_a_file_is_in_a_worktree() -> None:
    roots = repo_roots(_listing(), workdir_id=WORKDIR_ID, paths=[f"{WORKTREE_PATH}/src/app.py"])

    assert _labels(roots) == ["api/dem-1"]


def test_the_hub_is_never_a_repository_even_when_the_session_started_there() -> None:
    roots = repo_roots(_listing(), workdir_id=WORKDIR_ID, paths=[f"{HUB_PATH}/brain/a.md"])

    assert roots == ()


def test_lists_the_own_repo_first_then_each_repo_once_when_several_repos_changed() -> None:
    roots = repo_roots(
        _listing(),
        workdir_id=REPO_ID,
        paths=[f"{WORKTREE_PATH}/a.py", f"{REPO_PATH}/b.py", f"{WORKTREE_PATH}/c.py"],
    )

    assert _labels(roots) == ["api", "api/dem-1"]


def test_leaves_a_path_out_when_it_only_starts_like_a_repo_folder() -> None:
    roots = repo_roots(_listing(), workdir_id=WORKDIR_ID, paths=["/hubs/api-old/a.py", "/etc/x"])

    assert roots == ()


def test_reads_at_most_max_repos_when_more_repos_changed() -> None:
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


def test_reads_a_worktree_when_a_call_names_it_and_no_file_tool_changed_it() -> None:
    roots = repo_roots(
        _listing(),
        workdir_id=WORKDIR_ID,
        paths=[f"{HUB_PATH}/brain/reviews/T-1.md"],
        mentions=[f"cd {WORKTREE_PATH} && python3 - <<'EOF'", "Implement the card"],
    )

    assert _labels(roots) == ["api/dem-1"]


def test_skips_a_main_checkout_when_a_call_names_it_in_passing() -> None:
    roots = repo_roots(
        _listing(), workdir_id=WORKDIR_ID, paths=[], mentions=[f"rg claims {REPO_PATH}/src"]
    )

    assert roots == ()


@pytest.mark.parametrize(
    "mention",
    [f"{WORKTREE_PATH}-old/a.py", f"{WORKTREE_PATH}x", "/hubs/api/.claude/worktrees/dem-10"],
)
def test_names_no_worktree_when_a_text_only_starts_like_one(mention: str) -> None:
    roots = repo_roots(_listing(), workdir_id=WORKDIR_ID, paths=[], mentions=[mention])

    assert roots == ()


@pytest.mark.parametrize(
    "mention",
    [WORKTREE_PATH, f"{WORKTREE_PATH}/", f'W="{WORKTREE_PATH}"; cd $W', f"-C {WORKTREE_PATH} log"],
)
def test_names_a_worktree_when_its_whole_path_appears(mention: str) -> None:
    roots = repo_roots(_listing(), workdir_id=WORKDIR_ID, paths=[], mentions=[mention])

    assert _labels(roots) == ["api/dem-1"]


class _Reader:
    def __init__(
        self,
        failing: frozenset[str] = frozenset(),
        pull: RepoPullRequest | None = None,
    ) -> None:
        self.read_roots: list[str] = []
        self.recorded: list[tuple[str, str, str]] = []
        self.pr_asks = 0
        self._failing = failing
        self._pull = pull

    def read(self, root: str, *, label: str) -> RepoChanges:
        self.read_roots.append(root)
        if root in self._failing:
            raise RepoChangesError(label)
        return RepoChanges(
            root=root,
            label=label,
            branch="dem-1",
            base="origin/main",
            base_sha="f" * 40,
            head_sha="e" * 40,
        )

    def read_recorded(  # noqa: PLR0913 -- the port's signature
        self,
        repo_root: str,
        *,
        label: str,
        root: str,
        branch: str | None,
        base: str | None,
        base_sha: str,
        head_sha: str,
    ) -> RepoChanges:
        self.recorded.append((repo_root, root, head_sha))
        if repo_root in self._failing:
            raise RepoChangesError(label)
        return RepoChanges(
            root=root,
            label=label,
            branch=branch,
            base=base,
            base_sha=base_sha,
            head_sha=head_sha,
            source="recorded",
        )

    def pull_request(self, root: str, *, branch: str) -> RepoPullRequest | None:
        self.pr_asks += 1
        return self._pull

    def commit_diff(self, root: str, *, sha: str, paths: Sequence[str]) -> RepoCommitDiff:
        self.read_roots.append(root)
        if root in self._failing:
            raise RepoChangesError(root)
        return RepoCommitDiff(sha=sha * 2, path=paths[0], diff=f"diff of {','.join(paths)}")

    def file_text(self, root: str, *, sha: str, path: str) -> RepoFileText:
        self.read_roots.append(root)
        if root in self._failing:
            raise RepoChangesError(root)
        return RepoFileText(sha=sha * 2, path=path, text=f"text of {path}")


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


async def test_reads_each_repository_when_the_session_changed_a_file_in_it(
    make_rig: MakeRig,
) -> None:
    reader = _Reader()
    rig, session = await _ended_session_with_files(
        make_rig, reader, f"{WORKTREE_PATH}/a.py", f"{HUB_PATH}/brain/x.md"
    )

    changes = await rig.control.repo_changes(session.id)

    assert reader.read_roots == [WORKTREE_PATH]
    assert [(repo.label, repo.base) for repo in changes.repos] == [("api/dem-1", "origin/main")]
    assert changes.warnings == ()


async def test_reads_the_worktree_when_the_session_s_calls_worked_in_it(
    make_rig: MakeRig,
) -> None:
    reader = _Reader()
    rig, session = await _ended_session_with_files(make_rig, reader, f"{HUB_PATH}/brain/x.md")
    last = rig.store.get(session.id).last_seq
    rig.store.append(
        session.id,
        [
            a_log_record(
                "tool.call",
                seq=last + 1,
                body={
                    "name": "Agent",
                    "tool_use_id": "t9",
                    "input": {"prompt": f"Work in {WORKTREE_PATH}"},
                },
            )
        ],
    )

    changes = await rig.control.repo_changes(session.id)

    assert reader.read_roots == [WORKTREE_PATH]
    assert [repo.label for repo in changes.repos] == ["api/dem-1"]


PULL = RepoPullRequest(
    number=7, url="https://github.com/acme/api/pull/7", state="OPEN", head_sha="e" * 40
)


async def test_records_the_review_targets_with_their_pull_request_when_repo_changes_read(
    make_rig: MakeRig,
) -> None:
    reader = _Reader(pull=PULL)
    rig, session = await _ended_session_with_files(make_rig, reader, f"{WORKTREE_PATH}/a.py")

    changes = await rig.control.repo_changes(session.id)

    assert [repo.pull_request for repo in changes.repos] == [PULL]
    assert rig.store.get(session.id).review_targets == (
        ReviewTarget(
            repo="api",
            label="api/dem-1",
            root=WORKTREE_PATH,
            branch="dem-1",
            base="origin/main",
            base_sha="f" * 40,
            head_sha="e" * 40,
            pr_number=7,
            pr_url=PULL.url,
        ),
    )


async def test_asks_github_at_most_once_a_minute_when_a_branch_s_pull_request_read_again(
    make_rig: MakeRig,
) -> None:
    reader = _Reader(pull=PULL)
    rig, session = await _ended_session_with_files(make_rig, reader, f"{WORKTREE_PATH}/a.py")

    await rig.control.repo_changes(session.id)
    await rig.control.repo_changes(session.id)

    assert reader.pr_asks == 1


async def test_reads_the_recorded_commits_when_a_worktree_was_removed(make_rig: MakeRig) -> None:
    reader = _Reader()
    gone = "/hubs/api/.claude/worktrees/dem-0"
    rig, session = await _ended_session_with_files(make_rig, reader, f"{HUB_PATH}/brain/x.md")
    target = ReviewTarget(
        repo="api",
        label="api/dem-0",
        root=gone,
        branch="dem-0",
        base="origin/main",
        base_sha="a" * 40,
        head_sha="b" * 40,
        pr_number=3,
        pr_url="https://github.com/acme/api/pull/3",
    )
    rig.store.update(session.id, review_targets=(target,))

    changes = await rig.control.repo_changes(session.id)

    assert reader.recorded == [(REPO_PATH, gone, "b" * 40)]
    assert [(repo.label, repo.source) for repo in changes.repos] == [("api/dem-0", "recorded")]
    # GitHub did not answer: the pull request the session recorded still shows.
    assert changes.repos[0].pull_request == RepoPullRequest(
        number=3, url="https://github.com/acme/api/pull/3", state="UNKNOWN"
    )


async def test_a_removed_worktree_is_left_out_when_the_session_works_on_its_repo_elsewhere(
    make_rig: MakeRig,
) -> None:
    reader = _Reader()
    rig, session = await _ended_session_with_files(make_rig, reader, f"{WORKTREE_PATH}/a.py")
    old = ReviewTarget(
        repo="api",
        label="api/dem-0",
        root="/hubs/api/.claude/worktrees/dem-0",
        base_sha="a" * 40,
        head_sha="b" * 40,
    )
    rig.store.update(session.id, review_targets=(old,))

    changes = await rig.control.repo_changes(session.id)

    assert [repo.label for repo in changes.repos] == ["api/dem-1"]
    assert reader.recorded == []


async def test_names_a_repository_in_the_warnings_when_git_cannot_read_it(
    make_rig: MakeRig,
) -> None:
    reader = _Reader(failing=frozenset({REPO_PATH}))
    rig, session = await _ended_session_with_files(
        make_rig, reader, f"{REPO_PATH}/a.py", f"{WORKTREE_PATH}/b.py"
    )

    changes = await rig.control.repo_changes(session.id)

    assert [repo.label for repo in changes.repos] == ["api/dem-1"]
    assert changes.warnings == ("api could not be read by git",)


async def test_lists_no_repositories_when_there_is_no_reader(make_rig: MakeRig) -> None:
    rig, session = await _ended_session_with_files(make_rig, None, f"{REPO_PATH}/a.py")

    changes = await rig.control.repo_changes(session.id)

    assert (changes.repos, changes.warnings) == ((), ())


async def test_reads_a_commit_s_diff_when_its_repository_holds_the_file(
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
async def test_answers_not_found_when_a_commit_s_file_is_outside_the_repositories(
    make_rig: MakeRig, path: str
) -> None:
    rig, session = await _ended_session_with_files(make_rig, _Reader())

    with pytest.raises(EntityNotFoundError):
        await rig.control.repo_commit_diff(session.id, path=path, sha="abc1234")


async def test_answers_not_found_when_git_cannot_read_the_commit(make_rig: MakeRig) -> None:
    rig, session = await _ended_session_with_files(
        make_rig, _Reader(failing=frozenset({REPO_PATH}))
    )

    with pytest.raises(EntityNotFoundError):
        await rig.control.repo_commit_diff(session.id, path=f"{REPO_PATH}/a.py", sha="abc1234")


async def test_reads_a_file_at_a_commit_in_the_repository_that_holds_it(
    make_rig: MakeRig,
) -> None:
    reader = _Reader()
    rig, session = await _ended_session_with_files(make_rig, reader)

    found = await rig.control.repo_file_text(
        session.id, path=f"{WORKTREE_PATH}/src/a.py", sha="abc1234"
    )

    assert reader.read_roots == [WORKTREE_PATH]
    assert (found.path, found.text) == (f"{WORKTREE_PATH}/src/a.py", "text of src/a.py")


@pytest.mark.parametrize("path", [f"{HUB_PATH}/brain/a.md", "/etc/passwd", WORKTREE_PATH])
async def test_answers_not_found_when_a_file_is_outside_the_repositories(
    make_rig: MakeRig, path: str
) -> None:
    rig, session = await _ended_session_with_files(make_rig, _Reader())

    with pytest.raises(EntityNotFoundError):
        await rig.control.repo_file_text(session.id, path=path, sha="abc1234")


async def test_answers_not_found_when_git_cannot_read_the_file_s_commit(
    make_rig: MakeRig,
) -> None:
    rig, session = await _ended_session_with_files(
        make_rig, _Reader(failing=frozenset({REPO_PATH}))
    )

    with pytest.raises(EntityNotFoundError):
        await rig.control.repo_file_text(session.id, path=f"{REPO_PATH}/a.py", sha="abc1234")


def test_keeps_only_files_inside_the_root_when_made_relative_to_it() -> None:
    assert relative_to_root(REPO_PATH, f"{REPO_PATH}/src/a.py") == "src/a.py"
    assert relative_to_root(REPO_PATH, REPO_PATH) is None
    assert relative_to_root(REPO_PATH, f"{REPO_PATH}/../x.py") is None
    assert relative_to_root(REPO_PATH, "/hubs/api-old/a.py") is None
