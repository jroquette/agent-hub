"""The upgrade pack's ``outcome.py`` (AGH-484), in process: the run's status (done or blocked, the
failing check named) and the PR's summary, from what the earlier nodes printed."""

import importlib.util
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/upgrade/scripts/outcome.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.upgrade.scripts.outcome"
SOURCE = "https://github.com/encode/httpx/releases/tag/0.29.0"
FAILING = "FAILED tests/test_api.py::test_get - TypeError: verify"


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


def a_check(
    *, passed: bool, round_: int = 1, code: int = 0, tail: str = "ok\n"
) -> dict[str, object]:
    return {"passed": passed, "exit_code": code, "round": round_, "tail": tail}


def a_strength(**changes: object) -> dict[str, object]:
    found: dict[str, object] = {
        "touched": 0,
        "files": [],
        "lockfiles_edited": [],
        "ran": False,
        "tool": "",
        "reason": "no commit after the bump",
        "mutants": 0,
        "killed": 0,
        "inconclusive": 0,
        "survived": [],
        "more_survived": 0,
    }
    return found | changes


def args(**given: object) -> list[str]:
    """The node's argv; a value of None is a skipped producer (blank)."""
    values: dict[str, object] = {
        "fast-gate": "make check-fast",
        "full-gate": "make check",
        "package": "httpx",
        "bump": {
            "manager": "uv",
            "dir": ".",
            "from": "0.28.1",
            "to": "0.29.0",
            "major": True,
            "files": ["uv.lock"],
            "commit": "0" * 40,
        },
        "notes-found": True,
        "notes-reason": "",
        "sources": [SOURCE],
        "changelog": {"breaking": [], "summary": "Nothing breaks."},
        "check": a_check(passed=True),
        "adapt": None,
        "strength": a_strength(),
        "full": a_check(passed=True),
    } | {key.replace("_", "-"): value for key, value in given.items()}
    argv: list[str] = []
    for key, value in values.items():
        # As the engine renders an object into an argument: compact, sorted, not ASCII-escaped.
        dumped = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        text = "" if value is None else value if isinstance(value, str) else dumped
        argv += [f"--{key}", text]
    return argv


def outcome(capsys: pytest.CaptureFixture[str], argv: list[str]) -> dict[str, str]:
    assert load().main(argv) == 0
    found: dict[str, str] = json.loads(capsys.readouterr().out)
    return found


def test_is_done_with_summary_when_check_green_without_adapt(
    capsys: pytest.CaptureFixture[str],
) -> None:
    found = outcome(capsys, args())

    assert (found["status"], found["question"]) == ("done", "")
    summary = found["summary"]
    for text in (
        "httpx 0.28.1 → 0.29.0 (major)",
        SOURCE,
        "no breaking change found",
        "No adapt round: the fast check passed on the bump.",
        "test-strength not run: no commit after the bump",
        "check_fast (`make check-fast`): passed",
        "check (`make check`): passed",
    ):
        assert text in summary


def test_names_the_failing_check_when_adapt_rounds_exhausted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    red = a_check(passed=False, round_=3, code=2, tail=f"collected 9 items\n{FAILING}\n\n")
    fix = {"status": "done", "summary": "Passes verify through.", "question": ""}

    found = outcome(
        capsys,
        args(
            check=a_check(passed=False, code=2),
            adapt={"fix": fix, "recheck": red},
            strength=None,
            full=None,
        ),
    )

    assert found["status"] == "blocked"
    assert found["question"] == (
        f"check_fast (make check-fast) still fails after 3 adapt rounds, exit 2: {FAILING}"
    )
    assert "check (`make check`): not run" in found["summary"]


def test_passes_the_agent_question_when_fix_is_blocked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fix = {"status": "blocked", "summary": "", "question": "Pin the old API, or drop the proxy?"}

    found = outcome(
        capsys,
        args(
            check=a_check(passed=False, code=2),
            adapt={"fix": fix, "recheck": None},
            strength=None,
            full=None,
        ),
    )

    assert (found["status"], found["question"]) == (
        "blocked",
        "Pin the old API, or drop the proxy?",
    )


