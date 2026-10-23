# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Write the spike's research.md and its ADR draft under brain/features/<slug>/ in the hub.

``draft.py --slug <slug> --question <text> --state <settle> --recall <recall> --options
<options> --premortem <premortem>``, with the research on stdin: each value is the JSON a step
printed, or empty when that step did not run. The current folder is the hub. It writes
``brain/features/<slug>/research.md`` and, when there were options, ``adr-draft-<slug>.md``
beside it: an ADR with no number and status draft, which /adr records. It never overwrites a
file: an existing name gets ``-<AGENT_HUB_RUN_ID>`` (then ``-2``, ``-3``...) before ``.md``.

Both files are marked incomplete (``complete: false`` and a first line ``> Incomplete: ...``)
when the timebox was reached, a step did not run, no option was picked, or the premortem did not
give exactly three causes. It prints ``{"result": "complete" | "incomplete", "research", "adr",
"reasons", "spent_m"}``: the paths written (``adr`` empty when none) and the agent time spent.

``--now <epoch seconds>`` replaces the clock, for tests. Exit codes: 0 with the JSON on stdout,
2 on a bad input (an argument or stdin that is not a JSON object, a slug outside
brain/features), 1 when a file cannot be written (the reason on stderr).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

FEATURES = Path("brain/features")
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
RUN_ID = re.compile(r"[^A-Za-z0-9._-]")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
# A paragraph that starts with one of these would turn into a heading, a quote, a list or a
# code fence: agent text is data, so it is escaped.
BLOCK_START = re.compile(r"^([#>*+`=|~-]|\d+[.)])")
CAUSES = 3
# The premortem's timeout: its time counts up to this much.
PREMORTEM_CAP_S = 20 * 60
MAX_TITLE = 100
MAX_REASONS = 10
MAX_SOURCES = 30
MAX_WRITES = 100
VALUED = ("--slug", "--question", "--state", "--recall", "--options", "--premortem", "--now")
STEPS = ("state", "recall", "options", "premortem")


class InputError(ValueError):
    """A bad input: the message names it."""


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def timebox_text(seconds: int) -> str:
    """``7200`` as ``2h``, ``5400`` as ``90m``."""
    return f"{seconds // 3600}h" if seconds % 3600 == 0 else f"{seconds // 60}m"


def reasons(
    *,
    state: dict[str, Any],
    recall: dict[str, Any] | None,
    research: dict[str, Any] | None,
    options: dict[str, Any] | None,
    premortem: dict[str, Any] | None,
) -> list[str]:
    """Why the spike is incomplete, in step order; empty when it is complete."""
    del recall  # Recall always runs: a failure fails the run before draft.
    found: list[str] = []
    if state.get("over"):
        after = "recall" if research is None else "research" if options is None else "options"
        found.append(f"timebox {timebox_text(state['timebox_s'])} reached after {after}")
    else:
        if research is None:
            found.append("research did not run")
        if options is None:
            found.append("options did not run")
        if not state.get("picked"):
            found.append(f"no option picked after {plural(state.get('round', 0), 'round')}")
        if premortem is None:
            found.append("premortem did not run")
    if premortem is not None and len(premortem.get("causes", [])) != CAUSES:
        count = len(premortem.get("causes", []))
        found.append(f"the premortem gave {plural(count, 'cause')}, not {CAUSES}")
    return found[:MAX_REASONS]


def line(text: Any) -> str:
    """``text`` on one line, without control characters."""
    return CONTROL.sub(" ", str(text)).strip()


def para(text: Any) -> str:
    """Agent text as one Markdown paragraph that cannot open a block of its own."""
    flat = line(text)
    return f"\\{flat}" if BLOCK_START.match(flat) else flat


