"""The rendered commit-msg hook (AGH-699 C-8): AGENTS.md rule 1 at git's own commit step.

The rendered ``.githooks/commit-msg`` (ADR 0061) runs ``plugin/hub-workflow/hooks/commit_msg.py`` on
the message file git passes. Each case makes a rendered demo hub a git repository whose
``core.hooksPath`` is ``.githooks`` (what ``hub sync`` sets), without the pre-commit hook (its own
tests are in the CLI's ``test_commit_hooks.py``), then commits with real
git, ``python3`` being ``hook_python`` first on ``PATH``. The hook refuses an AI co-author
trailer, a "Generated with Claude" line and the robot emoji (the guard's ``AI_ATTRIBUTION``), and,
when ``hub.json`` names ``project.author_email``, an author or committer with another email.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

TIMEOUT = 60
SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
HOOK_ID = "commit-msg"
AUTHOR_NAME = "Jane Doe"
AUTHOR_EMAIL = "jane@example.com"
FOREIGN_EMAIL = "noreply@anthropic.com"
CLEAN_MESSAGE = "feat(api): add the login endpoint\n\nThe endpoint checks the session.\n"
ATTRIBUTION_REASON = "commit-msg: the message carries AI attribution"
# Built from fragments, so this file holds no attribution line a reader could take for one.
TRAILER = "Co-Authored-" + "By: Claude <" + FOREIGN_EMAIL + ">"
FOOTER = "Generated " + "with [Claude Code](https://claude.com/claude-code)"
ROBOT = "\U0001f916"


def real_git() -> str:
    found = shutil.which("git")
    assert found is not None, "the commit-msg tests run git: install it"
    return os.path.realpath(found)


def run_git(hub: Path, env: Mapping[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - absolute git, fixed arguments, no shell
        [real_git(), *arguments],
        capture_output=True,
        text=True,
        check=False,
        cwd=hub,
        env=dict(env),
        timeout=TIMEOUT,
    )


class HubRepo:
    """A rendered demo hub that is a git repository with the commit-msg hook installed."""

    def __init__(self, root: Path, env: dict[str, str]) -> None:
        self.root = root
        self.env = env

    def commit(
        self, message: str, *options: str, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        arguments = ("commit", "--allow-empty", *options, "-m", message)
        return run_git(self.root, self.env | dict(env or {}), *arguments)

    def messages(self) -> list[str]:
        listed = run_git(self.root, self.env, "log", "--format=%B%x00")
        if listed.returncode != 0:  # no commit yet
            return []
        return [text.strip("\n") for text in listed.stdout.split("\x00") if text.strip("\n")]


@pytest.fixture
def hub_repo(
    *,
    tmp_path: Path,
    rendered_hub: Callable[[HubConfig], Path],
    demo_config: HubConfig,
    hook_python: str,
) -> Callable[[dict[str, Any]], HubRepo]:
    """Render the demo hub with ``document`` as its ``hub.json``, ``git init`` it and turn on its
    rendered ``.githooks/commit-msg`` alone, through ``core.hooksPath``."""

    def build(document: dict[str, Any]) -> HubRepo:
        hub = rendered_hub(demo_config)
        (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "python3").symlink_to(os.path.realpath(hook_python))
        env = {
            "PATH": os.pathsep.join((str(bin_dir), *SYSTEM_PATH)),
            "HOME": str(tmp_path / "home"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "LANG": "C.UTF-8",
        }
        for arguments in (
            ("init", "-q"),
            ("config", "user.name", AUTHOR_NAME),
            ("config", "user.email", AUTHOR_EMAIL),
            ("config", "maintenance.auto", "false"),
            ("config", "gc.auto", "0"),
            ("config", "core.hooksPath", ".githooks"),
        ):
            assert run_git(hub, env, *arguments).returncode == 0
        (hub / ".githooks" / "pre-commit").unlink()
        return HubRepo(hub, env)

    return build


def text_of(config: HubConfig, path: str) -> str:
    rendered = render_hub(config)
    return next(file for file in rendered.files if file.path == path).content.decode("utf-8")


def test_runs_rendered_hook_file_when_hook_read(demo_config: HubConfig) -> None:
    hook = text_of(demo_config, ".githooks/commit-msg")

    paths = {file.path for file in render_hub(demo_config).files}

    script = "plugin/hub-workflow/hooks/commit_msg.py"
    assert hook.splitlines()[-1] == f'exec python3 "$hub_dir/{script}" "$1"'
    assert script in paths


@pytest.mark.parametrize(
    "line",
    [TRAILER, TRAILER.lower(), FOOTER, f"Done {ROBOT}"],
    ids=["trailer", "lower", "footer", "robot"],
)
def test_refuses_commit_when_message_carries_ai_attribution(
    line: str, hub_repo: Callable[[dict[str, Any]], HubRepo]
) -> None:
    repo = hub_repo(a_hub_document())

    completed = repo.commit(f"{CLEAN_MESSAGE}\n{line}\n")

    assert completed.returncode != 0
    assert ATTRIBUTION_REASON in completed.stderr
    assert repo.messages() == []


@pytest.mark.parametrize(
    ("options", "env"),
    [
        ((f"--author=Bot <{FOREIGN_EMAIL}>",), {}),
        ((), {"GIT_COMMITTER_EMAIL": FOREIGN_EMAIL}),
    ],
    ids=["author", "committer"],
)
def test_refuses_commit_when_identity_foreign(
    options: tuple[str, ...],
    env: dict[str, str],
    hub_repo: Callable[[dict[str, Any]], HubRepo],
) -> None:
    repo = hub_repo(a_hub_document())

    completed = repo.commit(CLEAN_MESSAGE, *options, env=env)

    assert completed.returncode != 0
    assert FOREIGN_EMAIL in completed.stderr
    assert f"project.author_email ({AUTHOR_EMAIL})" in completed.stderr
    assert ATTRIBUTION_REASON not in completed.stderr
    assert repo.messages() == []


def test_commits_when_message_clean_and_author_configured(
    hub_repo: Callable[[dict[str, Any]], HubRepo],
) -> None:
    repo = hub_repo(a_hub_document())

    completed = repo.commit(CLEAN_MESSAGE)

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert repo.messages() == [CLEAN_MESSAGE.strip("\n")]


def test_lets_any_author_commit_when_hub_names_no_author_email(
    hub_repo: Callable[[dict[str, Any]], HubRepo],
) -> None:
    document = a_hub_document()
    del document["project"]["author_email"]
    repo = hub_repo(document)

    clean = repo.commit(CLEAN_MESSAGE, "--author=Other <other@example.com>")
    attributed = repo.commit(f"{CLEAN_MESSAGE}\n{TRAILER}\n")

    assert clean.returncode == 0, clean.stderr
    assert attributed.returncode != 0
    assert ATTRIBUTION_REASON in attributed.stderr
    assert repo.messages() == [CLEAN_MESSAGE.strip("\n")]
