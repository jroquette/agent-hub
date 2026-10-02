"""The rendered ``scripts/cloud-setup.sh`` of module ``cloud`` (AGH-17 D3, AC-17.9, AC-17.10).

``TestParity`` holds the hub's own ``cloud-setup.sh`` behaviour (its characterization cases:
identity global and per repo, fetch, clone, a failed fetch or clone as a WARN with exit 0, no
author → no identity). ``TestSecrecy``: a synthetic ``GH_TOKEN`` reaches git only through the
credential helper and shows nowhere. ``TestAccess`` (criterion 10.3, E11, Q-8): ``git ls-remote``
on the pinned tag, then one ``uvx`` warm-up, before any repo; each failure exits 1 in one line.

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
HELPER_KEY = "credential.https://github.com.helper"
# What `gh auth setup-git` writes for github.com: a reset, then gh's own helper.
GH_HELPERS = ("", "!/usr/local/bin/gh auth git-credential")
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
        assert f"cloud-setup: {removed} present, fetched" not in completed.stdout.splitlines()
        # The other repo is still set up.
        other = MISSING if removed == PRESENT else PRESENT
        assert (cloud_ws.workspace / other / ".git").is_dir()

    def test_warns_and_continues_when_identity_cannot_be_set(
        self, cloud_ws: CloudWorkspace
    ) -> None:
        # The global file sits in a missing folder (git reads nothing there and cannot write it);
        # the insteadOf rules come from the environment instead; ../demo-api's config is locked.
        rules = (cloud_ws.home / ".gitconfig").read_text(encoding="utf-8")
        pairs = [line.split('"')[1] for line in rules.splitlines() if line.startswith("[url")]
        prefixes = [line.split(" = ")[1] for line in rules.splitlines() if "insteadOf" in line]
        env = {
            "GIT_CONFIG_GLOBAL": str(cloud_ws.root / "no-such-dir" / "gitconfig"),
            "GIT_CONFIG_COUNT": str(len(pairs)),
        }
        for index, (url, prefix) in enumerate(zip(pairs, prefixes, strict=True)):
            env[f"GIT_CONFIG_KEY_{index}"] = f"url.{url}.insteadOf"
            env[f"GIT_CONFIG_VALUE_{index}"] = prefix
        (cloud_ws.workspace / PRESENT / ".git" / "config.lock").write_text("", encoding="utf-8")

        completed = cloud_ws.run(env=env)

        assert completed.returncode == 0, completed.stderr
        lines = completed.stdout.splitlines()
        assert "cloud-setup: WARN could not set the global git identity" in lines
        assert f"cloud-setup: WARN could not set the git identity in ../{PRESENT}" in lines
        assert f"cloud-setup: {PRESENT} present, fetched" in lines
        assert f"cloud-setup: cloned acme/{MISSING} into ../{MISSING}" in lines
        assert identity_line() not in lines
        clone = cloud_ws.workspace / MISSING
        assert cloud_ws.config("--local", "user.email", cwd=clone) == [AUTHOR_EMAIL]

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
        assert_no_token_in_files(cloud_ws)

    def test_keeps_gh_helpers_and_adds_one_when_run_twice(self, cloud_ws: CloudWorkspace) -> None:
        for value in GH_HELPERS:
            cloud_ws.config("--global", "--add", HELPER_KEY, value)

        first = cloud_ws.run(env={"GH_TOKEN": TOKEN})
        second = cloud_ws.run(env={"GH_TOKEN": TOKEN})

        assert (first.returncode, second.returncode) == (0, 0), first.stderr + second.stderr
        *kept, ours = cloud_ws.config("--global", "--get-all", HELPER_KEY)
        assert tuple(kept) == GH_HELPERS
        assert "${GH_TOKEN}" in ours

    def test_answers_nothing_when_token_unset_later(self, cloud_ws: CloudWorkspace) -> None:
        assert cloud_ws.run(env={"GH_TOKEN": TOKEN}).returncode == 0
        [helper] = cloud_ws.config("--global", "--get-all", HELPER_KEY)
        shell = shutil.which("sh")
        assert shell is not None

        # A later shell without GH_TOKEN: git runs the `!` helper as `sh -c '<body> "$@"' get`;
        # it answers nothing, so git falls through to the next helper (gh's, a keychain).
        completed = subprocess.run(  # noqa: S603 - absolute sh, the helper the script wrote
            [shell, "-c", helper.removeprefix("!") + ' "$@"', helper, "get"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            check=False,
            timeout=TIMEOUT,
            env={"PATH": os.environ.get("PATH", os.defpath)},
        )

        assert completed.stdout == ""


def assert_no_token_in_files(ws: CloudWorkspace) -> None:
    """Every file of the run: the call log (argv), ``~/.gitconfig``, each repo's config (remote
    URLs), ``hub.json``, the rendered hub; ``hub.lock`` would be one of them."""
    for path in ws.root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            assert TOKEN.encode() not in path.read_bytes(), path


SOURCE = f"git+{RELEASE_URL}@v{VERSION}#subdirectory=packages/agent-hub"
INSTALL_URL = "https://docs.astral.sh/uv/getting-started/installation/"


def no_access_line(version: str = VERSION) -> str:
    return (
        f"cloud-setup: cannot read agent-hub v{version} at {RELEASE_URL}: "
        "attach the repository to this session or set GH_TOKEN"
    )


def warm_up_call(version: str = VERSION) -> str:
    return f"uvx --from git+{RELEASE_URL}@v{version}#subdirectory=packages/agent-hub hub --version"


class TestAccess:
    def test_exits_one_naming_access_when_tag_unreachable(self, cloud_ws: CloudWorkspace) -> None:
        cloud_ws.git("tag", "-d", f"v{VERSION}", cwd=cloud_ws.origins / "agent-hub.git")

        completed = cloud_ws.run()

        assert completed.returncode == 1
        assert completed.stderr.splitlines() == [no_access_line()]
        calls = cloud_ws.calls()
        assert [call for call in calls if call.startswith("git ls-remote")] == [
            f"git ls-remote --exit-code {RELEASE_URL} refs/tags/v{VERSION}"
        ]
        assert not any(call.startswith(("uv ", "uvx ")) for call in calls)
        # No repo is fetched or cloned (the hub's own identity may be set before).
        assert not any(" fetch " in f" {call} " or call.startswith("git clone") for call in calls)
        assert not (cloud_ws.workspace / MISSING).exists()

    def test_warms_cache_once_before_fetch_when_tag_reachable(
        self, cloud_ws: CloudWorkspace
    ) -> None:
        completed = cloud_ws.run()

        assert completed.returncode == 0, completed.stderr
        calls = cloud_ws.calls()
        uv_calls = [call for call in calls if call.startswith(("uv ", "uvx "))]
        assert uv_calls == [warm_up_call()]
        access = calls.index(f"git ls-remote --exit-code {RELEASE_URL} refs/tags/v{VERSION}")
        warm_up = calls.index(warm_up_call())
        fetch = next(i for i, call in enumerate(calls) if call.endswith("fetch --quiet origin"))
        clone = next(i for i, call in enumerate(calls) if call.startswith("git clone"))
        assert access < warm_up < fetch < clone

    def test_reads_pin_at_run_time_when_hub_json_changes(self, cloud_ws: CloudWorkspace) -> None:
        # A new pin in hub.json, no sync: the script reads it, and the origin holds its tag.
        cloud_ws.write_hub_json(a_pinned_document("7.8.9"))
        source = cloud_ws.root / "sources" / "agent-hub"
        cloud_ws.git("tag", "v7.8.9", cwd=source)
        cloud_ws.git("push", "-q", str(cloud_ws.origins / "agent-hub.git"), "v7.8.9", cwd=source)

        completed = cloud_ws.run()

        assert completed.returncode == 0, completed.stderr
        calls = cloud_ws.calls()
        assert f"git ls-remote --exit-code {RELEASE_URL} refs/tags/v7.8.9" in calls
        assert [call for call in calls if call.startswith("uvx ")] == [warm_up_call("7.8.9")]

    def test_uses_helper_when_token_given_and_tag_private(self, cloud_ws: CloudWorkspace) -> None:
        private = {"FAKE_GIT_PRIVATE_TAG": "1"}

        without = cloud_ws.run(env=private)
        with_token = cloud_ws.run(env=private | {"GH_TOKEN": TOKEN})

        # Without the token the private tag is unreachable; with it git asks the helper, which
        # answers with the variable (the helper is set before the access check).
        assert without.returncode == 1
        assert no_access_line() in without.stderr.splitlines()
        assert with_token.returncode == 0, with_token.stderr
        assert [call for call in cloud_ws.calls() if call.startswith("uvx ")] == [warm_up_call()]
        assert TOKEN not in with_token.stdout + with_token.stderr
        # The helper has run: no file of the run holds the token, the call log included.
        assert_no_token_in_files(cloud_ws)

    @pytest.mark.parametrize(
        ("removed", "message"),
        [
            (
                ("uv", "uvx"),
                f"cloud-setup: uv is not installed (no uvx on PATH); see {INSTALL_URL}",
            ),
            (("python3",), "cloud-setup: python3 is not installed; it reads hub.json"),
        ],
        ids=["uv", "python3"],
    )
    def test_exits_one_naming_tool_when_uv_or_python_missing(
        self, removed: tuple[str, ...], message: str, cloud_ws: CloudWorkspace
    ) -> None:
        for tool in removed:
            (cloud_ws.bin / tool).unlink()

        completed = cloud_ws.run()

        assert completed.returncode == 1
        assert completed.stderr.splitlines() == [message]
        calls = cloud_ws.calls()
        assert not any(call.startswith(("git ls-remote", "git clone", "uvx ")) for call in calls)
        assert not any(call.endswith("fetch --quiet origin") for call in calls)

    def test_exits_one_when_warm_up_fails(self, cloud_ws: CloudWorkspace) -> None:
        completed = cloud_ws.run(env={"FAKE_UVX_RESOLVE_RC": "1"})

        assert completed.returncode == 1
        assert completed.stderr.splitlines() == [
            f"cloud-setup: cannot run agent-hub {VERSION} from {SOURCE}: "
            "the uv cache warm-up failed"
        ]
        calls = cloud_ws.calls()
        assert calls.count(warm_up_call()) == 1
        assert not any(call.startswith("git clone") for call in calls)
        assert not any(call.endswith("fetch --quiet origin") for call in calls)