def fenced(text: str) -> str:
    """Owner text in a code fence longer than any backtick run inside it."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def items(values: Sequence[Any], empty: str) -> str:
    return "\n".join(f"- {line(value)}" for value in values) if values else empty


def front_matter(fields: list[tuple[str, str]]) -> str:
    return "---\n" + "".join(f"{key}: {value}\n" for key, value in fields) + "---\n"


def flow(values: Sequence[str]) -> str:
    """A YAML flow list of JSON strings (valid YAML)."""
    return "[" + ", ".join(json.dumps(line(value), ensure_ascii=False) for value in values) + "]"


def incomplete(found: list[str]) -> str:
    return f"> Incomplete: {'; '.join(found)}.\n\n" if found else ""


def title_of(question: str) -> str:
    first = line(question.strip().splitlines()[0] if question.strip() else question)
    return first if len(first) <= MAX_TITLE else first[: MAX_TITLE - 3].rstrip() + "..."


def listed(options: dict[str, Any] | None) -> list[dict[str, Any]]:
    found = options.get("options", []) if options else []
    return [item for item in found if isinstance(item, dict)]


def picked_option(state: dict[str, Any]) -> dict[str, Any]:
    option = state.get("option")
    return option if state.get("picked") and isinstance(option, dict) else {}


def render_options(options: dict[str, Any] | None) -> str:
    if options is None:
        return "Not run."
    parts = []
    for option in listed(options):
        pros = "\n".join(f"- Pro: {line(pro)}" for pro in option.get("pros", []))
        cons = "\n".join(f"- Con: {line(con)}" for con in option.get("cons", []))
        lists = "\n".join(part for part in (pros, cons) if part)
        head = f"### {line(option.get('id', ''))}. {line(option.get('title', ''))}"
        parts.append(
            "\n\n".join(part for part in (head, para(option.get("summary", "")), lists) if part)
        )
    recommended = (
        f"Recommended: {line(options.get('recommendation', ''))}. {line(options.get('reason', ''))}"
    )
    return "\n\n".join([*parts, recommended.strip()])


def render_pick(state: dict[str, Any]) -> str:
    option = picked_option(state)
    if not option:
        return f"No option picked ({plural(state.get('round', 0), 'round')} of options)."
    who = line(state.get("approver", "")) or "the owner"
    text = f"Option {line(state['picked'])}, picked by {who}: {line(option.get('title', ''))}."
    note = line(state.get("note", ""))
    return f"{text}\n\nOwner's note: {note}" if note else text


def render_research(
    question: str,
    given: dict[str, Any],
    found: list[str],
    *,
    run: str,
    today: str,
    spent_m: int,
) -> str:
    """research.md: what the brain says, what the code does, the options and the pick."""
    state, recall, research = given["state"], given["recall"], given["research"]
    sources = [source.get("ref", "") for source in (recall or {}).get("sources", [])]
    sources += [finding.get("where", "") for finding in (research or {}).get("findings", [])]
    unique = list(dict.fromkeys(source for source in sources if source))[:MAX_SOURCES]
    head = front_matter(
        [
            ("type", "research"),
            ("repos", flow((research or {}).get("repos", []))),
            ("status", "draft"),
            ("complete", "false" if found else "true"),
            ("last_verified", today),
            ("sources", flow(unique)),
            ("provenance", "agent-from-code"),
            ("run", run),
        ]
    )
    brain = "Not run."
    if recall is not None:
        cited = "\n".join(
            f"- `{line(source.get('ref', ''))}`: {line(source.get('says', ''))}"
            for source in recall.get("sources", [])
        )
        brain = "\n\n".join(part for part in (para(recall.get("summary", "")), cited) if part)
    findings = "Not run."
    if research is not None:
        findings = "\n".join(
            f"- **{line(item.get('area', ''))}**: {line(item.get('fact', ''))}"
            f" (`{line(item.get('where', ''))}`)"
            for item in research.get("findings", [])
        )
    timebox = timebox_text(state.get("timebox_s", 0))
    rounds = plural(state.get("round", 0), "round")
    sections = [
        ("Question", fenced(question)),
        ("Summary", para(research["summary"]) if research is not None else "Not run."),
        ("What the brain already says", brain),
        ("Detailed findings", findings),
        ("Invariants touched", items((research or {}).get("invariants", []), "None found.")),
        ("Options", render_options(given["options"])),
        ("Pick", render_pick(state)),
        ("Open questions", items((research or {}).get("open_questions", []), "None.")),
        ("Agent time", f"{spent_m} min of the {timebox} timebox, {rounds} of options."),
    ]
    text = "\n\n".join(f"## {name}\n\n{content}" for name, content in sections)
    return f"{head}{incomplete(found)}# Research: {title_of(question)}\n\n{text}\n"


def render_premortem(premortem: dict[str, Any] | None, found: list[str]) -> str:
    if premortem is None:
        return f"Not run: {'; '.join(found)}." if found else "Not run."
    parts = []
    for n, cause in enumerate(premortem.get("causes", []), start=1):
        parts.append(
            f"### {n}. {line(cause.get('cause', ''))}\n\n"
            f"- Likelihood: {line(cause.get('likelihood', ''))}. "
            f"Impact: {line(cause.get('impact', ''))}.\n"
            f"- Early-warning sign: {line(cause.get('sign', ''))}\n"
            f"- Cheapest experiment: {line(cause.get('experiment', ''))}"
        )
    others = premortem.get("others", [])
    if others:
        parts.append("**Other causes**\n\n" + items(others, ""))
    assumptions = premortem.get("assumptions", [])
    if assumptions:
        marked = "\n".join(
            f"- [{'x' if item.get('checked') else ' '}] {line(item.get('text', ''))}"
            for item in assumptions
        )
        parts.append(f"**Assumptions** (checked or not)\n\n{marked}")
    first = line(premortem.get("first", ""))
    if first:
        parts.append(f"Run first: {first}")
    return "\n\n".join(parts)


def render_outcome(state: dict[str, Any], options: dict[str, Any] | None, found: list[str]) -> str:
    option = picked_option(state)
    if not option:
        why = "; ".join(found) or "no option was picked"
        recommended = ""
        if options is not None:
            recommended = (
                f" The recommendation was {line(options.get('recommendation', ''))}: "
                f"{line(options.get('reason', ''))}"
            )
        return (
            f"No option picked yet: {why}.{recommended}\n\n### Consequences\n\n"
            "- Unknown until an option is picked."
        )
    note = line(state.get("note", ""))
    because = note
    if not because and options is not None and options.get("recommendation") == state["picked"]:
        because = line(options.get("reason", ""))
    chosen = f'Chosen option: "{line(option.get("id", ""))}. {line(option.get("title", ""))}"'
    text = f"{chosen}, because {because}" if because else f"{chosen}."
    good = [f"- Good: {line(pro)}" for pro in option.get("pros", [])]
    bad = [f"- Bad: {line(con)}" for con in option.get("cons", [])]
    consequences = "\n".join(good + bad) or "- None listed."
    return f"{text}\n\n### Consequences\n\n{consequences}"


def render_adr(
    question: str, given: dict[str, Any], found: list[str], *, run: str, today: str
) -> str:
    """The ADR draft: agent-hub's ADR sections with no number, then the premortem."""
    state, research, options = given["state"], given["research"], given["options"]
    head = front_matter(
        [
            ("type", "adr-draft"),
            ("status", "draft"),
            ("complete", "false" if found else "true"),
            ("repos", flow((research or {}).get("repos", []))),
            ("last_verified", today),
            ("provenance", "agent"),
            ("run", run),
        ]
    )
    option = picked_option(state)
    title = line(option.get("title", "")) if option else title_of(question)
    deciders = line(state.get("approver", "")) if option else ""
    considered = "\n".join(
        f"- {line(item.get('id', ''))}. {line(item.get('title', ''))}:"
        f" {line(item.get('summary', ''))}"
        for item in listed(options)
    )
    context = fenced(question)
    if research is not None:
        context += f"\n\n{para(research.get('summary', ''))}"
    context += "\n\nThe spike's findings are in research.md beside this file."
    sections = [
        ("Context and Problem Statement", context),
        ("Considered Options", considered or "None: the options step did not run."),
        ("Decision Outcome", render_outcome(state, options, found)),
        ("Premortem", render_premortem(given["premortem"], found)),
    ]
    text = "\n\n".join(f"## {name}\n\n{content}" for name, content in sections)
    meta = (
        "- Status: draft (record it with /adr)\n"
        f"- Date: {today}\n"
        f"- Deciders: {deciders or 'the owner, once an option is picked'}"
    )
    return f"{head}{incomplete(found)}# Draft: {title}\n\n{meta}\n\n{text}\n"


