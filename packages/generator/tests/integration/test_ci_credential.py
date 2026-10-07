"""The rendered CI step ``Platform read credential``, run the way Actions runs it (AC-16.12, D4).

The workspace has no YAML parser (E18): the step's ``run: |`` block is taken as text by its fixed
indentation and run on ``bash`` with Actions' default flags, a synthetic ``TOKEN`` and a temp
``GITHUB_ENV``. With a token the block appends the platform ``insteadOf`` pair and the hub's
self-map to ``GITHUB_ENV``; without one it writes nothing; a token outside GitHub's character
set is refused before anything is written. The token shows in no rendered file and no output.

AGH-49 (AC-49.7, E14, E19): with a token, the step reads ``platform.repository`` from the
``hub.json`` in its folder (Actions' workspace). A repository on ``github.com`` (exact, lowercase)
gets the token mapping; another host gets none, so a change to ``hub.json`` cannot send the token
elsewhere. A bad value or an unreadable ``hub.json`` exits 1 in one fixed line, nothing written.
The harness runs the block in ``tmp_path/ws`` holding the demo ``hub.json`` (or the one a case
gives), with a ``python3`` link to this interpreter (or ``hook_python``) first on ``PATH``.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.platform_repository import PLATFORM_REPOSITORY_FORM
from agent_hub.core.hub_files.hub_lock import build_hub_lock, lock_bytes
from agent_hub.core.json_form import dump_json
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.platform_repository_cases import (
    CUSTOM_REPOSITORY,
    REPOSITORY_CASES,
    SECRET_PARTS,
    RepositoryCase,
)
from agent_hub.generator.placeholders import PLATFORM_REPOSITORY
from agent_hub.generator.render_hub import render_hub

TIMEOUT = 30
CI = ".github/workflows/ci.yml"
STEP = "      - name: Platform read credential\n"
RUN_HEAD = "        run: |\n"
BLOCK_INDENT = " " * 10
# Actions' default `shell: bash` on Linux.
BASH_FLAGS = ("--noprofile", "--norc", "-eo", "pipefail")
PLATFORM_URL = PLATFORM_REPOSITORY.removeprefix("git+")
# Synthetic tokens, built from fragments so no token-shaped literal sits in the source: a
# classic one (ghp_ + 36) and a fine-grained one (github_pat_ + 22 + _ + 59).
CLASSIC_TOKEN = "gh" + "p_" + "x" * 36
FINE_GRAINED_TOKEN = "github" + "_pat_" + "A1" * 11 + "_" + "b2" * 29 + "c"
REFUSAL = "AGENT_HUB_READ_TOKEN: unexpected characters"
PRIOR_ENV = "PRIOR=kept\n"
# The step's folder holds this hub.json unless a case gives another (or none).
DEMO_HUB_JSON = json.dumps(a_hub_document())


def credential_block(ci: str) -> str:
    """The step's ``run: |`` block as bash reads it: its lines at the block's indent, dedented."""
    step = ci[ci.index(STEP) :]
    body = step[step.index(RUN_HEAD) + len(RUN_HEAD) :]
    lines: list[str] = []
    for line in body.splitlines(keepends=True):
        if line.strip() and not line.startswith(BLOCK_INDENT):
            break
        lines.append(line.removeprefix(BLOCK_INDENT))
    assert lines, ci
    return "".join(lines)


def config_with_hub(hub_repo: str) -> HubConfig:
    document = a_hub_document()
    document["project"]["hub_repo"] = hub_repo
    return HubConfig.model_validate(document)


def ci_of(config: HubConfig) -> str:
    rendered = render_hub(config)
    return next(file for file in rendered.files if file.path == CI).content.decode("utf-8")


def run_step(
    config: HubConfig,
    tmp_path: Path,
    token: str | None,
    *,
    hub_json: str | None = DEMO_HUB_JSON,
    python: str = sys.executable,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run the rendered block in ``tmp_path/ws``, which holds ``hub_json`` as text (``None``: no
    file), with ``python3`` linked to ``python`` first on ``PATH``; ``token=None`` leaves
    ``TOKEN`` unset. Returns the run and its ``GITHUB_ENV`` file (written by the step, or not)."""
    bash = shutil.which("bash")
    assert bash is not None, "the credential step runs on bash: install it"
    env_file = tmp_path / "github-env"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    if hub_json is not None:
        (workspace / "hub.json").write_text(hub_json, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").symlink_to(os.path.realpath(python))
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.defpath}",
        "GITHUB_ENV": str(env_file),
        "HOME": str(tmp_path / "home"),
    }
    if token is not None:
        env["TOKEN"] = token
    completed = subprocess.run(  # noqa: S603 - absolute bash, the rendered block, no shell
        [os.path.realpath(bash), *BASH_FLAGS, "-c", credential_block(ci_of(config))],
        capture_output=True,
        text=True,
        check=False,
        cwd=workspace,
        env=env,
        timeout=TIMEOUT,
    )
    return completed, env_file


