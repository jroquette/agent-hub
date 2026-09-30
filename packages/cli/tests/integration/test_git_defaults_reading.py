import os
import shlex
import shutil
import signal
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_hub.cli.git_defaults import (
    AUTHOR_EMAIL,
    AUTHOR_NAME,
    GIT_FAILED,
    GIT_NOT_FOUND,
    GIT_TIMED_OUT,
    HUB_REPO,
    GitDefaults,
    read_git_defaults,
)

ALL_KEYS = frozenset({AUTHOR_NAME, AUTHOR_EMAIL, HUB_REPO})
REMOTE_WITH_USERINFO = "https://x-access-token:SECRET123@github.com/acme/demo-hub"
# The conftest's fake git builder (tests cannot import a conftest in importlib mode).
type FakeGitFactory = Callable[..., Any]
ANSWERS = {
    "config --get user.name": "Jane Doe",
    "config --get user.email": "jane@example.com",
    "config --get remote.origin.url": REMOTE_WITH_USERINFO,
}


@pytest.fixture
def target(tmp_path: Path) -> Path:
    folder = tmp_path / "hub"
    folder.mkdir()
    return Path(os.path.realpath(folder))


def assert_no_secret(defaults: GitDefaults) -> None:
    assert "SECRET123" not in repr(defaults)
    assert REMOTE_WITH_USERINFO not in repr(defaults)


def test_logs_calls_when_fake_git_run(
    fake_git: FakeGitFactory, tmp_path: Path, target: Path
) -> None:
    git = fake_git({"config --get user.name": "Jane 'Q' Doe"})

    answered = subprocess.run(  # noqa: S603 - the fake git under tmp_path, fixed argv, no shell
        [str(git.bin_dir / "git"), "config", "--get", "user.name"],
        cwd=target,
        env={"PATH": str(git.bin_dir)},
        capture_output=True,
        check=False,
    )
    unset = subprocess.run(  # noqa: S603 - the fake git under tmp_path, fixed argv, no shell
        [str(git.bin_dir / "git"), "rev-parse", "--show-toplevel"],
        cwd=tmp_path,
        env={"PATH": str(git.bin_dir)},
        capture_output=True,
        check=False,
    )

    assert (answered.returncode, answered.stdout) == (0, b"Jane 'Q' Doe\n")
    assert (unset.returncode, unset.stdout) == (128, b"")
    assert git.calls() == [
        (str(target), "config --get user.name"),
        (os.path.realpath(tmp_path), "rev-parse --show-toplevel"),
    ]


def test_reads_every_default_when_all_keys_missing(
    fake_git: FakeGitFactory, monkeypatch: pytest.MonkeyPatch, target: Path
) -> None:
    git = fake_git(ANSWERS, toplevel=target)
    monkeypatch.setenv("PATH", str(git.bin_dir))

    defaults = read_git_defaults(missing=ALL_KEYS, target=target)

    assert defaults == GitDefaults(
        values={
            AUTHOR_NAME: "Jane Doe",
            AUTHOR_EMAIL: "jane@example.com",
            HUB_REPO: "acme/demo-hub",
        },
        problems={},
    )
    assert [arguments for _, arguments in git.calls()] == [
        "config --get user.name",
        "config --get user.email",
        "rev-parse --show-toplevel",
        "config --get remote.origin.url",
    ]
    assert_no_secret(defaults)


def test_reads_only_missing_keys_when_some_flags_given(
    fake_git: FakeGitFactory, monkeypatch: pytest.MonkeyPatch, target: Path
) -> None:
    git = fake_git(ANSWERS, toplevel=target)
    monkeypatch.setenv("PATH", str(git.bin_dir))

    defaults = read_git_defaults(missing=frozenset({AUTHOR_EMAIL}), target=target)

    assert defaults == GitDefaults(values={AUTHOR_EMAIL: "jane@example.com"}, problems={})
    assert [arguments for _, arguments in git.calls()] == ["config --get user.email"]


def test_calls_no_git_when_nothing_missing(
    fake_git: FakeGitFactory, monkeypatch: pytest.MonkeyPatch, target: Path
) -> None:
    git = fake_git(ANSWERS, toplevel=target)
    monkeypatch.setenv("PATH", str(git.bin_dir))

    defaults = read_git_defaults(missing=frozenset(), target=target)

    assert defaults == GitDefaults(values={}, problems={})
    assert git.calls() == []