def read_json(text: str, name: str) -> dict[str, Any] | None:
    """A step's JSON object, or ``None`` when the step did not run (empty text)."""
    if text.strip() == "":
        return None
    try:
        value = json.loads(text)
    except ValueError:
        msg = f"{name} is not JSON"
        raise InputError(msg) from None
    if not isinstance(value, dict):
        msg = f"{name} is not a JSON object"
        raise InputError(msg)
    return value


def feature_folder(hub: Path, slug: str) -> Path:
    """``brain/features/<slug>`` in ``hub``, refused when it would lead outside it."""
    if SLUG.fullmatch(slug) is None:
        msg = f"slug {slug!r} is not ^[a-z0-9][a-z0-9-]{{0,63}}$"
        raise InputError(msg)
    root = (hub / FEATURES).resolve()
    folder = (hub / FEATURES / slug).resolve()
    if folder.parent != root:
        msg = f"slug {slug!r} leads outside {FEATURES}"
        raise InputError(msg)
    return folder


def write_new(folder: Path, stem: str, text: str, *, run: str) -> Path:
    """Write ``text`` to ``<stem>.md`` in ``folder``, or the first free ``-<run>`` name."""
    names = [f"{stem}.md", f"{stem}-{run}.md"]
    names += [f"{stem}-{run}-{n}.md" for n in range(2, MAX_WRITES)]
    for name in names:
        path = folder / name
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(text)
        except FileExistsError:
            continue
        return path
    raise FileExistsError(str(folder / names[-1]))


