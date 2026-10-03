"""The CLI and the hooks' reader resolve one developer's identity alike (AC-65.10).

Each shared case (``agent_hub.core.testing.identity_cases``) becomes a rendered demo hub: its
``hub.json`` holds the case's identity keys and transport, its ``hub.local.json`` the case's text,
and the hub repo's own ``.git/config`` the case's ``user.name``/``user.email``, written by git
itself. ``GIT_CONFIG_GLOBAL`` is an empty file and the system config is off, so a value is found
only by running git in the hub. The CLI reads both files from disk and resolves as its commands
do (the merged config, then ``branch_prefix_or_lines`` for the prefix); the hooks through
``load_config`` in a child on ``hook_python``. Both must give the case's values. This is the one
generator test that imports the CLI (E19): tests sit outside import-linter's ``agent_hub`` root.
"""

import ast
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest

from agent_hub.cli.effective_config import (
    EffectiveConfig,
    branch_prefix_or_lines,
    effective_or_problems,
    git_identity_reader,
)
from agent_hub.cli.hub_config_reader import DISTRIBUTION, FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import local_home
from agent_hub.core.hub_config.effective_identity import (
    IdentityKey,
    IdentityValues,
    resolve_identity,
)
from agent_hub.core.hub_config.local_config import LOCAL_FILE
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.identity_cases import IDENTITY_CASES, LOCAL_KEYS, IdentityCase

HOOKS = "plugin/hub-workflow/hooks"
# The hooks' effective values, in ``LOCAL_KEYS`` order, then the prefix's source.
HOOK_IDENTITY_CODE = (
    "import json\nfrom hubhooks import load_config\ncfg = load_config(None)\n"
    "print(json.dumps([cfg.branch_prefix, cfg.author_name, cfg.author_email, cfg.transport,"
    " cfg.identity.prefix_source()]))\n"
)
GIT_KEYS = {"user.name": "git_name", "user.email": "git_email"}
# Where G3's ``LOCAL_PATHS`` is declared (read as source: tests never import each other).
READER_TESTS = Path(__file__).with_name("test_hub_json_reader.py")


def hub_document(case: IdentityCase) -> dict[str, Any]:
    """The builders' ``hub.json`` with the case's identity keys and transport in place.

    Pinned to the running release, so the CLI's reader takes it.
    """
    document = a_hub_document()
    document["platform"]["version"] = version(DISTRIBUTION)
    for key in IdentityKey:
        document["project"].pop(key.value, None)
    document["project"].update(case.hub_project)
    if case.hub_transport is not None:
        document["tracker"]["transport"] = case.hub_transport
    return document