def test_runs_in_target_when_target_exists(
    fake_git: FakeGitFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, target: Path
) -> None:
    git = fake_git(ANSWERS, toplevel=target)
    monkeypatch.setenv("PATH", str(git.bin_dir))
    monkeypatch.chdir(tmp_path)

    read_git_defaults(missing=ALL_KEYS, target=target)

    assert {cwd for cwd, _ in git.calls()} == {str(target)}


def test_runs_in_cwd_when_target_absent(
    fake_git: FakeGitFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, target: Path
) -> None:
    git = fake_git(ANSWERS, toplevel=target)
    monkeypatch.setenv("PATH", str(git.bin_dir))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    defaults = read_git_defaults(missing=ALL_KEYS, target=target / "new")

    # An absent target is no work tree top, so the remote is not read.
    assert defaults == GitDefaults(
        values={AUTHOR_NAME: "Jane Doe", AUTHOR_EMAIL: "jane@example.com"}, problems={}
    )
    assert git.calls() == [
        (os.path.realpath(work), "config --get user.name"),
        (os.path.realpath(work), "config --get user.email"),
    ]


def test_runs_in_cwd_when_target_is_file(
    fake_git: FakeGitFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, target: Path
) -> None:
    git = fake_git(ANSWERS, toplevel=target)
    monkeypatch.setenv("PATH", str(git.bin_dir))
    monkeypatch.chdir(tmp_path)
    a_file = target / "a-file"
    a_file.write_text("", encoding="utf-8")

    defaults = read_git_defaults(missing=frozenset({AUTHOR_NAME, HUB_REPO}), target=a_file)

    assert defaults == GitDefaults(values={AUTHOR_NAME: "Jane Doe"}, problems={})
    assert git.calls() == [(os.path.realpath(tmp_path), "config --get user.name")]


def test_skips_remote_when_target_not_worktree_top(
    fake_git: FakeGitFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, target: Path
) -> None:
    # The target sits inside a parent work tree: that repo's remote is not the hub's.
    git = fake_git(ANSWERS, toplevel=Path(os.path.realpath(tmp_path)))
    monkeypatch.setenv("PATH", str(git.bin_dir))

    defaults = read_git_defaults(missing=frozenset({HUB_REPO}), target=target)

    assert defaults == GitDefaults(values={}, problems={})
    assert [arguments for _, arguments in git.calls()] == ["rev-parse --show-toplevel"]


def test_skips_remote_when_target_outside_worktree(
    fake_git: FakeGitFactory, monkeypatch: pytest.MonkeyPatch, target: Path
) -> None:
    git = fake_git(ANSWERS)
    monkeypatch.setenv("PATH", str(git.bin_dir))

    defaults = read_git_defaults(missing=frozenset({HUB_REPO}), target=target)

    assert defaults == GitDefaults(values={}, problems={})
    assert [arguments for _, arguments in git.calls()] == ["rev-parse --show-toplevel"]


def test_reads_remote_when_toplevel_names_target_through_link(
    fake_git: FakeGitFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, target: Path
) -> None:
    link = tmp_path / "hub-link"
    link.symlink_to(target, target_is_directory=True)
    git = fake_git(ANSWERS, toplevel=link)
    monkeypatch.setenv("PATH", str(git.bin_dir))

    defaults = read_git_defaults(missing=frozenset({HUB_REPO}), target=target)

    assert defaults == GitDefaults(values={HUB_REPO: "acme/demo-hub"}, problems={})


def test_leaves_values_missing_when_git_holds_none(
    fake_git: FakeGitFactory, monkeypatch: pytest.MonkeyPatch, target: Path
) -> None:
    git = fake_git({}, toplevel=target)
    monkeypatch.setenv("PATH", str(git.bin_dir))

    defaults = read_git_defaults(missing=ALL_KEYS, target=target)

    assert defaults == GitDefaults(values={}, problems={})
    assert len(git.calls()) == 4


