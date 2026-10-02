"""One bench run's children and its record: settings, argv, environments, outcomes; pure.

The texts, argv and field orders are the hub script's (``scripts/bench.py``), so its goldens
hold. Three differences: the plugin is ``hub-workflow@<project.name>`` (Q-5); a case's ``env``
goes to the grader's test command only, never to git or ``claude`` (E17); and every git argv
reads pathspecs literally (``--literal-pathspecs``, E16), so a hidden test path is one file,
never a glob or pathspec magic. The CLI adds its own base environment (no tokens, E9) and runs
the children.

``--setting-sources user`` loads the user's own settings, so their hooks and plugins run in both
arms alike (parity with the script): only the plugin under test differs, and only the
account-synced ``engineering@synced`` is turned off.
"""

import json
import math
import posixpath
from collections.abc import Mapping
from typing import Final

from agent_hub.core.bench.bench_cases import BenchCase
from agent_hub.core.bench.bench_plan import Job
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes

MODEL: Final = "claude-sonnet-5"
MAX_TURNS: Final = 60
EFFORTS: Final = ("low", "medium", "high")
CLAUDE_PROGRAM: Final = "claude"
GIT: Final = ("git", "--literal-pathspecs")
# Today's agent config, laid over the old code from origin/main so both arms read the same.
AGENT_CONFIG: Final = ("AGENTS.md", "CLAUDE.md", ".claude/rules", ".claude/settings.json")
OTEL_VARIABLE: Final = "OTEL_RESOURCE_ATTRIBUTES"
AGENT_ERROR_CHARS: Final = 300
TAIL_CHARS: Final = 200
# Isolation: only the plugin under test varies; account-synced plugins stay off in both arms.
_SYNCED_PLUGIN: Final = "engineering@synced"
# The script's sandbox writes, macOS temp folders included (parity).
_TEMP_WRITES: Final = ("/private/tmp", "/private/var/folders")


def plugin_id(project: str) -> str:
    """The plugin the ``with`` arm enables: the hub's generated marketplace is its project."""
    return f"hub-workflow@{project}"


def worktree_name(*, label: str, case_id: str, arm: str, run: int) -> str:
    """A run's worktree folder under ``<ws>/_bench/wt``."""
    return f"{label}-{case_id}-{arm}-r{run}"


def validate_worktree_name(*, case_id: str, label: str) -> str:
    """``--validate``'s worktree for a case at ``label`` (``parent`` or ``merge``)."""
    return f"validate-{case_id}-{label}"


def settings_name(worktree: str) -> str:
    """The settings file of the run in worktree folder ``worktree``, under the results."""
    return f".settings-{worktree}.json"


def sandbox_settings(*, worktree: str, arm: str, plugin: str, effort: str) -> dict[str, JsonValue]:
    """The session's ``--settings``: sandboxed to its worktree, the plugin on in ``with`` only."""
    return {
        "sandbox": {
            "enabled": True,
            "allowUnsandboxedCommands": False,
            "autoAllowBashIfSandboxed": True,
            "network": {"allowedDomains": ["127.0.0.1", "localhost"], "allowLocalBinding": True},
            "filesystem": {
                "allowWrite": [worktree, *_TEMP_WRITES],
                "denyWrite": [posixpath.join(worktree, ".git")],
            },
        },
        "enabledPlugins": {plugin: arm == "with", _SYNCED_PLUGIN: False},
        "effortLevel": effort,
    }


def settings_text(settings: Mapping[str, JsonValue]) -> str:
    """The settings file's text, as the script wrote it (no final newline)."""
    return json.dumps(settings)


def record_line(record: Mapping[str, JsonValue]) -> str:
    """A record as one JSON line, as the script printed and appended it."""
    return json.dumps(record)


def agent_argv(*, prompt: str, settings_path: str, per_run: float, trace: bool) -> list[str]:
    """``claude -p`` with the case's prompt, the caps and, with ``trace``, a kept stream."""
    output = (
        ["--output-format", "stream-json", "--verbose"] if trace else ["--output-format", "json"]
    )
    return [
        CLAUDE_PROGRAM,
        "-p",
        prompt,
        "--model",
        MODEL,
        *output,
        "--permission-mode",
        "acceptEdits",
        "--setting-sources",
        "user",
        "--settings",
        settings_path,
        "--max-budget-usd",
        str(per_run),
        "--max-turns",
        str(MAX_TURNS),
        # No MCP servers: the cases need none.
        "--strict-mcp-config",
        *([] if trace else ["--no-session-persistence"]),
    ]


