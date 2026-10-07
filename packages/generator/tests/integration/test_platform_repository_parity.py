"""The five readers of ``platform.repository`` take the same values (AGH-49 AC-49.8, E2, E19).

Each shared case (``agent_hub.core.testing.platform_repository_cases``) becomes a ``hub.json``:
the demo document without a project author, its ``platform.repository`` set to the case's value.
Five readers give one verdict per case, accepted or rejected, and each must equal the case's
``is_valid``. The model: ``HubConfig`` validates, or reports one error, at the key. The rest run
from one demo render, on ``hook_python`` (this interpreter and a real 3.9): the hooks' stdlib
reader in one child over every case; the ``hub`` shim, cloud setup and the CI step each with a
``python3`` link to it first on ``PATH``, since their one-liners are Python that no linter sees.
The shim: accepted when it calls the fake ``uvx`` and exits 0, rejected on its fixed line. Cloud
setup, with no ``GH_TOKEN``, no author and no ``uvx``: accepted when it gets as far as "uv is not
installed", rejected on its fixed line, so no git is needed. The CI step, with a token: accepted
on exit 0 (the five lines for a ``github.com`` URL, else the notice and nothing written; E19),
rejected on exit 1 and its fixed line. Any other outcome is recorded as such and fails the case.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.platform_repository import PLATFORM_REPOSITORY_FORM
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.platform_repository_cases import REPOSITORY_CASES, RepositoryCase

HOOKS = "plugin/hub-workflow/hooks"
CLOUD_SETUP = "scripts/cloud-setup.sh"
CI = ".github/workflows/ci.yml"
CI_STEP = "      - name: Platform read credential\n"
CI_RUN_HEAD = "        run: |\n"
CI_BLOCK_INDENT = " " * 10
# Actions' default `shell: bash` on Linux.
CI_BASH_FLAGS = ("--noprofile", "--norc", "-eo", "pipefail")
TIMEOUT = 30
VERSION = "4.5.6"
HUB_URL = "https://github.com/acme/demo-hub"
# A synthetic token, built from fragments so no token-shaped literal sits in the source.
TOKEN = "gh" + "p_" + "x" * 36
PRIOR_ENV = "PRIOR=kept\n"
ACCEPTED = "accepted"
REJECTED = "rejected"
SHIM_LINE = f"hub: platform.repository in hub.json must be {PLATFORM_REPOSITORY_FORM}\n"
CLOUD_LINE = f"cloud-setup: platform.repository in hub.json must be {PLATFORM_REPOSITORY_FORM}\n"
CLOUD_NO_UV = (
    "cloud-setup: uv is not installed (no uvx on PATH); "
    "see https://docs.astral.sh/uv/getting-started/installation/\n"
)
CI_LINE = (
    "Platform read credential: platform.repository in hub.json must be "
    f"{PLATFORM_REPOSITORY_FORM}\n"
)
CI_NOTICE = (
    "Platform read credential: platform.repository is not on https://github.com/ "
    "(exact, lowercase); AGENT_HUB_READ_TOKEN is not used\n"
)
# The stdlib reader's (repository, has_bad_repository) for each hub.json path in argv[1] (JSON).
READER_CODE = """
import json
import stdlib_reader as reader
verdicts = []
for path in json.loads(sys.argv[1]):
    platform = reader.load_hub_file(path).platform
    verdicts.append([platform.repository, platform.has_bad_repository])
print(json.dumps(verdicts))
"""

type Verdicts = dict[str, str]


def case_document(case: RepositoryCase) -> dict[str, Any]:
    """The demo ``hub.json`` pinned to ``VERSION``, with no author and the case's repository."""
    document = a_hub_document()
    document["platform"]["version"] = VERSION
    document["platform"]["repository"] = case.value
    del document["project"]["author_name"]
    del document["project"]["author_email"]
    return document


def expected_verdicts() -> Verdicts:
    return {case.name: ACCEPTED if case.is_valid else REJECTED for case in REPOSITORY_CASES}


def outcome(completed: subprocess.CompletedProcess[str]) -> str:
    """An unexpected run, as the verdict that fails the comparison."""
    return f"exit {completed.returncode}: {completed.stdout!r} {completed.stderr!r}"


def run_tool(
    argv: list[str], *, cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - an absolute shell, a rendered script, no shell
        argv, capture_output=True, text=True, check=False, cwd=cwd, env=env, timeout=TIMEOUT
    )


def which(name: str) -> str:
    found = shutil.which(name)
    assert found is not None, f"the parity test runs {name}: install it"
    return os.path.realpath(found)


def ci_block(hub: Path) -> str:
    """The CI step's ``run: |`` block as bash reads it: its lines at the block's indent."""
    ci = (hub / CI).read_text(encoding="utf-8")
    step = ci[ci.index(CI_STEP) :]
    body = step[step.index(CI_RUN_HEAD) + len(CI_RUN_HEAD) :]
    lines: list[str] = []
    for line in body.splitlines(keepends=True):
        if line.strip() and not line.startswith(CI_BLOCK_INDENT):
            break
        lines.append(line.removeprefix(CI_BLOCK_INDENT))
    assert lines, ci
    return "".join(lines)


def ci_lines(repository: str) -> str:
    """What the step appends for a repository on github.com: the token pair, then the hub's."""
    url = repository.removeprefix("git+")
    return (
        "GIT_CONFIG_COUNT=2\n"
        f"GIT_CONFIG_KEY_0=url.https://x-access-token:{TOKEN}@{url.removeprefix('https://')}"
        ".insteadOf\n"
        f"GIT_CONFIG_VALUE_0={url}\n"
        f"GIT_CONFIG_KEY_1=url.{HUB_URL}.insteadOf\n"
        f"GIT_CONFIG_VALUE_1={HUB_URL}\n"
    )


