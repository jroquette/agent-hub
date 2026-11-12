"""The prompt secret hook, run on the rendered ``prompt_secret.py`` (AGH-814 AC-36).

The hook runs as Claude Code runs it on UserPromptSubmit: a file of a rendered demo hub on
``hook_python`` (a real 3.9), with the event on stdin, in an environment from scratch (``HOME`` and
``TMPDIR`` under ``tmp_path``). On a prompt that names a secret file, holds a secret's shape or a
block of ``NAME=value`` lines, it prints one JSON line with only ``systemMessage`` and exits 0; on
any other prompt, and on any error, it prints nothing and exits 0. Secret-shaped values are built
here from fragments, so no secret-shaped literal sits in the repo.
"""

import ast
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.hook_inputs import a_hook_input

HOOKS = "plugin/hub-workflow/hooks"
EVENT = "UserPromptSubmit"
ENV_FILE_HINT = "git-ignored env file"

type RunHook = Callable[..., subprocess.CompletedProcess[bytes]]

SECRET_FILE_PROMPTS = {
    "env-file": "cat .env.production",
    "ssh-key": "use ~/.ssh/id_ed25519",
    "pem": "server.pem",
}
# (prompt, the secret-shaped part the warning must never quote)
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
GITHUB_TOKEN = "ghp" + "_" + "a1B2c3D4e5" * 3
STRIPE_KEY = "sk" + "_live_" + "a1B2c3D4e5F6g7H8"
SECRET_SHAPE_PROMPTS = {
    "aws": (f"deploy with {AWS_KEY} please", AWS_KEY),
    "github": (f"the token is {GITHUB_TOKEN}", GITHUB_TOKEN),
    "stripe": (f"charge with\n{STRIPE_KEY}\nthen stop", STRIPE_KEY),
}
NAME_VALUE_PROMPTS = {
    "plain": "DB_USER=app\nDB_PASSWORD=x1",
    "export": "set these:\nexport DB_USER=app\nexport DB_PASSWORD=x1\nthanks",
}
SILENT_PROMPTS = {
    "default": a_hook_input(EVENT)["prompt"],
    "one-name-value": "FOO=bar",
    "env-words": "use the env file",
}


@pytest.fixture
def hooks(rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig) -> Path:
    """The hooks folder of the rendered demo hub."""
    return rendered_hub(demo_config).resolve() / HOOKS