def write_git_identity(case: IdentityCase, hub: Path, tmp_path: Path) -> dict[str, str]:
    """The case's git values in the hub repo's config, written and read back by git itself.

    Git quotes and escapes what it must (a trailing space, a control character); reading each
    value back shows the file holds exactly the case's value, plus the newline git prints. The
    returned environment gives git an empty global config and no system config.
    """
    git = shutil.which("git")
    assert git is not None
    config = hub / ".git" / "config"
    for git_key, field in GIT_KEYS.items():
        value: str | None = getattr(case, field)
        if value is None:
            continue
        subprocess.run([git, "config", "--file", str(config), git_key, value], check=True)  # noqa: S603
        read = subprocess.run(  # noqa: S603 - the git found above, fixed argv
            [git, "config", "--file", str(config), "--get", git_key],
            capture_output=True,
            check=True,
        )
        assert read.stdout == value.encode() + b"\n"
    empty_global = tmp_path / "empty-gitconfig"
    empty_global.write_bytes(b"")
    home = tmp_path / "home"
    home.mkdir()
    return {"GIT_CONFIG_GLOBAL": str(empty_global), "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(home)}


@pytest.fixture
def case_hub(rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig) -> Path:
    """The rendered demo hub, a git repo of its own (its main checkout), without ``hub.json``."""
    hub = rendered_hub(demo_config).resolve()
    subprocess.run(  # noqa: S603 - fixed argv
        ["git", "init", "-q", str(hub)],  # noqa: S607 - git from PATH
        check=True,
        env={
            "PATH": os.environ.get("PATH", os.defpath),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        },
    )
    return hub


def cli_values(
    hub: Path,
) -> tuple[dict[str, str | None], str | None, str | list[str]] | list[str | None]:
    """The CLI's effective values, prefix source and ``branch_prefix_or_lines``, or the paths of
    its local file problems; both files read from ``hub`` as its commands read them."""
    config = load_hub_config_or_exit(hub / FILE_LABEL)
    loaded = effective_or_problems(config, home=local_home(hub, environ=os.environ))
    if not isinstance(loaded, EffectiveConfig):
        return [problem.path for problem in loaded]
    read_git, _ = git_identity_reader(loaded.home)
    resolved = resolve_identity(
        local=IdentityValues.of(loaded.local.project),
        # Merged, as branch_prefix_or_lines passes it.
        hub=IdentityValues.of(loaded.config.project),
        keys=tuple(IdentityKey),
        read_git=read_git,
    )
    values: dict[str, str | None] = {
        f"project.{key.value}": None if sourced is None else sourced.value
        for key, sourced in resolved.values.items()
    }
    values["tracker.transport"] = loaded.config.tracker.transport
    prefix = resolved.values[IdentityKey.BRANCH_PREFIX]
    source = None if prefix is None else prefix.prefix_source
    return values, source, branch_prefix_or_lines(loaded)


@pytest.mark.parametrize("case", IDENTITY_CASES, ids=[case.name for case in IDENTITY_CASES])
def test_agrees_with_case_when_cli_and_hooks_resolve(
    case: IdentityCase,
    *,
    case_hub: Path,
    hook_python: str,
    run_python: Callable[..., Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (case_hub / FILE_LABEL).write_text(json.dumps(hub_document(case)), encoding="utf-8")
    if case.local_text is not None:
        (case_hub / LOCAL_FILE).write_text(case.local_text, encoding="utf-8")
    git_env = write_git_identity(case, case_hub, tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    for name, value in git_env.items():
        monkeypatch.setenv(name, value)

    hooks = run_python(
        hook_python, HOOK_IDENTITY_CODE, path=case_hub / HOOKS, cwd=elsewhere, env=git_env
    )
    cli = cli_values(case_hub)

    # The hooks give "" for no value.
    *hook_values, hook_source = [value or None for value in hooks]
    assert dict(zip(LOCAL_KEYS, hook_values, strict=True)) == case.expected
    assert hook_source == case.prefix_source
    if case.local_is_valid:
        prefix = case.expected["project.branch_prefix"]
        assert isinstance(cli, tuple)
        values, source, prefix_or_lines = cli
        assert (values, source) == (case.expected, case.prefix_source)
        if prefix is None:
            assert isinstance(prefix_or_lines, list)
        else:
            assert prefix_or_lines == prefix
    else:
        assert cli == [case.problem_path]


def declared_local_paths() -> tuple[tuple[str | int, ...], ...]:
    """``LOCAL_PATHS`` as ``test_hub_json_reader.py`` declares it."""
    tree = ast.parse(READER_TESTS.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "LOCAL_PATHS"
            and node.value is not None
        ):
            paths: tuple[tuple[str | int, ...], ...] = ast.literal_eval(node.value)
            return paths
    raise AssertionError(f"no LOCAL_PATHS in {READER_TESTS.name}")


def test_lists_reader_paths_when_parity_cases_cover_them() -> None:
    """Every optional key the reader test leaves to these cases (G3) is one they assert."""
    asserted = {key for case in IDENTITY_CASES for key in case.expected}
    local_paths = {".".join(str(part) for part in path) for path in declared_local_paths()}

    assert local_paths
    assert local_paths <= asserted