def test_blocks_when_check_full_is_red(capsys: pytest.CaptureFixture[str]) -> None:
    found = outcome(capsys, args(full=a_check(passed=False, code=1, tail="e2e failed\n")))

    assert found["status"] == "blocked"
    assert found["question"] == (
        "check (make check) fails after check_fast passed, exit 1: e2e failed"
    )
    assert "check (`make check`): failed, exit 1" in found["summary"]


def test_blocks_when_adapt_edited_a_lockfile(capsys: pytest.CaptureFixture[str]) -> None:
    edited = a_strength(touched=2, files=["src/a.py", "uv.lock"], lockfiles_edited=["uv.lock"])

    found = outcome(capsys, args(strength=edited))

    assert found["status"] == "blocked"
    assert found["question"] == (
        "the adapt commits edited uv.lock: only the tooling may change manifests and lockfiles"
    )


def test_lists_breaking_changes_with_path_line_and_survivors_when_major_bump_adapted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    breaking = {
        "breaking": [
            {
                "change": "verify is gone",
                "path": "src/api.py",
                "line": 12,
                "action": "Pass verify through the transport.",
            },
            {
                "change": "proxies renamed",
                "path": "src/client.py",
                "line": None,
                "action": "Use proxy.",
            },
        ],
        "summary": "Two hits.",
    }
    survivor = {
        "path": "web/src/x.ts",
        "line": 3,
        "mutator": "ArithmeticOperator",
        "replacement": "a - b",
    }
    strength = a_strength(
        touched=3,
        ran=True,
        tool="stryker",
        reason="",
        mutants=4,
        killed=2,
        inconclusive=1,
        survived=[survivor],
        more_survived=2,
    )
    fix = {"status": "done", "summary": "Passes verify through the transport.", "question": ""}

    found = outcome(
        capsys,
        args(
            check=a_check(passed=False, code=2),
            changelog=breaking,
            strength=strength,
            adapt={"fix": fix, "recheck": a_check(passed=True, round_=2)},
        ),
    )

    assert found["status"] == "done"
    summary = found["summary"]
    for text in (
        "- verify is gone (`src/api.py:12`): Pass verify through the transport.",
        "- proxies renamed (`src/client.py`): Use proxy.",
        "Adapt, 2 rounds: Passes verify through the transport.",
        "stryker: 4 mutants, 2 killed, 1 inconclusive, 3 survived",
        "- `web/src/x.ts:3` ArithmeticOperator: a - b",
        "2 more survived",
        "check_fast (`make check-fast`): failed on the bump, exit 2; passed after adapt",
    ):
        assert text in summary


def test_says_no_changelog_found_when_notes_missing(capsys: pytest.CaptureFixture[str]) -> None:
    reason = "GitHub refused the releases read (HTTP 403, likely the unauthenticated rate limit)"

    found = outcome(capsys, args(notes_found=False, notes_reason=reason, sources=[]))

    assert f"no changelog found: {reason}" in found["summary"]


def test_caps_summary_when_inputs_are_at_their_bound(capsys: pytest.CaptureFixture[str]) -> None:
    wide = "\U0001f600```"
    item = {"change": wide * 50, "path": wide * 64, "line": 10_000_000, "action": wide * 50}
    survivor = {"path": wide * 200, "line": 1, "mutator": wide * 25, "replacement": wide * 50}
    fix = {"status": "done", "summary": wide * 500, "question": ""}

    found = outcome(
        capsys,
        args(
            changelog={"breaking": [item] * 30, "summary": wide * 500},
            sources=[f"https://github.com/a/b/{'x' * 470}"] * 10,
            check=a_check(passed=False, code=2, tail=wide * 1000),
            adapt={"fix": fix, "recheck": a_check(passed=True, tail=wide * 1000)},
            strength=a_strength(ran=True, tool="stryker", survived=[survivor] * 50),
        ),
    )

    assert len(found["summary"]) <= 8000
    assert "```" not in found["summary"]
    assert found["summary"].endswith("[summary cut at 8000 characters]")


@pytest.mark.parametrize(
    "argv",
    [
        args(bump="{not json"),
        args(check="[1, 2]"),
        args(package=""),
        [*args(), "--extra", "x"],
    ],
)
def test_exits_two_when_an_argument_is_unreadable(
    capsys: pytest.CaptureFixture[str], *, argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as raised:
        load().main(argv)

    assert raised.value.code == 2
    assert capsys.readouterr().out == ""
