# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The spike's agent-time budget, kept between its agent steps, and the owner's pick read.

A node that times out fails the run, so the spike keeps its timebox here instead: each command
prints the budget's state as one JSON object, and the workflow skips the agent steps left once
``over`` is true. The state is ``{"slug", "timebox_s", "spent_s", "at", "over", "left_m",
"round"}``: ``spent_s`` is the agent time spent, ``at`` the instant it was last counted to,
``left_m`` the whole minutes left and ``round`` the rounds of options so far.

``budget.py start --question <text> --timebox <n>m|<n>h --slug <slug>`` checks the inputs (a
question of 1-2000 characters without NUL; a timebox from 10m to 8h; a slug
``^[a-z0-9][a-z0-9-]{0,63}$``, or, when empty, one derived from the question) and starts the
clock.

``budget.py tick --state <state> [--loop-prev <settle>] --cap <n>s|m|h [--round]`` adds the time
since ``at``, at most ``--cap`` (the step's timeout: a run resumed days later does not count the
downtime), to ``spent_s``. ``--loop-prev``, when not empty, is the previous round's ``settle``
and is read instead of ``--state``; ``--round`` counts one more round.

``budget.py settle --state <state> --options <options> --decision <id> --note <text> --approver
<name> --max-rounds <n>`` reads the owner's pick after the gate: ``at`` restarts now (the time
the owner took is not agent time), ``picked`` is the decision when the round listed that option
(else empty: a request for more), ``go`` is a pick within the timebox, and ``done`` ends the
rounds (a pick, the timebox, or ``--max-rounds`` rounds). It adds ``{"picked", "go", "done",
"note", "approver", "option"}``: the note without control characters and cut to 2000
characters, and the picked option (``{}`` without one). Empty values are steps that did not run.

``--now <epoch seconds>`` replaces the clock, for tests. Exit codes: 0 with the JSON on stdout,
2 on a bad input (the reason on stderr).
"""

import argparse
import json
import re
import sys
import time
from collections.abc import Sequence
from typing import Any

MIN_TIMEBOX_S = 10 * 60
MAX_TIMEBOX_S = 8 * 3600
MAX_QUESTION = 2000
MAX_NOTE = 2000
MAX_APPROVER = 200
MAX_SLUG = 48
# The schema's bound on rounds of options, the loop group's max_iterations.
MAX_ROUNDS = 3
TIMEBOX = re.compile(r"[1-9][0-9]*[mh]")
CAP = re.compile(r"[1-9][0-9]*[smh]")
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
WORD = re.compile(r"[a-z0-9]+")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
SPACES = re.compile(r"[\t\n\r]")
UNIT_S = {"s": 1, "m": 60, "h": 3600}
STATE_TYPES: dict[str, tuple[type, ...]] = {
    "slug": (str,),
    "timebox_s": (int,),
    "spent_s": (int,),
    "at": (int, float),
    "over": (bool,),
    "left_m": (int,),
    "round": (int,),
}
# The options that take a value: joined to it as --name=value, so a value may start with "-".
VALUED = (
    "--question",
    "--timebox",
    "--slug",
    "--state",
    "--loop-prev",
    "--cap",
    "--options",
    "--decision",
    "--note",
    "--approver",
    "--max-rounds",
    "--now",
)


class InputError(ValueError):
    """A bad input: the message names it."""


def parse_timebox(text: str) -> int:
    """``text`` (``<n>m`` or ``<n>h``, 10m to 8h) in seconds."""
    if TIMEBOX.fullmatch(text) is None:
        msg = f"timebox {text!r} is not <n>m or <n>h"
        raise InputError(msg)
    seconds = int(text[:-1]) * UNIT_S[text[-1]]
    if not MIN_TIMEBOX_S <= seconds <= MAX_TIMEBOX_S:
        msg = f"timebox {text!r} is not between 10m and 8h"
        raise InputError(msg)
    return seconds


def parse_cap(text: str) -> int:
    """A step's timeout, ``<n>s``, ``<n>m`` or ``<n>h``, in seconds."""
    if CAP.fullmatch(text) is None:
        msg = f"cap {text!r} is not <n>s, <n>m or <n>h"
        raise InputError(msg)
    return int(text[:-1]) * UNIT_S[text[-1]]


