"""``GhEventSource``: a repo's GitHub events read through ``gh api`` (ADR 0048).

One REST call per poll, through ``gh`` (the account it is signed in with; no other host, no
token read here): ``merge`` lists the commits of the default branch, ``pr_opened`` the open pull
requests newest first, ``ci_red`` the failed Actions runs of the branch, ``per_page=20`` each.
The child gets an argv list, an empty stdin, no prompt, the system temp folder as its cwd and the
caller's environment without git's location variables or ``LINEAR_API_KEY``. Its stdout is read
up to ``OUTPUT_LIMIT``; an answer that fills it is refused, not parsed. Each item's id is
shape-checked (a 40-hex sha, an integer from 1 to 2^53). Every failure is an ``EventPollError``
naming why, never the answer's text.
"""

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from agent_hub.core.json_form import JsonValue
from agent_hub.core.schedules.scheduled_starts import (
    EVENT_PAGE,
    EventPollError,
    EventQuery,
    EventRef,
)
from agent_hub.hub_git.git_runner import OUTPUT_LIMIT, Launch, child_env, run_process

POLL_SECONDS: Final = 30.0
# Children of hub web never get the tracker's key (ADR 0030).
DROPPED_VARIABLES: Final = ("LINEAR_API_KEY",)
_SHA_CHARS: Final = 40
_HEX: Final = frozenset("0123456789abcdef")
_MAX_ID: Final = 2**53
_UNEXPECTED: Final = "unexpected answer"


class GhEventSource:
    """``EventSource`` over ``gh api`` (see the module docstring)."""

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        gh: str = "gh",
        launch: Launch = run_process,
        timeout: float = POLL_SECONDS,
    ) -> None:
        given = dict(os.environ if environ is None else environ)
        env = child_env(given)
        self._env = {name: value for name, value in env.items() if name not in DROPPED_VARIABLES}
        self._gh = gh
        self._launch = launch
        self._timeout = timeout

    def poll(self, query: EventQuery) -> tuple[EventRef, ...]:
        """The newest events of ``query`` first, at most ``EVENT_PAGE``; ``EventPollError``."""
        answer = self._answer(query)
        if query.kind == "merge":
            return tuple(_merge(item) for item in _items(answer))
        if query.kind == "pr_opened":
            return tuple(_pull(item) for item in _items(answer))
        runs = answer.get("workflow_runs") if isinstance(answer, dict) else None
        return tuple(_red_run(item) for item in _items(runs))

    def _answer(self, query: EventQuery) -> JsonValue:
        program = shutil.which(self._gh, path=self._env.get("PATH") or "")
        if program is None:
            raise EventPollError("gh not found")
        try:
            result = self._launch(
                [os.path.abspath(program), *_api_args(query)],
                cwd=Path(tempfile.gettempdir()),
                env=self._env,
                timeout=self._timeout,
                keep_stdout=True,
            )
        except subprocess.TimeoutExpired, TimeoutError:
            raise EventPollError("gh timed out") from None
        except OSError:
            raise EventPollError("gh could not start") from None
        if result.returncode != 0:
            raise EventPollError(f"gh exited {result.returncode}")
        if len(result.stdout) >= OUTPUT_LIMIT:
            raise EventPollError("answer too large")
        try:
            answer: JsonValue = json.loads(result.stdout)
        except ValueError:
            raise EventPollError("answer not JSON") from None
        return answer


def _api_args(query: EventQuery) -> list[str]:
    base = ["api", "-X", "GET", f"repos/{query.github}/"]
    page = ["-f", f"per_page={EVENT_PAGE}"]
    if query.kind == "merge":
        base[-1] += "commits"
        fields = ["-f", f"sha={query.branch}"]
    elif query.kind == "pr_opened":
        base[-1] += "pulls"
        fields = ["-f", "state=open", "-f", "sort=created", "-f", "direction=desc"]
    else:
        base[-1] += "actions/runs"
        fields = ["-f", f"branch={query.branch}", "-f", "status=failure"]
    return [*base, *fields, *page]


def _items(answer: JsonValue) -> list[Mapping[str, JsonValue]]:
    if not isinstance(answer, list) or not all(isinstance(item, dict) for item in answer):
        raise EventPollError(_UNEXPECTED)
    return [item for item in answer[:EVENT_PAGE] if isinstance(item, dict)]


def _sha(value: JsonValue) -> str:
    if isinstance(value, str) and len(value) == _SHA_CHARS and set(value) <= _HEX:
        return value
    raise EventPollError(_UNEXPECTED)


def _number(value: JsonValue) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= _MAX_ID:
        return value
    raise EventPollError(_UNEXPECTED)


def _merge(item: Mapping[str, JsonValue]) -> EventRef:
    sha = _sha(item.get("sha"))
    return EventRef(sha, {"sha": sha})


def _pull(item: Mapping[str, JsonValue]) -> EventRef:
    number = _number(item.get("number"))
    head = item.get("head")
    sha = _sha(head.get("sha") if isinstance(head, dict) else None)
    return EventRef(str(number), {"pr": number, "sha": sha})


def _red_run(item: Mapping[str, JsonValue]) -> EventRef:
    run = _number(item.get("id"))
    sha = _sha(item.get("head_sha"))
    return EventRef(str(run), {"ci_run": run, "sha": sha})
