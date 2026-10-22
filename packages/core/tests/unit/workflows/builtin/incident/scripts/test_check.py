"""The incident pack's ``check.py`` (AGH-483), in process: which agent-written checks it runs.

A check is an argv list a model wrote after reading untrusted text, so ``refusal`` allows only
read-only inspection programs, git's read subcommands without the options that run a program or
write a file, and paths inside the checkout; ``child_env`` passes nothing from the parent.
"""

import importlib.util
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/incident/scripts/check.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.incident.scripts.check"
CHILD_ENV_KEYS = {
    "PATH",
    "LANG",
    "HOME",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_CONFIG_GLOBAL",
    "GIT_TERMINAL_PROMPT",
    "GIT_OPTIONAL_LOCKS",
    "PAGER",
}
GIT_PREFIX = [
    "git",
    "-c",
    "core.pager=cat",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "diff.external=",
    "--no-pager",
]


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "grep", "-n", "timeout", "--", "src"],
        ["git", "log", "-S", "x", "--oneline"],
        ["git", "log", "--first-parent", "main..HEAD", "--", "app/payment.py"],
        ["git", "show", "HEAD~2:app/config.py"],
        ["test", "-f", "app/config.py"],
        ["grep", "-rn", "x", "src"],
        ["wc", "-l", "a.txt"],
        ["tail", "-n", "20", "log.txt"],
        ["cat", "app/x=y.txt"],
    ],
)
def test_allows_read_only_inspection_when_argv_is_on_the_list(argv: list[str]) -> None:
    assert load().refusal(argv) is None


@pytest.mark.parametrize(
    ("argv", "reason"),
    [
        (["sh", "-c", "true"], "program"),
        (["/bin/cat", "x"], "program"),
        (["rg", "--pre", "x", "y"], "program"),
        (["find", ".", "-exec", "rm", "{}", ";"], "program"),
        (["python3", "-c", "print(1)"], "program"),
        (["git", "-c", "core.pager=sh", "log"], "git subcommand"),
        (["git", "push"], "git subcommand"),
        (["git", "config", "x"], "git subcommand"),
        (["git"], "git subcommand"),
        (["git", "grep", "-O", "x"], "option"),
        (["git", "grep", "-nOsh", "x"], "option"),
        (["git", "grep", "--open-files-in-pager=sh", "x"], "option"),
        (["git", "grep", "--open", "x"], "option"),
        (["git", "log", "--output=/tmp/x"], "option"),
        (["git", "log", "--outp=x"], "option"),
        (["git", "log", "-p", "--output-indicator-new=x"], "option"),
        (["git", "diff", "--ext-diff"], "option"),
        (["git", "show", "--textconv", "HEAD"], "option"),
        (["git", "cat-file", "--filters", "HEAD:x"], "option"),
        (["git", "log", "--exec=x"], "option"),
        (["git", "log", "--upload-pack=x"], "option"),
        (["git", "log", "--git-dir=x"], "option"),
        (["git", "log", "--work-tree=x"], "option"),
        (["git", "diff", "--no-index", "a", "b"], "option"),
        (["cat", "/etc/passwd"], "path"),
        (["cat", "../../x"], "path"),
        (["cat", "a/../../x"], "path"),
        (["grep", "--file=/etc/x", "y"], "path"),
        (["grep", "-f/etc/x", "y"], "path"),
        (["cat", "~/.aws/credentials"], "path"),
        (["git", "log", "--", "../x"], "path"),
        (["tail", "-f", "log"], "follow"),
        (["tail", "-F", "log"], "follow"),
        (["tail", "-nf", "log"], "follow"),
        (["tail", "--follow=name", "log"], "follow"),
        (["tail", "--fo", "log"], "follow"),
        (["cat", "a\x00b"], "control"),
        (["cat", "a\nb"], "control"),
        (["cat", "a\x9bb"], "control"),
        (["cat", *(["x"] * 16)], "elements"),
        ([], "elements"),
        (["cat", "x" * 257], "256"),
    ],
    ids=lambda value: "-".join(value)[:60] if isinstance(value, list) else value,
)
def test_refuses_check_when_argv_escapes_the_allow_list(argv: list[str], reason: str) -> None:
    refused = load().refusal(argv)

    assert refused is not None
    assert reason in refused
    assert len(refused) <= 200


def test_refuses_check_when_argv_is_not_a_list_of_text() -> None:
    check = load()

    assert check.refusal("git log") is not None
    assert check.refusal(["git", 1]) is not None


def test_passes_no_inherited_secret_when_child_env_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("GITHUB_TOKEN", "LINEAR_API_KEY", "AWS_PROFILE", "GIT_DIR", "GIT_CONFIG"):
        monkeypatch.setenv(name, "secret")

    env = load().child_env("/usr/bin:/bin", str(tmp_path))

    assert set(env) == CHILD_ENV_KEYS
    assert "secret" not in env.values()
    assert env["HOME"] == str(tmp_path)
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["PAGER"] == "cat"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["git", "grep", "-q", "x"], [*GIT_PREFIX, "grep", "-q", "x"]),
        (
            ["git", "log", "-p"],
            [*GIT_PREFIX, "log", "--no-ext-diff", "--no-textconv", "-p"],
        ),
        (["git", "blame", "a.py"], [*GIT_PREFIX, "blame", "--no-textconv", "a.py"]),
        (["cat", "a.py"], ["cat", "a.py"]),
    ],
)
def test_runs_git_with_its_safe_prefix_when_command_built(
    argv: list[str], expected: list[str]
) -> None:
    assert load().command(argv) == expected