def test_leaves_values_missing_when_git_answers_empty(
    fake_git: FakeGitFactory, monkeypatch: pytest.MonkeyPatch, target: Path
) -> None:
    git = fake_git({"config --get user.name": ""}, toplevel=target)
    monkeypatch.setenv("PATH", str(git.bin_dir))

    defaults = read_git_defaults(missing=frozenset({AUTHOR_NAME}), target=target)

    assert defaults == GitDefaults(values={}, problems={})


@pytest.mark.parametrize(
    "url",
    [
        "https://user:SECRET123@gitlab.com/acme/demo-hub.git",
        "https://x-access-token:SECRET123@github.com/acme",
    ],
)
def test_leaves_hub_repo_missing_when_remote_not_github(
    fake_git: FakeGitFactory, monkeypatch: pytest.MonkeyPatch, target: Path, *, url: str
) -> None:
    git = fake_git({"config --get remote.origin.url": url}, toplevel=target)
    monkeypatch.setenv("PATH", str(git.bin_dir))

    defaults = read_git_defaults(missing=frozenset({HUB_REPO}), target=target)

    assert defaults == GitDefaults(values={}, problems={})
    assert "SECRET123" not in repr(defaults)
    assert url not in repr(defaults)


def test_names_git_not_found_when_git_absent(
    monkeypatch: pytest.MonkeyPatch, no_git_path: Path, target: Path
) -> None:
    monkeypatch.setenv("PATH", str(no_git_path))

    defaults = read_git_defaults(missing=ALL_KEYS, target=target)

    assert defaults == GitDefaults(values={}, problems=dict.fromkeys(ALL_KEYS, GIT_NOT_FOUND))


def test_finds_git_when_path_entry_relative(
    fake_git: FakeGitFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, target: Path
) -> None:
    # PATH is searched from the process cwd; git then runs in the target, so its path is made
    # absolute first.
    git = fake_git(ANSWERS, toplevel=target)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", git.bin_dir.name)

    defaults = read_git_defaults(missing=frozenset({AUTHOR_NAME}), target=target)

    assert defaults == GitDefaults(values={AUTHOR_NAME: "Jane Doe"}, problems={})


def test_names_git_failure_when_git_cannot_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target: Path
) -> None:
    # An executable that is no program: the exec fails with ENOEXEC, not ENOENT.
    bin_dir = tmp_path / "broken-bin"
    bin_dir.mkdir()
    (bin_dir / "git").write_bytes(b"\x00\x01\x02\x03")
    (bin_dir / "git").chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))

    defaults = read_git_defaults(missing=ALL_KEYS, target=target)

    assert defaults == GitDefaults(values={}, problems=dict.fromkeys(ALL_KEYS, GIT_FAILED))


def test_names_timeout_when_git_hangs(
    fake_git: FakeGitFactory, monkeypatch: pytest.MonkeyPatch, target: Path
) -> None:
    git = fake_git(ANSWERS, toplevel=target, hangs=True)
    monkeypatch.setenv("PATH", str(git.bin_dir))
    results: list[GitDefaults] = []
    # In a thread, so a read that never ends fails the test instead of hanging the run.
    reader = threading.Thread(
        target=lambda: results.append(
            read_git_defaults(missing=ALL_KEYS, target=target, timeout=0.2)
        ),
        daemon=True,
    )

    reader.start()
    reader.join(timeout=5)

    # The spinning child of the fake holds stdout: only killing the group lets the read end.
    assert not reader.is_alive()
    assert results == [GitDefaults(values={}, problems=dict.fromkeys(ALL_KEYS, GIT_TIMED_OUT))]
    # After a timeout git is not called again.
    assert [arguments for _, arguments in git.calls()] == ["config --get user.name"]


def test_keeps_values_read_when_later_call_times_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target: Path
) -> None:
    # A fake that answers user.name, then hangs on every later call.
    bin_dir = tmp_path / "late-hang-bin"
    bin_dir.mkdir()
    (bin_dir / "git").write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        "  'config --get user.name') printf '%s\\n' 'Jane Doe' ;;\n"
        "  *) ( while :; do :; done ) & wait ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (bin_dir / "git").chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))

    defaults = read_git_defaults(missing=ALL_KEYS, target=target, timeout=0.2)

    assert defaults == GitDefaults(
        values={AUTHOR_NAME: "Jane Doe"},
        problems={AUTHOR_EMAIL: GIT_TIMED_OUT, HUB_REPO: GIT_TIMED_OUT},
    )