def expected_lines(token: str, hub_url: str) -> list[str]:
    return [
        "GIT_CONFIG_COUNT=2",
        f"GIT_CONFIG_KEY_0=url.https://x-access-token:{token}@"
        f"{PLATFORM_URL.removeprefix('https://')}.insteadOf",
        f"GIT_CONFIG_VALUE_0={PLATFORM_URL}",
        f"GIT_CONFIG_KEY_1=url.{hub_url}.insteadOf",
        f"GIT_CONFIG_VALUE_1={hub_url}",
    ]


def git_rewrites(env_lines: list[str], urls: list[str], tmp_path: Path) -> list[str]:
    """The URL git uses for each of ``urls`` under the job environment ``env_lines`` sets."""
    git = shutil.which("git")
    assert git is not None, "the self-map test runs git: install it"
    repo = tmp_path / "repo"
    env = {"PATH": os.defpath, "HOME": str(tmp_path / "home"), "GIT_CONFIG_NOSYSTEM": "1"}
    env |= dict(line.split("=", 1) for line in env_lines)

    def run(*arguments: str) -> str:
        completed = subprocess.run(  # noqa: S603 - absolute git, fixed arguments, no shell
            [os.path.realpath(git), "-C", str(repo), *arguments],
            capture_output=True,
            text=True,
            check=True,
            env=env,
            timeout=TIMEOUT,
        )
        return completed.stdout.strip()

    repo.mkdir()
    run("init", "-q")
    for number, url in enumerate(urls):
        run("remote", "add", f"r{number}", url)
    return [run("remote", "get-url", f"r{number}") for number in range(len(urls))]


@pytest.mark.parametrize(
    "token", [CLASSIC_TOKEN, FINE_GRAINED_TOKEN], ids=["classic", "fine-grained"]
)
def test_sets_platform_pair_and_self_map_when_token_given(token: str, tmp_path: Path) -> None:
    # Actions' GITHUB_ENV may already hold earlier steps' lines: the step appends to them.
    (tmp_path / "github-env").write_text(PRIOR_ENV, encoding="utf-8")

    completed, env_file = run_step(HubConfig.model_validate(a_hub_document()), tmp_path, token)

    assert completed.returncode == 0, completed.stderr
    assert env_file.read_text(encoding="utf-8").splitlines() == [
        PRIOR_ENV.rstrip("\n"),
        *expected_lines(token, "https://github.com/acme/demo-hub"),
    ]
    assert "git+" not in env_file.read_text(encoding="utf-8")


@pytest.mark.parametrize("token", ["", None], ids=["empty", "unset"])
def test_sets_nothing_when_token_empty(token: str | None, tmp_path: Path) -> None:
    completed, env_file = run_step(HubConfig.model_validate(a_hub_document()), tmp_path, token)

    assert completed.returncode == 0, completed.stderr
    assert not env_file.exists()
    assert (completed.stdout, completed.stderr) == ("", "")


def test_never_shows_token_when_step_runs(tmp_path: Path) -> None:
    document = a_hub_document()
    config = HubConfig.model_validate(document)
    rendered = render_hub(config)

    completed, env_file = run_step(config, tmp_path, CLASSIC_TOKEN)

    assert completed.returncode == 0, completed.stderr
    assert CLASSIC_TOKEN not in completed.stdout + completed.stderr
    written = {file.path: file.content for file in rendered.files}
    written["hub.json"] = dump_json(document)
    written["hub.lock"] = lock_bytes(build_hub_lock(rendered=rendered, config=config))
    assert [path for path, content in written.items() if CLASSIC_TOKEN.encode() in content] == []
    # Only the job environment carries it, in the platform rule's key alone.
    carriers = [
        line for line in env_file.read_text(encoding="utf-8").splitlines() if CLASSIC_TOKEN in line
    ]
    assert [line.split("=", 1)[0] for line in carriers] == ["GIT_CONFIG_KEY_0"]