def model_verdict(document: dict[str, Any]) -> str:
    try:
        HubConfig.model_validate(document)
    except ValidationError as error:
        locations = [problem["loc"] for problem in error.errors()]
        return REJECTED if locations == [("platform", "repository")] else repr(locations)
    return ACCEPTED


def reader_verdicts(
    paths: list[Path], cases: list[RepositoryCase], *, python: str, hub: Path, run: Any
) -> Verdicts:
    read = run(python, READER_CODE, path=hub / HOOKS, args=[json.dumps([str(p) for p in paths])])
    verdicts: Verdicts = {}
    for case, (repository, has_bad) in zip(cases, read, strict=True):
        if (repository, has_bad) == (case.value, False):
            verdicts[case.name] = ACCEPTED
        elif (repository, has_bad) == (None, True):
            verdicts[case.name] = REJECTED
        else:
            verdicts[case.name] = repr((repository, has_bad))
    return verdicts


def shim_verdict(hub: Path, *, cwd: Path, bin_dir: Path, log: Path) -> str:
    log.unlink(missing_ok=True)
    argv = [which("sh"), str(hub / "hub"), "brief"]
    completed = run_tool(argv, cwd=cwd, env={"PATH": str(bin_dir)})
    called = log.exists() and log.read_text(encoding="utf-8") != ""
    if completed.returncode == 0 and called:
        return ACCEPTED
    if not called and (completed.returncode, completed.stdout, completed.stderr) == (
        1,
        "",
        SHIM_LINE,
    ):
        return REJECTED
    return outcome(completed)


def cloud_verdict(hub: Path, *, cwd: Path, bin_dir: Path, home: Path) -> str:
    completed = run_tool(
        [which("bash"), str(hub / CLOUD_SETUP)],
        cwd=cwd,
        env={"PATH": str(bin_dir), "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1"},
    )
    if (completed.returncode, completed.stderr) == (1, CLOUD_NO_UV):
        return ACCEPTED
    if (completed.returncode, completed.stdout, completed.stderr) == (1, "", CLOUD_LINE):
        return REJECTED
    return outcome(completed)


def ci_verdict(block: str, value: object, *, cwd: Path, bin_dir: Path, env_file: Path) -> str:
    env_file.write_text(PRIOR_ENV, encoding="utf-8")
    completed = run_tool(
        [which("bash"), *CI_BASH_FLAGS, "-c", block],
        cwd=cwd,
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.defpath}",
            "GITHUB_ENV": str(env_file),
            "TOKEN": TOKEN,
        },
    )
    written = env_file.read_text(encoding="utf-8").removeprefix(PRIOR_ENV)
    # E19: the token mapping for a URL on https://github.com/ (exact, lowercase) only.
    if isinstance(value, str) and value.startswith("git+https://github.com/"):
        accepted = ("", ci_lines(value))
    else:
        accepted = (CI_NOTICE, "")
    if (completed.returncode, completed.stderr) == (0, "") and (
        completed.stdout,
        written,
    ) == accepted:
        return ACCEPTED
    if (completed.returncode, completed.stdout, completed.stderr, written) == (1, "", CI_LINE, ""):
        return REJECTED
    return outcome(completed)


@pytest.fixture
def case_hub(rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig) -> Path:
    """The rendered demo hub (modules ``cloud`` and ``bench``): the shim, the hooks, cloud setup
    and CI."""
    return rendered_hub(demo_config).resolve()


def test_accepts_same_values_when_readers_check_cases(
    *,
    case_hub: Path,
    hook_python: str,
    run_python: Callable[..., Any],
    fake_uv_bin: Path,
    tmp_path: Path,
) -> None:
    (fake_uv_bin / "python3").symlink_to(os.path.realpath(hook_python))
    python_only = tmp_path / "python-only"
    python_only.mkdir()
    (python_only / "python3").symlink_to(os.path.realpath(hook_python))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    documents = tmp_path / "cases"
    documents.mkdir()
    block = ci_block(case_hub)
    cases = list(REPOSITORY_CASES)
    verdicts: dict[str, Verdicts] = {"model": {}, "shim": {}, "cloud setup": {}, "CI step": {}}
    paths: list[Path] = []
    for case in cases:
        document = case_document(case)
        text = json.dumps(document)
        path = documents / f"{case.name}.json"
        path.write_text(text, encoding="utf-8")
        paths.append(path)
        (case_hub / "hub.json").write_text(text, encoding="utf-8")
        verdicts["model"][case.name] = model_verdict(document)
        verdicts["shim"][case.name] = shim_verdict(
            case_hub, cwd=elsewhere, bin_dir=fake_uv_bin, log=fake_uv_bin / "uvx.log"
        )
        verdicts["cloud setup"][case.name] = cloud_verdict(
            case_hub, cwd=elsewhere, bin_dir=python_only, home=home
        )
        verdicts["CI step"][case.name] = ci_verdict(
            block, case.value, cwd=case_hub, bin_dir=python_only, env_file=tmp_path / "github-env"
        )
    verdicts["reader"] = reader_verdicts(
        paths, cases, python=hook_python, hub=case_hub, run=run_python
    )

    expected = expected_verdicts()
    assert {ACCEPTED, REJECTED} <= set(expected.values())
    for reader, given in verdicts.items():
        assert given == expected, reader