def derive_slug(question: str) -> str:
    """The question's lowercase words joined by ``-``, cut at a ``-`` to 48 characters."""
    slug = "-".join(WORD.findall(question.lower()))
    if len(slug) > MAX_SLUG:
        cut = slug[:MAX_SLUG]
        slug = cut if slug[MAX_SLUG] == "-" or "-" not in cut else cut.rsplit("-", 1)[0]
    slug = slug.strip("-")
    if not slug:
        msg = "slug cannot be derived from the question: give --slug"
        raise InputError(msg)
    return slug


def check_question(question: str) -> None:
    if not 1 <= len(question) <= MAX_QUESTION or "\x00" in question:
        msg = f"question must be 1-{MAX_QUESTION} characters without NUL"
        raise InputError(msg)


def with_time(state: dict[str, Any], spent: int, at: float) -> dict[str, Any]:
    """``state`` with ``spent`` seconds spent, counted to ``at``."""
    timebox = state["timebox_s"]
    return state | {
        "spent_s": spent,
        "at": at,
        "over": spent >= timebox,
        "left_m": max(0, timebox - spent) // 60,
    }


def start(question: str, timebox: str, slug: str, *, now: float) -> dict[str, Any]:
    check_question(question)
    seconds = parse_timebox(timebox)
    if slug == "":
        slug = derive_slug(question)
    elif SLUG.fullmatch(slug) is None:
        msg = f"slug {slug!r} is not ^[a-z0-9][a-z0-9-]{{0,63}}$"
        raise InputError(msg)
    return with_time({"slug": slug, "timebox_s": seconds, "round": 0}, 0, now)


def read_state(text: str, name: str = "state") -> dict[str, Any]:
    """The state in ``text``: one JSON object holding every state key (others are dropped)."""
    try:
        value = json.loads(text)
    except ValueError:
        msg = f"{name} is not JSON"
        raise InputError(msg) from None
    if not isinstance(value, dict):
        msg = f"{name} is not a JSON object"
        raise InputError(msg)
    for key, types in STATE_TYPES.items():
        found = value.get(key)
        # A JSON boolean is a Python int: only "over" takes one.
        if not isinstance(found, types) or isinstance(found, bool) != (types == (bool,)):
            msg = f"{name} lacks {key}"
            raise InputError(msg)
    return {key: value[key] for key in STATE_TYPES}


def tick(
    state: dict[str, Any], now: float, cap: int, *, next_round: bool = False
) -> dict[str, Any]:
    """``state`` with the time since ``at`` (0 to ``cap`` seconds) spent."""
    elapsed = int(max(0.0, min(now - state["at"], float(cap))))
    ticked = with_time(state, state["spent_s"] + elapsed, now)
    if next_round:
        ticked["round"] = min(state["round"] + 1, MAX_ROUNDS)
    return ticked


def joined(argv: Sequence[str]) -> list[str]:
    """``argv`` with each valued option joined to its value, so a value may start with ``-``."""
    out: list[str] = []
    items = iter(argv)
    for item in items:
        value = next(items, None) if item in VALUED else None
        out.append(item if value is None else f"{item}={value}")
    return out


def parser() -> argparse.ArgumentParser:
    found = argparse.ArgumentParser(prog="budget.py")
    commands = found.add_subparsers(dest="command", required=True)
    begin = commands.add_parser("start")
    begin.add_argument("--question", required=True)
    begin.add_argument("--timebox", required=True)
    begin.add_argument("--slug", default="")
    step = commands.add_parser("tick")
    step.add_argument("--state", required=True)
    step.add_argument("--loop-prev", default="")
    step.add_argument("--cap", required=True)
    step.add_argument("--round", action="store_true")
    for command in (begin, step):
        command.add_argument("--now", type=float, default=None)
    return found


def run(given: argparse.Namespace) -> dict[str, Any]:
    now = time.time() if given.now is None else given.now
    if given.command == "start":
        return start(given.question, given.timebox, given.slug, now=now)
    base = read_state(given.loop_prev, "loop-prev") if given.loop_prev else None
    state = base if base is not None else read_state(given.state)
    return tick(state, now, parse_cap(given.cap), next_round=given.round)


def main(argv: Sequence[str]) -> int:
    try:
        given = parser().parse_args(joined(argv))
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else 2
    try:
        found = run(given)
    except InputError as error:
        print(f"budget.py: {error}", file=sys.stderr)
        return 2
    print(json.dumps(found, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