def test_maps_hub_to_itself_when_hub_url_shares_prefix(tmp_path: Path) -> None:
    platform_path = PLATFORM_URL.removeprefix("https://github.com/")
    hub_url = f"https://github.com/{platform_path}-hub"

    completed, env_file = run_step(config_with_hub(f"{platform_path}-hub"), tmp_path, CLASSIC_TOKEN)

    assert completed.returncode == 0, completed.stderr
    lines = env_file.read_text(encoding="utf-8").splitlines()
    assert lines == expected_lines(CLASSIC_TOKEN, hub_url)
    # insteadOf is a prefix match and the longest wins: the hub keeps its URL, the token goes
    # to the platform only.
    assert git_rewrites(
        lines, [hub_url, f"{hub_url}.git", PLATFORM_URL, f"{PLATFORM_URL}.git"], tmp_path
    ) == [
        hub_url,
        f"{hub_url}.git",
        f"https://x-access-token:{CLASSIC_TOKEN}@{PLATFORM_URL.removeprefix('https://')}",
        f"https://x-access-token:{CLASSIC_TOKEN}@{PLATFORM_URL.removeprefix('https://')}.git",
    ]


@pytest.mark.parametrize(
    "token",
    [
        CLASSIC_TOKEN + "\nLD_PRELOAD=/x",
        CLASSIC_TOKEN + "\r",
        CLASSIC_TOKEN + " x",
        CLASSIC_TOKEN + "@evil.example/",
        CLASSIC_TOKEN + "-x",
        CLASSIC_TOKEN + "\u00e9",
    ],
    ids=["newline", "carriage-return", "space", "url-characters", "dash", "non-ascii"],
)
def test_refuses_token_when_characters_unexpected(token: str, tmp_path: Path) -> None:
    (tmp_path / "github-env").write_text(PRIOR_ENV, encoding="utf-8")

    completed, env_file = run_step(HubConfig.model_validate(a_hub_document()), tmp_path, token)

    assert completed.returncode == 1
    assert completed.stderr == f"{REFUSAL}\n"
    assert completed.stdout == ""
    assert env_file.read_text(encoding="utf-8") == PRIOR_ENV


# AGH-49 (AC-49.7, E19): the token as the AC writes it (from fragments, as above), a repository of
# another org on github.com and the lines the step writes for it, spelled out so a change to how
# it builds them fails here.
TOKEN = "abc" + "_123"
GITHUB_REPOSITORY = "git+https://github.com/acme/agent-hub"
GITHUB_URL = "https://github.com/acme/agent-hub"
HUB_URL = "https://github.com/acme/demo-hub"
GITHUB_LINES = [
    "GIT_CONFIG_COUNT=2",
    f"GIT_CONFIG_KEY_0=url.https://x-access-token:{TOKEN}@github.com/acme/agent-hub.insteadOf",
    f"GIT_CONFIG_VALUE_0={GITHUB_URL}",
    f"GIT_CONFIG_KEY_1=url.{HUB_URL}.insteadOf",
    f"GIT_CONFIG_VALUE_1={HUB_URL}",
]
OTHER_HOST_NOTICE = (
    "Platform read credential: platform.repository is not on github.com; "
    "AGENT_HUB_READ_TOKEN is not used\n"
)
BAD_REPOSITORY_LINE = (
    "Platform read credential: platform.repository in hub.json must be "
    f"{PLATFORM_REPOSITORY_FORM}\n"
)
UNREADABLE_LINE = "Platform read credential: cannot read hub.json as JSON\n"
# Parts of the bad values that a message echoing them would show (E10): the credential's user,
# password and token, a port, a query and a scheme.
VALUE_PARTS = (*SECRET_PARTS, "8443", "ref=x", "git+ssh")
BAD_CASES = [case for case in REPOSITORY_CASES if not case.is_valid]


def case_name(case: RepositoryCase) -> str:
    return case.name


def a_hub_json(repository: object) -> str:
    document = a_hub_document()
    document["platform"]["repository"] = repository
    return json.dumps(document)


def demo_config() -> HubConfig:
    return HubConfig.model_validate(a_hub_document())