@pytest.fixture
def run_prompt(
    hooks: Path, *, hook_python: str, run_hook_file: RunHook, tmp_path: Path
) -> Callable[..., subprocess.CompletedProcess[bytes]]:
    """Run the hook with ``stdin`` (default: the event of ``prompt``) from the hub."""
    home, temp = tmp_path / "home", tmp_path / "tmp"
    home.mkdir()
    temp.mkdir()

    def run(prompt: str = "", *, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
        data = (
            stdin if stdin is not None else json.dumps(a_hook_input(EVENT, prompt=prompt)).encode()
        )
        return run_hook_file(
            hook_python,
            hooks / "prompt_secret.py",
            stdin=data,
            cwd=hooks.parent.parent.parent,
            env={"HOME": str(home), "TMPDIR": str(temp)},
        )

    return run


def assert_warns(completed: subprocess.CompletedProcess[bytes]) -> str:
    """Exit 0, nothing on stderr, exactly one JSON line with only ``systemMessage``; returns it."""
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == b""
    lines = completed.stdout.decode().splitlines()
    assert len(lines) == 1, completed.stdout
    output = json.loads(lines[0])
    assert list(output) == ["systemMessage"]
    message = output["systemMessage"]
    assert isinstance(message, str)
    assert ENV_FILE_HINT in message
    return message


def assert_silent(completed: subprocess.CompletedProcess[bytes]) -> None:
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == b""
    assert b"Traceback" not in completed.stderr


@pytest.mark.parametrize("prompt", SECRET_FILE_PROMPTS.values(), ids=SECRET_FILE_PROMPTS.keys())
def test_warns_when_prompt_names_secret_file(
    prompt: str, run_prompt: Callable[..., subprocess.CompletedProcess[bytes]]
) -> None:
    assert_warns(run_prompt(prompt))


@pytest.mark.parametrize(
    "prompt", [p for p, _ in SECRET_SHAPE_PROMPTS.values()], ids=SECRET_SHAPE_PROMPTS.keys()
)
def test_warns_when_prompt_holds_secret_shape(
    prompt: str, run_prompt: Callable[..., subprocess.CompletedProcess[bytes]]
) -> None:
    assert_warns(run_prompt(prompt))


@pytest.mark.parametrize("prompt", NAME_VALUE_PROMPTS.values(), ids=NAME_VALUE_PROMPTS.keys())
def test_warns_when_prompt_holds_name_value_block(
    prompt: str, run_prompt: Callable[..., subprocess.CompletedProcess[bytes]]
) -> None:
    assert_warns(run_prompt(prompt))


@pytest.mark.parametrize("prompt", SILENT_PROMPTS.values(), ids=SILENT_PROMPTS.keys())
def test_stays_silent_when_prompt_holds_neither(
    prompt: str, run_prompt: Callable[..., subprocess.CompletedProcess[bytes]]
) -> None:
    assert_silent(run_prompt(prompt))


@pytest.mark.parametrize(
    ("prompt", "secret"),
    [
        *SECRET_SHAPE_PROMPTS.values(),
        (SECRET_FILE_PROMPTS["env-file"], ".env.production"),
        (SECRET_FILE_PROMPTS["ssh-key"], "id_ed25519"),
        (NAME_VALUE_PROMPTS["plain"], "x1"),
    ],
    ids=[*SECRET_SHAPE_PROMPTS.keys(), "env-file", "ssh-key", "name-value"],
)
def test_never_quotes_the_secret_when_warning(
    prompt: str, secret: str, run_prompt: Callable[..., subprocess.CompletedProcess[bytes]]
) -> None:
    completed = run_prompt(prompt)

    assert_warns(completed)
    assert secret.encode() not in completed.stdout


# guard.py gone: the import fails in the hook; hubhooks.py or stdlib_reader.py gone: the guard's
# own import-failure branch prints a PreToolUse "ask" line and exits, which must reach neither
# stdout nor the exit code.
@pytest.mark.parametrize("missing", ["guard.py", "hubhooks.py", "stdlib_reader.py"])
def test_exits_zero_and_prints_nothing_when_guard_missing(
    missing: str, hooks: Path, run_prompt: Callable[..., subprocess.CompletedProcess[bytes]]
) -> None:
    (hooks / missing).unlink()

    assert_silent(run_prompt(SECRET_FILE_PROMPTS["env-file"]))


@pytest.mark.parametrize(
    "stdin",
    [b"", b"not json", b"[]", b'"x"', b"\xff", b'{"prompt": 5}'],
    ids=["empty", "text", "list", "string", "invalid-utf8", "prompt-not-str"],
)
def test_exits_zero_and_prints_nothing_when_stdin_is_not_json(
    stdin: bytes, run_prompt: Callable[..., subprocess.CompletedProcess[bytes]]
) -> None:
    assert_silent(run_prompt(stdin=stdin))


# AC-38: the hook imports the guard's secret-name rule and the reader's secret shapes, and defines
# one regex of its own, the NAME=value line; a copied pattern would drift from the guard's.
GUARD_NAMES = {"_secret_tokens", "SECRET_TOKEN", "SECRET_CHUNK"}
READER_NAMES = {"secret_shaped", "SECRET_SHAPES"}
REGEX_CALLS = {"LazyPattern", "compile"}
NAME_VALUE_PATTERN = r"^\s*(?:export\s+)?[A-Z][A-Z0-9_]*=\S"


def names_used_from(module: ast.Module, source: str) -> set[str]:
    """The names the module takes from ``source``: ``from source import x`` or ``source.x``."""
    names: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.module == source:
            names |= {alias.name for alias in node.names}
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == source
        ):
            names.add(node.attr)
    return names


def regex_strings(module: ast.Module) -> list[str]:
    """Every string constant passed to ``LazyPattern(...)`` or ``re.compile(...)``."""
    found: list[str] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name in REGEX_CALLS:
            found += [
                child.value
                for argument in [*node.args, *(keyword.value for keyword in node.keywords)]
                for child in ast.walk(argument)
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
            ]
    return found


def test_imports_guard_and_reader_patterns_when_rendered(hooks: Path) -> None:
    path = hooks / "prompt_secret.py"
    module = ast.parse(path.read_text(), filename=str(path), feature_version=(3, 9))

    assert names_used_from(module, "guard") & GUARD_NAMES
    assert names_used_from(module, "stdlib_reader") & READER_NAMES
    assert regex_strings(module) == [NAME_VALUE_PATTERN]
