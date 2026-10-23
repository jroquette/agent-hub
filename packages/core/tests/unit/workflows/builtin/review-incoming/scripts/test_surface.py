"""The review-incoming pack's ``surface.py`` (AGH-493): whether a PR's diff touches a risky
surface (AGH-442's six categories), decided by path and added-line rules, failing closed."""

import json
from types import ModuleType
from typing import Any

import pytest

# The conftest's ``Clone``: a hub, its repo's clone, ``base`` and ``head``.
type Clone = Any

RISKY_RUN = "import subprocess\n\n\ndef run(cmd):\n    return subprocess.run(cmd, shell=True)\n"


@pytest.fixture
def surface(script: Any) -> ModuleType:
    module: ModuleType = script("surface")
    return module


@pytest.fixture
def run(surface: ModuleType, clone: Clone, capsys: pytest.CaptureFixture[str]) -> Any:
    def running() -> tuple[int, Any]:
        code = surface.main(["--path", str(clone.repo), "--base", clone.base, "--head", clone.head])
        out = capsys.readouterr().out
        return code, json.loads(out) if code == 0 else None

    return running


def a_diff(path: str, *added: str, removed: tuple[str, ...] = ()) -> str:
    lines = [f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}", "@@ -1,1 +4,2 @@"]
    lines += [f"-{line}" for line in removed] + [f"+{line}" for line in added]
    return "\n".join(lines) + "\n"


def test_marks_risky_when_diff_adds_subprocess_call(clone: Clone, run: Any) -> None:
    clone.commit({"app/run.py": RISKY_RUN})

    code, result = run()

    assert code == 0
    assert result["risky"] is True
    assert "subprocesses" in result["categories"]
    assert {"category": "subprocesses", "path": "app/run.py", "line": 5, "rule": "shell=True"} in (
        result["hits"]
    )
    assert result["truncated"] is False


@pytest.mark.parametrize(
    ("case"),
    [
        ("app/handler.py", "    name = request.args['name']", "input handling"),
        ("app/view.js", "  el.innerHTML = text;", "input handling"),
        ("app/guard.py", "    if user.is_admin:", "auth"),
        ("app/settings.py", "KEY = os.getenv('SERVICE')", "secrets"),
        ("app/tool.js", "child_process.exec(cmd)", "subprocesses"),
        ("app/files.py", "    open(os.path.join(root, name))", "file paths"),
        ("app/load.py", "    data = pickle.loads(blob)", "parsing"),
        ("app/login.py", "x = 1", "auth"),
        ("config/.env.example", "X=1", "secrets"),
        (".github/workflows/ci.yml", "    runs-on: ubuntu-latest", "subprocesses"),
    ],
    ids=[
        "request",
        "inner-html",
        "is-admin",
        "getenv",
        "child-process",
        "path-join",
        "pickle",
        "login-path",
        "env-path",
        "workflow-path",
    ],
)
def test_marks_each_category_when_its_rule_matches(
    surface: ModuleType, case: tuple[str, str, str]
) -> None:
    path, added, category = case

    result = surface.classify(a_diff(path, added), cut=False)

    assert result["risky"] is True
    assert category in result["categories"]


def test_stays_clean_when_diff_only_changes_docs_and_tests_of_pure_code(
    clone: Clone, run: Any
) -> None:
    clone.commit(
        {
            "README.md": "# Api\n\nAdds two numbers.\n",
            "app/core.py": "def add(a, b):\n    return a + b\n\n\n"
            "def twice(a):\n    return 2 * a\n",
            "tests/test_core.py": "from app.core import twice\n\n\ndef test_doubles():\n"
            "    assert twice(2) == 4\n",
        }
    )

    code, result = run()

    assert code == 0
    assert result == {
        "risky": False,
        "categories": [],
        "hits": [],
        "files": 3,
        "truncated": False,
        "reason": "",
    }


def test_ignores_removed_lines_when_classifying(surface: ModuleType) -> None:
    diff = a_diff(
        "app/core.py", "    return a + b", removed=("    subprocess.run(cmd, shell=True)",)
    )

    result = surface.classify(diff, cut=False)

    assert result["risky"] is False
    assert result["hits"] == []


def test_marks_risky_when_an_added_line_is_too_long_to_read(surface: ModuleType) -> None:
    result = surface.classify(a_diff("app/data.py", "x = '" + "a" * 2001 + "' # eval("), cut=False)

    assert result["risky"] is True
    assert result["hits"] == [
        {
            "category": "unread",
            "path": "app/data.py",
            "line": 4,
            "rule": "line over 2000 characters",
        }
    ]
    assert "over 2000 characters" in result["reason"]


def test_reads_an_added_line_starting_with_plus_signs_when_classifying(
    surface: ModuleType,
) -> None:
    # In the diff the added line "++ subprocess.run(cmd, shell=True)" reads "+++ subprocess...".
    # A removed line "-- old" reads "--- old" just before it.
    diff = a_diff("app/run.py", "++ subprocess.run(cmd, shell=True)", removed=("-- old",))

    result = surface.classify(diff, cut=False)

    assert result["risky"] is True
    assert "subprocesses" in result["categories"]
    assert {h["path"] for h in result["hits"]} == {"app/run.py"}
    assert result["files"] == 1


def test_marks_risky_when_a_real_diff_adds_a_line_starting_with_plus_signs(
    clone: Clone, run: Any
) -> None:
    clone.commit({"app/notes.txt": "intro\n++ os.system(cmd)\n"})

    code, result = run()

    assert code == 0
    assert result["risky"] is True
    assert "subprocesses" in result["categories"]
    assert result["files"] == 1


def test_marks_risky_when_diff_exceeds_read_cap(
    surface: ModuleType, *, clone: Clone, run: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone.commit({"docs/notes.md": "word\n" * 100})
    monkeypatch.setattr(surface, "READ_CAP", 64)

    code, result = run()

    assert code == 0
    assert result["risky"] is True
    assert result["truncated"] is True
    assert "over" in result["reason"]


def test_marks_risky_when_git_cannot_diff(
    surface: ModuleType, clone: Clone, capsys: pytest.CaptureFixture[str]
) -> None:
    code = surface.main(["--path", str(clone.repo), "--base", clone.base, "--head", "e" * 40])

    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["risky"] is True
    assert result["reason"].startswith("git cannot diff")


def test_exits_two_when_a_commit_is_not_a_sha(
    surface: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    code = surface.main(["--path", "/nonexistent", "--base", "HEAD", "--head", "e" * 40])

    assert code == 2
    assert "base and head must be full commit shas" in capsys.readouterr().err


def test_lists_at_most_fifty_hits_when_many_match(surface: ModuleType) -> None:
    diff = a_diff("app/run.py", *(f"subprocess.run(['x{n}'])" for n in range(80)))

    result = surface.classify(diff, cut=False)

    assert len(result["hits"]) == 50
    assert result["categories"] == ["subprocesses"]


def test_marks_risky_when_a_file_is_renamed_into_github_workflows(clone: Clone, run: Any) -> None:
    text = (clone.repo / "app/core.py").read_text(encoding="utf-8")
    clone.commit({"app/core.py": "", ".github/workflows/core.py": text})

    code, result = run()

    assert code == 0
    assert result["risky"] is True
    assert "subprocesses" in result["categories"]
    assert result["files"] == 2


def test_marks_risky_when_a_binary_secret_file_is_added(clone: Clone, run: Any) -> None:
    clone.commit({"token.pem": "\x00\x01key\x00"})

    code, result = run()

    assert code == 0
    assert result["risky"] is True
    assert "secrets" in result["categories"]
    assert result["files"] == 1