def test_maps_custom_repository_when_hub_sets_one(tmp_path: Path, hook_python: str) -> None:
    (tmp_path / "github-env").write_text(PRIOR_ENV, encoding="utf-8")

    completed, env_file = run_step(
        demo_config(),
        tmp_path,
        TOKEN,
        hub_json=a_hub_json(GITHUB_REPOSITORY),
        python=hook_python,
    )

    assert completed.returncode == 0, completed.stderr
    assert (completed.stdout, completed.stderr) == ("", "")
    assert env_file.read_text(encoding="utf-8").splitlines() == [
        PRIOR_ENV.rstrip("\n"),
        *GITHUB_LINES,
    ]


def test_rewrites_only_custom_url_when_git_configured(tmp_path: Path) -> None:
    completed, env_file = run_step(
        demo_config(), tmp_path, TOKEN, hub_json=a_hub_json(GITHUB_REPOSITORY)
    )

    assert completed.returncode == 0, completed.stderr
    lines = env_file.read_text(encoding="utf-8").splitlines()
    # The token goes to the hub's repository only: not to the hub, not to the default platform.
    assert git_rewrites(lines, [GITHUB_URL, HUB_URL, PLATFORM_URL], tmp_path) == [
        f"https://x-access-token:{TOKEN}@github.com/acme/agent-hub",
        HUB_URL,
        PLATFORM_URL,
    ]


@pytest.mark.parametrize(
    "repository",
    [
        CUSTOM_REPOSITORY,
        "git+https://GitHub.com/acme/agent-hub",
        "git+https://github.com.acme.test/acme/agent-hub",
    ],
    ids=["other-host", "mixed-case-github", "github-lookalike"],
)
def test_writes_no_mapping_when_repository_not_on_github(
    repository: str, tmp_path: Path, hook_python: str
) -> None:
    (tmp_path / "github-env").write_text(PRIOR_ENV, encoding="utf-8")

    completed, env_file = run_step(
        demo_config(), tmp_path, TOKEN, hub_json=a_hub_json(repository), python=hook_python
    )

    # E19: the token reaches github.com only; another host gets neither the mapping nor the
    # hub's self pair (it has nothing to protect without a token rule).
    assert completed.returncode == 0, completed.stderr
    assert (completed.stdout, completed.stderr) == (OTHER_HOST_NOTICE, "")
    assert env_file.read_text(encoding="utf-8") == PRIOR_ENV


@pytest.mark.parametrize("case", BAD_CASES, ids=case_name)
def test_exits_one_writing_nothing_when_repository_bad(
    case: RepositoryCase, tmp_path: Path, hook_python: str
) -> None:
    (tmp_path / "github-env").write_text(PRIOR_ENV, encoding="utf-8")

    completed, env_file = run_step(
        demo_config(), tmp_path, TOKEN, hub_json=a_hub_json(case.value), python=hook_python
    )

    assert completed.returncode == 1
    # One fixed line: the key and the accepted form, never the value (D-bad, E10).
    assert (completed.stdout, completed.stderr) == ("", BAD_REPOSITORY_LINE)
    assert env_file.read_text(encoding="utf-8") == PRIOR_ENV
    for part in (*VALUE_PARTS, TOKEN):
        assert part not in completed.stdout + completed.stderr, part


@pytest.mark.parametrize("hub_json", [None, "{"], ids=["missing", "invalid-json"])
def test_exits_one_writing_nothing_when_hub_json_unreadable(
    hub_json: str | None, tmp_path: Path, hook_python: str
) -> None:
    (tmp_path / "github-env").write_text(PRIOR_ENV, encoding="utf-8")

    completed, env_file = run_step(
        demo_config(), tmp_path, TOKEN, hub_json=hub_json, python=hook_python
    )

    assert completed.returncode == 1
    assert (completed.stdout, completed.stderr) == ("", UNREADABLE_LINE)
    assert env_file.read_text(encoding="utf-8") == PRIOR_ENV


def test_reads_no_hub_json_when_token_empty(tmp_path: Path) -> None:
    # No hub.json at all: without a token the step stops before reading it, as before AGH-49.
    completed, env_file = run_step(demo_config(), tmp_path, "", hub_json=None)

    assert completed.returncode == 0, completed.stderr
    assert (completed.stdout, completed.stderr) == ("", "")
    assert not env_file.exists()