def session_env(base: Mapping[str, str], *, case: BenchCase, arm: str) -> dict[str, str]:
    """``base`` and the session's telemetry tags; never the case's ``env``."""
    tags = f"repo={case.repo},bench_case={case.id},bench_arm={arm}"
    return {**base, OTEL_VARIABLE: tags}


def grader_env(base: Mapping[str, str], *, case: BenchCase) -> dict[str, str]:
    """``base`` with the case's ``env`` over it: the test command's environment only."""
    return {**base, **case.env}


def git_argv(worktree: str, *arguments: str) -> list[str]:
    """``git`` in ``worktree``, every pathspec read as a literal path."""
    return [*GIT, "-C", worktree, *arguments]


def apply_tests_argv(*, worktree: str, case: BenchCase) -> list[str]:
    """The merge's hidden tests checked out over the worktree's files."""
    return git_argv(worktree, "checkout", case.merge, "--", *case.hidden_tests)


def grader_argvs(case: BenchCase) -> tuple[list[str], list[str]]:
    """The test command on the hidden tests, then on their folders (sorted, once each)."""
    folders = sorted({posixpath.dirname(path) or "." for path in case.hidden_tests})
    return [*case.test_cmd, *case.hidden_tests], [*case.test_cmd, *folders]


def result_of(stdout: str, *, trace: bool) -> dict[str, JsonValue]:
    """The session's result object: the JSON reply, or a trace's last ``result`` event; else {}.

    A trace line that is not a JSON object (a line cut by reading the trace's tail) is skipped.
    Lines end at ``"\n"`` only: ``splitlines`` would also cut at U+2028 or U+0085, which JSON
    keeps raw inside a string, and lose that event's cost.
    """
    if not trace:
        return _object(stdout)
    for line in reversed(stdout.split("\n")):
        if line.startswith("{"):
            event = _object(line)
            if event.get("type") == "result":
                return event
    return {}


def agent_outcome(
    *, rc: int, result: Mapping[str, JsonValue], secs: int, stderr: str
) -> dict[str, JsonValue]:
    """The session's part of the record; ``agent_error`` keeps the stderr's tail on failure."""
    turns, subtype = result.get("num_turns"), result.get("subtype")
    return {
        "agent_rc": rc,
        "cost": _cost(result.get("total_cost_usd")),
        "turns": turns if isinstance(turns, int) and not isinstance(turns, bool) else None,
        "secs": secs,
        "subtype": subtype if isinstance(subtype, str) else None,
        "agent_error": stderr[-AGENT_ERROR_CHARS:] if rc else "",
    }


def timeout_outcome(*, per_run: float, secs: int) -> dict[str, JsonValue]:
    """A session stopped at its timeout: counted at its whole per-run budget."""
    return {"agent_rc": "timeout", "cost": per_run, "secs": secs}


def grade_outcome(
    *, hidden_rc: int, hidden_stdout: str, related_rc: int, related_stdout: str
) -> dict[str, JsonValue]:
    """The grade: a pass needs both test runs to pass; each keeps its output's last line."""
    return {
        "pass": hidden_rc == 0 and related_rc == 0,
        "hidden_rc": hidden_rc,
        "related_rc": related_rc,
        "hidden_tail": _tail(hidden_stdout),
        "related_tail": _tail(related_stdout),
    }


def apply_failed_outcome(stderr: str) -> dict[str, JsonValue]:
    """The grade when the hidden tests could not be checked out."""
    return {"pass": False, "error": "apply-tests: " + stderr[-AGENT_ERROR_CHARS:]}


def run_record(
    *,
    label: str,
    job: Job,
    agent: Mapping[str, JsonValue],
    grade: Mapping[str, JsonValue],
    ts: str,
) -> dict[str, JsonValue]:
    """One run's record, in the script's field order; ``ts`` comes from the caller's clock."""
    return {
        "label": label,
        "case": job.case.id,
        "arm": job.arm,
        "run": job.run,
        "model": MODEL,
        **agent,
        **grade,
        "ts": ts,
    }


def _object(text: str) -> dict[str, JsonValue]:
    try:
        value = load_json_bytes(text.encode())
    except InvalidJsonError, UnicodeEncodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _cost(value: JsonValue | None) -> int | float:
    # The script's ``or 0.0``, for numbers only: a bool is an int to Python, never a cost, and
    # NaN or an infinity would break the sums.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    if isinstance(value, float) and not math.isfinite(value):
        return 0.0
    return value or 0.0


def _tail(text: str) -> str:
    # Lines end at "\n" only: ``splitlines`` also cuts at U+2028, U+0085 and the like.
    stripped = text.strip()
    return stripped.split("\n")[-1].removesuffix("\r")[:TAIL_CHARS] if stripped else ""
