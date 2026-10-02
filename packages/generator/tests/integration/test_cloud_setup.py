"""The rendered ``scripts/cloud-setup.sh`` of module ``cloud`` (AGH-17 D3, AC-17.9, AC-17.10).

``TestParity`` holds the hub's own ``cloud-setup.sh`` behaviour (its characterization cases:
identity global and per repo, fetch, clone, a failed fetch or clone as a WARN with exit 0, no
author → no identity). ``TestSecrecy``: a synthetic ``GH_TOKEN`` reaches git only through the
credential helper and shows nowhere.

The workspace, all under ``tmp_path`` and offline: ``ws/demo-hub`` is the ALL render (a git repo,
``hub.json`` pinned to ``VERSION``); ``ws/demo-api`` is a clone one commit behind its origin;
``demo-web`` exists only as ``origins/demo-web.git``; ``origins/agent-hub.git`` holds the tag
``v<VERSION>``. ``HOME/.gitconfig`` maps ``https://github.com/acme/`` and the platform repository
to those origins with ``insteadOf``. ``PATH`` holds only a test folder: the fake ``uv``/``uvx``,
a ``git`` that logs its argv to the same log before running the real git, and a ``python3`` link
to ``hook_python``.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document, a_second_repo

TIMEOUT = 60
SCRIPT = "scripts/cloud-setup.sh"
VERSION = "4.5.6"
RELEASE_URL = "https://github.com/jroquette/agent-hub"
AUTHOR_NAME = "Jane Doe"
AUTHOR_EMAIL = "jane@example.com"
PRESENT = "demo-api"
MISSING = "demo-web"
# A synthetic token, built from fragments so no token-shaped literal sits in the source.
TOKEN = "gh" + "p_" + "x" * 36
# The test's git: one log line per call, then the real git. With FAKE_GIT_PRIVATE_TAG=1 an
# ls-remote also needs the credential helper to answer with $GH_TOKEN (a private release).
FAKE_GIT = """\
#!/bin/sh
printf '%s\\n' "git $*" >> '{log}'
if [ "$1" = ls-remote ] && [ "${{FAKE_GIT_PRIVATE_TAG:-}}" = 1 ]; then
  answer=$(printf 'protocol=https\\nhost=github.com\\n\\n' \\
    | GIT_TERMINAL_PROMPT=0 '{git}' credential fill 2>/dev/null) || answer=
  if [ -z "${{GH_TOKEN:-}}" ] || [ "$answer" = "${{answer#*password=$GH_TOKEN}}" ]; then
    echo "fatal: Authentication failed for '$2'" >&2
    exit 128
  fi
