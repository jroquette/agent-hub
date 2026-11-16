"""The prompt secret hook, run on the rendered ``prompt_secret.py`` (AGH-814 AC-36).

The hook runs as Claude Code runs it on UserPromptSubmit: a file of a rendered demo hub on
``hook_python`` (a real 3.9), with the event on stdin, in an environment from scratch (``HOME`` and
``TMPDIR`` under ``tmp_path``). On a prompt that holds a secret's shape or a block of ``NAME=value``
lines, it prints one JSON line with only ``systemMessage`` and exits 0; on any other prompt (one
that only names a file, a secret one included), and on any error, it prints nothing and exits 0.
Secret-shaped values are built here from fragments, so no secret-shaped literal sits in the repo.
"""

import ast
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.hook_inputs import a_hook_input

HOOKS = "plugin/hub-workflow/hooks"
EVENT = "UserPromptSubmit"
ENV_FILE_HINT = "git-ignored env file"
ENV_FILE_SETTING = "hub.json's guard.readable_env_files"

type RunHook = Callable[..., subprocess.CompletedProcess[bytes]]

# (prompt, the secret-shaped part the warning must never quote)
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
GITHUB_TOKEN = "ghp" + "_" + "a1B2c3D4e5" * 3
STRIPE_KEY = "sk" + "_live_" + "a1B2c3D4e5F6g7H8"
SECRET_VALUE = "abcd" + "1234" + "efgh"
PEM_HEADER = "-" * 5 + "BEGIN RSA " + "PRIVATE" + " KEY" + "-" * 5
PEM_BODY = "MIIEow" + "IBAAKCAQEA" + "x7Yz" * 8
SECRET_SHAPE_PROMPTS = {
    "aws": (f"deploy with {AWS_KEY} please", AWS_KEY),
    "github": (f"the token is {GITHUB_TOKEN}", GITHUB_TOKEN),
    "stripe": (f"charge with\n{STRIPE_KEY}\nthen stop", STRIPE_KEY),
    "one-secret-line": ("AUTH" + "_SECRET=" + SECRET_VALUE, SECRET_VALUE),
    "token-colon": ("use API" + "_TOKEN: " + SECRET_VALUE + " for it", SECRET_VALUE),
    "private-key": (f"here it is:\n{PEM_HEADER}\n{PEM_BODY}\n", PEM_BODY),
}
NAME_VALUE_PROMPTS = {
    "plain": "DB_USER=app\nDB_PASSWORD=x1",
    "export": "set these:\nexport DB_USER=app\nexport DB_PASSWORD=x1\nthanks",
}
SILENT_PROMPTS = {
    "default": a_hook_input(EVENT)["prompt"],
    "one-name-value": "FOO=bar",
    "env-words": "use the env file",
    "names-env-local": "please put AUTH" + "_SECRET in .env" + ".local and read it",
    "names-env-example": "copy .env" + ".example to .env",
    "names-key-file": "look at the server" + ".key handling",
    "names-env-production": "cat .env" + ".production",
    "reference": "GITHUB" + "_TOKEN=$GITHUB" + "_TOKEN",
    "braced-reference": "AUTH" + "_SECRET=${AUTH" + "_SECRET}",
    "placeholder": "API" + "_KEY=<your key>",
    "masked": "DB" + "_PASSWORD=********",
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
    assert ENV_FILE_SETTING in message
    return message


def assert_silent(completed: subprocess.CompletedProcess[bytes]) -> None:
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == b""
    assert b"Traceback" not in completed.stderr


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
    [*SECRET_SHAPE_PROMPTS.values(), (NAME_VALUE_PROMPTS["plain"], "x1")],
    ids=[*SECRET_SHAPE_PROMPTS.keys(), "name-value"],
)
def test_never_quotes_the_secret_when_warning(
    prompt: str, secret: str, run_prompt: Callable[..., subprocess.CompletedProcess[bytes]]
) -> None:
    completed = run_prompt(prompt)

    assert_warns(completed)
    assert secret.encode() not in completed.stdout


def test_exits_zero_and_prints_nothing_when_reader_missing(
    hooks: Path, run_prompt: Callable[..., subprocess.CompletedProcess[bytes]]
) -> None:
    (hooks / "stdlib_reader.py").unlink()

    assert_silent(run_prompt(SECRET_SHAPE_PROMPTS["aws"][0]))


@pytest.mark.parametrize(
    "stdin",
    [b"", b"not json", b"[]", b'"x"', b"\xff", b'{"prompt": 5}'],
    ids=["empty", "text", "list", "string", "invalid-utf8", "prompt-not-str"],
)
def test_exits_zero_and_prints_nothing_when_stdin_is_not_json(
    stdin: bytes, run_prompt: Callable[..., subprocess.CompletedProcess[bytes]]
) -> None:
    assert_silent(run_prompt(stdin=stdin))


# The shapes are searched in windows of at most SHAPE_WINDOW characters, so a shape's backtracking
# is bounded by the window, not the line; the windows overlap, so a secret across one's edge is
# still whole in the next. The key is placed at every offset of the first three windows.
WINDOW_CODE = """
import json, sys
import prompt_secret

seen = []
shaped = prompt_secret.secret_shaped
prompt_secret.secret_shaped = lambda text: seen.append(len(text)) or shaped(text)
window = prompt_secret.SHAPE_WINDOW
key = sys.argv[1]
found = [
    prompt_secret.holds_secret("x" * start + key + "y" * (2 * window))
    for start in range(3 * window)
]
print(json.dumps({"window": window, "longest": max(seen), "missed": found.count(False)}))
"""


def test_finds_secret_across_window_edge_when_line_is_long(
    hooks: Path, *, hook_python: str, run_python: Callable[..., Any], tmp_path: Path
) -> None:
    result = run_python(hook_python, WINDOW_CODE, path=hooks, args=[AWS_KEY], cwd=tmp_path)

    assert result["longest"] <= result["window"]
    assert result["missed"] == 0


def test_warns_when_secret_ends_a_long_line(
    run_prompt: Callable[..., subprocess.CompletedProcess[bytes]],
) -> None:
    assert_warns(run_prompt("word " * 50_000 + AWS_KEY))


# AC-38: the hook imports the reader's secret shapes, the set the guard also uses, and defines one
# regex of its own, the NAME=value line; a copied pattern would drift from the guard's. It takes
# nothing from the guard: a file's name in a prompt is not a secret.
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


def imported_modules(module: ast.Module) -> set[str]:
    """Every module the code imports, by ``import x`` or ``from x import y``."""
    found: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


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


def test_takes_secret_shapes_from_reader_only_when_rendered(hooks: Path) -> None:
    path = hooks / "prompt_secret.py"
    module = ast.parse(path.read_text(), filename=str(path), feature_version=(3, 9))

    assert names_used_from(module, "stdlib_reader") & READER_NAMES
    assert "guard" not in imported_modules(module)
    assert regex_strings(module) == [NAME_VALUE_PATTERN]