def write_git_script(folder: Path, body: str) -> Path:
    folder.mkdir()
    script = folder / "git"
    script.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    script.chmod(0o755)
    return folder


def test_leaves_value_missing_when_git_fails_with_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target: Path
) -> None:
    bin_dir = write_git_script(tmp_path / "failing-bin", "printf '%s\\n' 'Jane Doe'\nexit 1\n")
    monkeypatch.setenv("PATH", str(bin_dir))

    defaults = read_git_defaults(missing=frozenset({AUTHOR_NAME}), target=target)

    assert defaults == GitDefaults(values={}, problems={})


def test_leaves_value_missing_when_git_answers_non_utf8(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target: Path
) -> None:
    bin_dir = write_git_script(tmp_path / "latin1-bin", "printf 'Jos\\351\\n'\n")
    monkeypatch.setenv("PATH", str(bin_dir))

    defaults = read_git_defaults(missing=frozenset({AUTHOR_NAME}), target=target)

    assert defaults == GitDefaults(values={}, problems={})


def test_prints_nothing_when_git_writes_stderr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target: Path,
    *,
    capfd: pytest.CaptureFixture[str],
) -> None:
    body = f"printf '%s\\n' {shlex.quote(REMOTE_WITH_USERINFO)} >&2\nprintf '%s\\n' 'Jane Doe'\n"
    monkeypatch.setenv("PATH", str(write_git_script(tmp_path / "noisy-bin", body)))

    defaults = read_git_defaults(missing=frozenset({AUTHOR_NAME}), target=target)

    assert defaults == GitDefaults(values={AUTHOR_NAME: "Jane Doe"}, problems={})
    assert capfd.readouterr() == ("", "")


def test_names_git_not_found_when_git_vanishes_before_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target: Path
) -> None:
    # Found on PATH, then gone when it runs.
    monkeypatch.setattr(shutil, "which", lambda _name: str(tmp_path / "gone" / "git"))

    defaults = read_git_defaults(missing=ALL_KEYS, target=target)

    assert defaults == GitDefaults(values={}, problems=dict.fromkeys(ALL_KEYS, GIT_NOT_FOUND))


@pytest.mark.parametrize("variable", ["GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"])
def test_skips_remote_when_git_location_set_in_environment(
    fake_git: FakeGitFactory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    target: Path,
    variable: str,
) -> None:
    # With GIT_DIR set, git takes the cwd as the work tree top: the target would pass the top
    # check while the remote comes from another repo. So the remote is not read at all.
    git = fake_git(ANSWERS, toplevel=target)
    monkeypatch.setenv("PATH", str(git.bin_dir))
    monkeypatch.setenv(variable, str(tmp_path / "other-repo" / ".git"))

    defaults = read_git_defaults(missing=ALL_KEYS, target=target)

    assert defaults == GitDefaults(
        values={AUTHOR_NAME: "Jane Doe", AUTHOR_EMAIL: "jane@example.com"}, problems={}
    )
    assert HUB_REPO not in defaults.values
    assert [arguments for _, arguments in git.calls()] == [
        "config --get user.name",
        "config --get user.email",
    ]


def test_kills_git_group_when_interrupted_while_git_runs(
    fake_git: FakeGitFactory, monkeypatch: pytest.MonkeyPatch, target: Path
) -> None:
    git = fake_git(ANSWERS, toplevel=target)
    monkeypatch.setenv("PATH", str(git.bin_dir))
    killed: list[tuple[int, int]] = []
    started: list[int] = []
    real_killpg = os.killpg

    def interrupted(self: subprocess.Popen[bytes], *_args: object, **_kwargs: object) -> None:
        started.append(self.pid)
        raise KeyboardInterrupt

    def recording_killpg(group: int, signal_number: int) -> None:
        killed.append((group, signal_number))
        real_killpg(group, signal_number)

    monkeypatch.setattr(subprocess.Popen, "communicate", interrupted)
    monkeypatch.setattr(os, "killpg", recording_killpg)

    with pytest.raises(KeyboardInterrupt):
        read_git_defaults(missing=ALL_KEYS, target=target)

    # git runs in its own session, so its pid is its group: the whole group is killed.
    assert killed == [(started[0], signal.SIGKILL)]