def joined(argv: Sequence[str]) -> list[str]:
    """``argv`` with each valued option joined to its value, so a value may start with ``-``."""
    out: list[str] = []
    values = iter(argv)
    for item in values:
        value = next(values, None) if item in VALUED else None
        out.append(item if value is None else f"{item}={value}")
    return out


def parser() -> argparse.ArgumentParser:
    found = argparse.ArgumentParser(prog="draft.py")
    found.add_argument("--slug", required=True)
    found.add_argument("--question", required=True)
    for name in STEPS:
        found.add_argument(f"--{name}", default="")
    found.add_argument("--now", type=float, default=None)
    return found


def main(argv: Sequence[str]) -> int:
    try:
        given = parser().parse_args(joined(argv))
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else 2
    hub = Path.cwd()
    try:
        steps = {name: read_json(getattr(given, name), f"--{name}") for name in STEPS}
        steps["research"] = read_json(sys.stdin.read(), "stdin")
        state = steps["state"]
        if state is None:
            msg = "--state is empty"
            raise InputError(msg)
        folder = feature_folder(hub, given.slug)
    except InputError as error:
        print(f"draft.py: {error}", file=sys.stderr)
        return 2
    now = time.time() if given.now is None else given.now
    given_steps: dict[str, Any] = {**steps, "state": state}
    found = reasons(
        state=state,
        recall=steps["recall"],
        research=steps["research"],
        options=steps["options"],
        premortem=steps["premortem"],
    )
    premortem_s = 0.0
    if steps["premortem"] is not None:
        premortem_s = max(0.0, min(now - float(state.get("at", now)), PREMORTEM_CAP_S))
    spent_m = int(state.get("spent_s", 0) + premortem_s) // 60
    # datetime.UTC is 3.11+: the seeded copy must import on 3.9.
    utc = datetime.timezone.utc  # noqa: UP017
    today = datetime.datetime.fromtimestamp(now, tz=utc).date().isoformat()
    run = RUN_ID.sub("", os.environ.get("AGENT_HUB_RUN_ID", "")) or "run"
    research = render_research(
        given.question, given_steps, found, run=run, today=today, spent_m=spent_m
    )
    try:
        folder.mkdir(parents=True, exist_ok=True)
        research_path = write_new(folder, "research", research, run=run)
        adr_path = None
        if steps["options"] is not None:
            adr = render_adr(given.question, given_steps, found, run=run, today=today)
            adr_path = write_new(folder, f"adr-draft-{given.slug}", adr, run=run)
    except OSError as error:
        shown = FEATURES / given.slug
        print(f"draft.py: cannot write {shown}: {error}", file=sys.stderr)
        return 1
    result = {
        "result": "incomplete" if found else "complete",
        "research": str(research_path),
        "adr": "" if adr_path is None else str(adr_path),
        "reasons": found,
        "spent_m": spent_m,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