fi
exec '{git}' "$@"
"""
SETUP_GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Setup",
    "GIT_AUTHOR_EMAIL": "setup@example.com",
    "GIT_COMMITTER_NAME": "Setup",
    "GIT_COMMITTER_EMAIL": "setup@example.com",
}


def real_git() -> str:
    found = shutil.which("git")
    assert found is not None, "the cloud setup tests run git: install it"
    return os.path.realpath(found)


@dataclass(frozen=True)
class CloudWorkspace:
    """The hub, its workspace, the local origins and the test's ``PATH`` folder and call log."""

    root: Path
    hub: Path
    home: Path
    bin: Path
    log: Path

    @property
    def workspace(self) -> Path:
        return self.hub.parent

    @property
    def origins(self) -> Path:
        return self.root / "origins"

    def git(self, *arguments: str, cwd: Path | None = None) -> str:
        """The real git with a setup-only identity and home; returns stdout."""
        completed = subprocess.run(  # noqa: S603 - absolute git, fixed arguments, no shell
            [real_git(), *arguments],
            capture_output=True,
            text=True,
            check=True,
            timeout=TIMEOUT,
            cwd=cwd or self.root,
            env={"PATH": os.environ.get("PATH", os.defpath), "HOME": str(self.root / "setup")}
            | SETUP_GIT_ENV,
        )
        return completed.stdout

    def config(self, *arguments: str, cwd: Path | None = None) -> list[str]:
        """``git config`` as the script's git sees it (its ``HOME``); empty when unset."""
        completed = subprocess.run(  # noqa: S603 - absolute git, fixed arguments, no shell
            [real_git(), "config", *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=TIMEOUT,
            cwd=cwd or self.root,
            env={"HOME": str(self.home), "GIT_CONFIG_NOSYSTEM": "1"},
        )
        return completed.stdout.splitlines()

    def write_hub_json(self, document: dict[str, object]) -> None:
        (self.hub / "hub.json").write_text(json.dumps(document, indent=2), encoding="utf-8")

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def run(self, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        """``bash <hub>/scripts/cloud-setup.sh`` from elsewhere, as an environment setup runs it."""
        bash = shutil.which("bash")
        assert bash is not None, "the module scripts run on bash: install it"
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir(exist_ok=True)
        return subprocess.run(  # noqa: S603 - absolute bash, a rendered script, no shell
            [bash, str(self.hub / SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
            timeout=TIMEOUT,
            cwd=elsewhere,
            env={"PATH": str(self.bin), "HOME": str(self.home), "GIT_CONFIG_NOSYSTEM": "1"}
            | (env or {}),
        )


def a_pinned_document(version: str = VERSION) -> dict[str, object]:
    """ALL's ``hub.json`` (the demo, ``demo-web``, the four modules), pinned to ``version``."""
    document = a_hub_document()
    document["platform"]["version"] = version
    document["repos"].append(a_second_repo())
    document["modules"] = {
        "bench": {},
        "cloud": {},
        "contract-sync": {"source": PRESENT, "target": MISSING},
        "marketplace": {},
    }
    return document


def a_bare_origin(ws: CloudWorkspace, name: str, files: dict[str, str], *, tag: str = "") -> Path:
    """``origins/<name>.git`` holding one commit of ``files`` on ``main`` (and ``tag``)."""
    source = ws.root / "sources" / name
    source.mkdir(parents=True)
    ws.git("-c", "init.defaultBranch=main", "init", "-q", cwd=source)
    for path, text in files.items():
        (source / path).write_text(text, encoding="utf-8")
    ws.git("add", ".", cwd=source)
    ws.git("commit", "-q", "-m", f"{name}: first", cwd=source)
    if tag:
        ws.git("tag", tag, cwd=source)
    origin = ws.origins / f"{name}.git"
    ws.git("clone", "-q", "--bare", str(source), str(origin))
    return origin


def push_upstream_change(ws: CloudWorkspace, name: str) -> str:
    """Commit in ``sources/<name>`` and push it to its origin's ``main``; return the commit."""
    source = ws.root / "sources" / name
    (source / "CHANGE.md").write_text("upstream\n", encoding="utf-8")
    ws.git("add", ".", cwd=source)
    ws.git("commit", "-q", "-m", f"{name}: upstream change", cwd=source)
    ws.git("push", "-q", str(ws.origins / f"{name}.git"), "HEAD:main", cwd=source)
    return ws.git("rev-parse", "HEAD", cwd=source).strip()


@pytest.fixture
def cloud_ws(
    tmp_path: Path,
    *,
    all_modules_config: HubConfig,
    rendered_hub: Callable[[HubConfig], Path],
    fake_uv_bin: Path,
    hook_python: str,
) -> CloudWorkspace:
    hub = rendered_hub(all_modules_config)
    ws = CloudWorkspace(
        root=tmp_path,
        hub=hub,
        home=tmp_path / "home",
        bin=fake_uv_bin,
        log=fake_uv_bin / "uvx.log",
    )
    ws.home.mkdir()
    ws.write_hub_json(a_pinned_document())
    ws.git("-c", "init.defaultBranch=main", "init", "-q", cwd=hub)
    a_bare_origin(ws, "agent-hub", {"README.md": "agent-hub\n"}, tag=f"v{VERSION}")
    a_bare_origin(ws, PRESENT, {"README.md": "api\n"})
    a_bare_origin(ws, MISSING, {"index.html": "<p>web</p>\n"})
    ws.git("clone", "-q", str(ws.origins / f"{PRESENT}.git"), str(ws.workspace / PRESENT))
    (ws.home / ".gitconfig").write_text(
        f'[url "{ws.origins.as_uri()}/"]\n\tinsteadOf = https://github.com/acme/\n'
        f'[url "{(ws.origins / "agent-hub.git").as_uri()}"]\n\tinsteadOf = {RELEASE_URL}\n',
        encoding="utf-8",
    )
    git = ws.bin / "git"
    git.write_text(FAKE_GIT.format(log=ws.log, git=real_git()), encoding="utf-8")
    git.chmod(0o755)
    (ws.bin / "python3").symlink_to(os.path.realpath(hook_python))
    return ws


def identity_line() -> str:
    return f"cloud-setup: git identity = {AUTHOR_NAME} <{AUTHOR_EMAIL}>"


class TestParity:
    def test_sets_identity_globally_and_per_repo_when_author_known(
        self, cloud_ws: CloudWorkspace
    ) -> None:
        completed = cloud_ws.run()

        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.splitlines()[0] == identity_line()
        assert cloud_ws.config("--global", "user.name") == [AUTHOR_NAME]
        assert cloud_ws.config("--global", "user.email") == [AUTHOR_EMAIL]
        # Repo-local too: a container's global ~/.gitconfig has been seen reset mid-session.
        for repo in (cloud_ws.hub, cloud_ws.workspace / PRESENT, cloud_ws.workspace / MISSING):
            assert cloud_ws.config("--local", "user.name", cwd=repo) == [AUTHOR_NAME], repo
            assert cloud_ws.config("--local", "user.email", cwd=repo) == [AUTHOR_EMAIL], repo

    def test_fetches_present_repo_when_run(self, cloud_ws: CloudWorkspace) -> None:
        upstream = push_upstream_change(cloud_ws, PRESENT)

        completed = cloud_ws.run()

        assert completed.returncode == 0, completed.stderr
        assert f"cloud-setup: {PRESENT} present, fetched" in completed.stdout.splitlines()
        fetched = cloud_ws.git("rev-parse", "origin/main", cwd=cloud_ws.workspace / PRESENT)
        assert fetched.strip() == upstream

    def test_clones_missing_repo_when_run(self, cloud_ws: CloudWorkspace) -> None:
        completed = cloud_ws.run()

        assert completed.returncode == 0, completed.stderr
        assert (
            f"cloud-setup: cloned acme/{MISSING} into ../{MISSING}" in completed.stdout.splitlines()
        )
        clone = cloud_ws.workspace / MISSING
        assert (clone / "index.html").read_text(encoding="utf-8") == "<p>web</p>\n"
        # The remote keeps the github URL; insteadOf only redirects the transfer.
        assert cloud_ws.config("remote.origin.url", cwd=clone) == [
            f"https://github.com/acme/{MISSING}.git"
        ]

    @pytest.mark.parametrize(
        ("removed", "warning"),
        [
            (PRESENT, f"cloud-setup: WARN fetch failed for {PRESENT}"),
            (
                MISSING,
                f"cloud-setup: WARN could not clone acme/{MISSING}: "
                "attach it to the session (or set GH_TOKEN)",
            ),
        ],
        ids=["fetch", "clone"],
    )
    def test_warns_and_exits_zero_when_clone_or_fetch_fails(
        self, removed: str, warning: str, cloud_ws: CloudWorkspace
    ) -> None:
        shutil.rmtree(cloud_ws.origins / f"{removed}.git")

        completed = cloud_ws.run()

        assert completed.returncode == 0, completed.stderr
        assert warning in completed.stdout.splitlines()
        # The other repo is still set up.
        other = MISSING if removed == PRESENT else PRESENT
        assert (cloud_ws.workspace / other / ".git").is_dir()

    @pytest.mark.parametrize("key", ["author_name", "author_email"])
    def test_sets_no_identity_when_author_missing(self, key: str, cloud_ws: CloudWorkspace) -> None:
        document = a_pinned_document()
        del document["project"][key]  # type: ignore[attr-defined]
        cloud_ws.write_hub_json(document)

        completed = cloud_ws.run()

        assert completed.returncode == 0, completed.stderr
        assert not any("git identity" in line for line in completed.stdout.splitlines())
        assert cloud_ws.config("--global", "--get-regexp", "^user[.]") == []
        assert cloud_ws.config("--local", "--get-regexp", "^user[.]", cwd=cloud_ws.hub) == []
        assert (cloud_ws.workspace / MISSING / ".git").is_dir()


class TestSecrecy:
    def test_never_shows_token_when_gh_token_set(self, cloud_ws: CloudWorkspace) -> None:
        completed = cloud_ws.run(env={"GH_TOKEN": TOKEN})

        assert completed.returncode == 0, completed.stderr
        # Git reads the variable at credential time through the helper; the file holds its name.
        [helper] = cloud_ws.config("--global", "credential.https://github.com.helper")
        assert "${GH_TOKEN}" in helper
        assert TOKEN not in completed.stdout
        assert TOKEN not in completed.stderr
        assert cloud_ws.calls(), "the call log records every git and uv argv"
        # Every file of the run: the call log (argv), ~/.gitconfig, each repo's config (remote
        # URLs), hub.json, the rendered hub; hub.lock would be one of them.
        for path in cloud_ws.root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                assert TOKEN.encode() not in path.read_bytes(), path
