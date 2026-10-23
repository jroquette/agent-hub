# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Decide the upgrade run's outcome and write its PR summary; print them as one JSON object.

``outcome.py --fast-gate <cmd> --full-gate <cmd> --package <name> --bump <json>
--notes-found <bool> --notes-reason <text> --sources <json> --changelog <json> --check <json>
--adapt <json> --strength <json> --full <json>``: each JSON value is what that node printed, and a
blank one is a node that did not run. The output is ``{"status", "question", "summary"}``.
``status`` is ``blocked`` when the adapting session stopped (its question), when the fast check
is still red after the adapt rounds, when the adapt commits edited a manifest or lockfile, or
when the full check is red or did not run; the question then names the failing gate, its exit
code and the last non-empty line of its output (at most ``MAX_LINE_CHARS``). Else ``done``.
``summary`` is the PR body's summary (at most ``MAX_SUMMARY_CHARS``): the versions, the notes'
sources or why none was found, each breaking change with its ``path:line`` and action, adapt's
work, the test strength result and both gates' results. Untrusted text in it has its control
characters dropped and every run of three or more backticks made two. An unreadable argument
exits 2.
"""

import argparse
import json
import re
import sys

MAX_SUMMARY_CHARS = 8000
MAX_QUESTION_CHARS = 1000
MAX_LINE_CHARS = 300
MAX_ARGUMENT_CHARS = 128 * 1024
CUT = f"[summary cut at {MAX_SUMMARY_CHARS} characters]"
FENCE_RUN = re.compile("`{3,}")
CONTROL = re.compile("[\x00-\x09\x0b-\x1f\x7f-\x9f]")
OBJECTS = ("bump", "changelog", "check", "adapt", "strength", "full")

Node = dict[str, object]


def clean(value: object) -> str:
    """Untrusted text for the summary: no control characters, no run of three backticks."""
    text = CONTROL.sub("", str(value).replace("\r\n", "\n").replace("\r", "\n"))
    return FENCE_RUN.sub("``", text)


def one_line(value: object) -> str:
    return " ".join(clean(value).split())


def last_line(tail: object) -> str:
    lines = [line.strip() for line in clean(tail if tail is not None else "").splitlines()]
    found = next((line for line in reversed(lines) if line), "")
    return found[:MAX_LINE_CHARS]


def _node(value: object) -> Node | None:
    return value if isinstance(value, dict) else None


def _failure(check: Node) -> str:
    return f"exit {check.get('exit_code')}: {last_line(check.get('tail'))}"


def question(args: argparse.Namespace) -> str:
    """Why the run is blocked, or the empty text."""
    adapt = args.adapt or {}
    fix, recheck = _node(adapt.get("fix")), _node(adapt.get("recheck"))
    edited = (args.strength or {}).get("lockfiles_edited") or []
    if fix is not None and fix.get("status") == "blocked":
        return one_line(fix.get("question") or "the adapting session stopped without a question")
    if recheck is not None and recheck.get("passed") is not True:
        rounds = recheck.get("round")
        failure = _failure(recheck)
        return f"check_fast ({args.fast_gate}) still fails after {rounds} adapt rounds, {failure}"
    if args.check is not None and args.check.get("passed") is not True and recheck is None:
        return f"check_fast ({args.fast_gate}) fails, {_failure(args.check)}"
    if isinstance(edited, list) and edited:
        listed = ", ".join(one_line(path) for path in edited[:10])
        rule = "only the tooling may change manifests and lockfiles"
        return f"the adapt commits edited {listed}: {rule}"
    if args.full is None:
        return f"check ({args.full_gate}) did not run"
    if args.full.get("passed") is not True:
        failure = _failure(args.full)
        return f"check ({args.full_gate}) fails after check_fast passed, {failure}"
    return ""


def notes_part(args: argparse.Namespace) -> list[str]:
    if args.notes_found == "true":
        sources = ", ".join(one_line(source) for source in args.sources)
        return [f"Release notes: {sources}"]
    return [f"Release notes: no changelog found: {one_line(args.notes_reason)}"]


def breaking_part(changelog: Node | None) -> list[str]:
    items = (changelog or {}).get("breaking")
    if not isinstance(items, list) or not items:
        return ["Breaking changes: no breaking change found in the notes."]
    lines = ["Breaking changes that hit the repo:"]
    for item in items:
        if not isinstance(item, dict):
            continue
        where = one_line(item.get("path"))
        where += f":{item['line']}" if isinstance(item.get("line"), int) else ""
        lines.append(
            f"- {one_line(item.get('change'))} (`{where}`): {one_line(item.get('action'))}"
        )
    return lines


def adapt_part(adapt: Node | None) -> list[str]:
    if adapt is None:
        return ["No adapt round: the fast check passed on the bump."]
    fix, recheck = _node(adapt.get("fix")) or {}, _node(adapt.get("recheck"))
    if recheck is None:
        return [f"Adapt stopped: {one_line(fix.get('question'))}"]
    rounds = recheck.get("round")
    noun = "round" if rounds == 1 else "rounds"
    return [f"Adapt, {rounds} {noun}: {one_line(fix.get('summary'))}"]


def strength_part(strength: Node | None) -> list[str]:
    if strength is None:
        return ["test-strength not run: the fast check is not green"]
    if strength.get("ran") is not True:
        return [f"test-strength not run: {one_line(strength.get('reason'))}"]
    survived = strength.get("survived")
    listed = survived if isinstance(survived, list) else []
    more = strength.get("more_survived")
    total = len(listed) + (more if isinstance(more, int) else 0)
    lines = [
        f"Test strength, {one_line(strength.get('tool'))}: {strength.get('mutants')} mutants,"
        f" {strength.get('killed')} killed, {strength.get('inconclusive')} inconclusive,"
        f" {total} survived"
    ]
    for item in listed:
        if isinstance(item, dict):
            where = f"{one_line(item.get('path'))}:{item.get('line')}"
            lines.append(
                f"- `{where}` {one_line(item.get('mutator'))}: {one_line(item.get('replacement'))}"
            )
    if total > len(listed):
        lines.append(f"{total - len(listed)} more survived.")
    if total:
        lines.append("The survivors are not classified: run /test-strength on the PR.")
    return lines


def _result(check: Node) -> str:
    return "passed" if check.get("passed") is True else f"failed, exit {check.get('exit_code')}"


def gates_part(args: argparse.Namespace) -> list[str]:
    fast = f"check_fast (`{one_line(args.fast_gate)}`): "
    recheck = _node((args.adapt or {}).get("recheck"))
    if args.check is None:
        fast += "not run"
    elif args.check.get("passed") is True or recheck is None:
        fast += _result(args.check)
    else:
        later = (
            "passed after adapt" if recheck.get("passed") is True else "still failing after adapt"
        )
        fast += f"failed on the bump, exit {args.check.get('exit_code')}; {later}"
        fast += "" if recheck.get("passed") is True else f", exit {recheck.get('exit_code')}"
    full = f"check (`{one_line(args.full_gate)}`): "
    full += "not run" if args.full is None else _result(args.full)
    return [fast, full]


def summary(args: argparse.Namespace) -> str:
    bump = args.bump or {}
    size = "major" if bump.get("major") is True else "minor or patch"
    versions = f"{one_line(bump.get('from'))} → {one_line(bump.get('to'))}"
    head = f"Bumps {one_line(args.package)} {versions} ({size})."
    parts = [
        [head],
        notes_part(args),
        breaking_part(args.changelog),
        adapt_part(args.adapt),
        strength_part(args.strength),
        gates_part(args),
    ]
    text = "\n\n".join("\n".join(part) for part in parts)
    if len(text) > MAX_SUMMARY_CHARS:
        text = text[: MAX_SUMMARY_CHARS - len(CUT) - 1] + "\n" + CUT
    return text


def _json(parser: argparse.ArgumentParser, name: str, value: str, *, kind: type) -> object:
    """``value`` read as JSON of ``kind``; blank is None (a node that did not run)."""
    if not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except ValueError:
        parser.error(f"--{name} is not JSON")
    if not isinstance(parsed, kind):
        parser.error(f"--{name} is not a JSON {kind.__name__}")
    return parsed


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="outcome.py")
    for name in ("fast-gate", "full-gate", "package", "notes-found", "notes-reason", "sources"):
        parser.add_argument(f"--{name}", required=True)
    for name in OBJECTS:
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args(argv)
    if any(len(value) > MAX_ARGUMENT_CHARS for value in vars(args).values()):
        parser.error(f"an argument is longer than {MAX_ARGUMENT_CHARS} characters")
    if not (args.fast_gate.strip() and args.full_gate.strip() and args.package.strip()):
        parser.error("--fast-gate, --full-gate and --package must not be blank")
    for name in OBJECTS:
        setattr(args, name, _json(parser, name, getattr(args, name), kind=dict))
    sources = _json(parser, "sources", args.sources, kind=list)
    args.sources = (
        [item for item in sources if isinstance(item, str)] if isinstance(sources, list) else []
    )
    return args


def main(argv: list[str]) -> int:
    args = parse(argv)
    blocked = question(args)
    result = {
        "status": "blocked" if blocked else "done",
        "question": blocked[:MAX_QUESTION_CHARS],
        "summary": summary(args),
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
