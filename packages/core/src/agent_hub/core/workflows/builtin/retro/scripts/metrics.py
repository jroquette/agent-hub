# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Gather step 1's numbers for the weekly retro, as one JSON object.

``metrics.py --days N [--root DIR] [--today YYYY-MM-DD]`` folds the hub's workflow run records
(``.agent-runs/workflows/*/records.jsonl``) started in the last ``N`` days (1-90) into flat
``workflow.<name>.<number>`` keys: runs, done, failed, cancelled, open, retries, review_rounds,
gates, gate_wait_h_median, evals, no_ship, no_ship_rate, ``outcome.<value>`` and
``failed_at.<node>``. The ``retro`` runs themselves, ``issue-to-pr`` runs (the dated records count
those) and scenario runs are left out.

It prints ``{"days", "since", "until", "runs", "nothing", "metrics", "idle", "sources",
"left_out", "summary"}``: ``metrics`` maps each key to a number (at most 300), ``runs`` counts the
runs started in the window, ``nothing`` is true when there is none, ``sources`` says for each
source whether it was read (``ok``, ``partial`` or ``missing``, with a reason) and ``left_out``
names what the numbers do not cover. A ``--days`` outside 1-90 or a bad ``--today`` exits 2.
"""

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

Record = dict[str, object]
Metrics = dict[str, float]
Source = dict[str, str]

# Last week's retro is not activity; issue-to-pr runs are counted from the dated records.
LEFT_OUT_WORKFLOWS = frozenset({"retro", "issue-to-pr"})
SHIP_VERDICTS = frozenset({"SHIP", "SHIP-WITH-OWNER-STEPS", "NO-SHIP"})
REVIEW_NODE = "review"
TOP_FAILED_AT = 3
UNSAFE = re.compile(r"[^A-Za-z0-9_.:/-]")
MIB = 1024 * 1024
MAX_RUNS = 500
MAX_RECORD_BYTES = 16 * MIB
MAX_RECORDS_TOTAL = 64 * MIB
MAX_KEYS = 300
MAX_SUMMARY = 4000
RUNS_FOLDER = (".agent-runs", "workflows")
RECORDS = "records.jsonl"
# What the numbers do not cover, said in the output and in the summary the owner reads.
LEFT_OUT = (
    "per-workflow cost (not recorded per workflow yet)",
    "per-workflow numbers from the event store (folded here from the run records instead)",
    "guard denies from the event store (no command prints them;"
    " transcript blocks are counted instead)",
    "GitHub review rounds on PRs (scripts get no GitHub token; workflow review rounds are counted)",
)
# The cap keeps the keys in this order: a key's rank is its first prefix's place here.
KEY_ORDER = (
    ("workflow.",),
    ("issue_runs.",),
    ("transcripts.",),
    ("skills.", "agents.", "skill.", "agent."),
)


class Reading(NamedTuple):
    """What one source gave: its keys, how each source behind it read, and its idle names."""

    metrics: Metrics
    sources: list[Source]
    extras: dict[str, list[str]]


def _part(text: str) -> str:
    """One key segment: only the key pattern's characters, at most 60 of them."""
    return UNSAFE.sub("_", text)[:60] or "_"


def _moment(record: Record) -> datetime | None:
    stamp = record.get("ts")
    if not isinstance(stamp, str):
        return None
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


@dataclass
class _Tally:
    """One workflow's runs in the window, as they are folded."""

    counts: Counter[str] = field(default_factory=Counter)
    outcomes: Counter[str] = field(default_factory=Counter)
    failed_at: Counter[str] = field(default_factory=Counter)
    waits: list[float] = field(default_factory=list)

    def add(self, run: list[Record]) -> None:
        self.counts["runs"] += 1
        gates: dict[tuple[object, object], datetime] = {}
        last_failed = ""
        ended: Record | None = None
        for record in run:
            event = record.get("event")
            if event == "step_end":
                last_failed = self._step(record) or last_failed
            elif event == "retry":
                self.counts["retries"] += 1
            elif event in ("gate", "decision"):
                self._gate(record, gates)
            elif event == "end":
                ended = record
        self._end(ended, last_failed)

    def _step(self, record: Record) -> str:
        """Counts a step end; returns its node when it failed."""
        node, status, output = record.get("node"), record.get("status"), record.get("output")
        node = node if isinstance(node, str) else ""
        if status != "skipped" and node.split("__")[-1] == REVIEW_NODE:
            self.counts["review_rounds"] += 1
        verdict = output.get("verdict") if isinstance(output, dict) else None
        if verdict in SHIP_VERDICTS:
            self.counts["evals"] += 1
            self.counts["no_ship"] += verdict == "NO-SHIP"
        return node if status == "failed" else ""

    def _gate(self, record: Record, gates: dict[tuple[object, object], datetime]) -> None:
        moment, place = _moment(record), (record.get("node"), record.get("attempt"))
        if record.get("event") == "gate":
            self.counts["gates"] += 1
            if moment is not None:
                gates[place] = moment
        elif moment is not None and place in gates:
            self.waits.append((moment - gates.pop(place)).total_seconds() / 3600)

    def _end(self, ended: Record | None, last_failed: str) -> None:
        if ended is None:
            self.counts["open"] += 1
            return
        status = ended.get("status")
        if status in ("done", "failed", "cancelled"):
            self.counts[str(status)] += 1
        outcome = ended.get("outcome")
        if isinstance(outcome, str) and outcome:
            self.outcomes[outcome] += 1
        reason = ended.get("reason")
        if status == "failed":
            self.failed_at[reason if isinstance(reason, str) and reason else last_failed] += 1

    def metrics(self, prefix: str) -> dict[str, float]:
        names = ("runs", "done", "failed", "cancelled", "open", "retries", "review_rounds")
        found: dict[str, float] = {f"{prefix}.{name}": self.counts[name] for name in names}
        found[f"{prefix}.gates"] = self.counts["gates"]
        if self.waits:
            found[f"{prefix}.gate_wait_h_median"] = round(statistics.median(self.waits), 2)
        evals = self.counts["evals"]
        found[f"{prefix}.evals"] = evals
        found[f"{prefix}.no_ship"] = self.counts["no_ship"]
        if evals:
            found[f"{prefix}.no_ship_rate"] = round(self.counts["no_ship"] / evals, 2)
        for outcome, n in sorted(self.outcomes.items()):
            found[f"{prefix}.outcome.{_part(outcome)}"] = n
        for node, n in self.failed_at.most_common(TOP_FAILED_AT):
            if node:
                found[f"{prefix}.failed_at.{_part(node)}"] = n
        return found


def _counted_workflow(run: list[Record], since: date) -> str | None:
    """The run's workflow when it counts: a start in the window, not left out."""
    begin = next((record for record in run if record.get("event") == "start"), None)
    if begin is None or begin.get("kind") == "scenario":
        return None
    name, moment = begin.get("workflow"), _moment(begin)
    if not isinstance(name, str) or name in LEFT_OUT_WORKFLOWS or moment is None:
        return None
    return name if moment.astimezone(UTC).date() >= since else None


def fold_runs(records: Iterable[list[Record]], *, since: date) -> dict[str, float]:
    """``workflow.<name>.<number>`` for each run (its record lines) started since ``since``."""
    tallies: dict[str, _Tally] = {}
    for run in records:
        name = _counted_workflow(run, since)
        if name is not None:
            tallies.setdefault(name, _Tally()).add(run)
    found: dict[str, float] = {}
    for name in sorted(tallies):
        found |= tallies[name].metrics(f"workflow.{_part(name)}")
    return found


def _run_folders(folder: Path, since: date) -> tuple[list[Path], list[str]]:
    """The run folders changed since ``since`` (links left out), newest first, at most 500."""
    start = datetime.combine(since, datetime.min.time(), UTC).timestamp()
    found: list[tuple[float, str, Path]] = []
    for child in folder.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        changed = child.stat().st_mtime
        if changed >= start:
            found.append((changed, child.name, child))
    found.sort(reverse=True)
    problems = ["more than 500 runs; oldest left out"] if len(found) > MAX_RUNS else []
    return [path for _, _, path in found[:MAX_RUNS]], problems


def _parse_lines(data: bytes) -> tuple[list[Record], int]:
    """The JSON object lines of one record file, and how many lines were not one."""
    lines: list[Record] = []
    bad = 0
    for raw in data.splitlines():
        if not raw.strip():
            continue
        try:
            line = json.loads(raw)
        except ValueError:
            line = None
        if isinstance(line, dict):
            lines.append(line)
        else:
            bad += 1
    return lines, bad


def read_runs(root: Path, since: date) -> tuple[list[list[Record]], list[str]]:
    """Each recent run's record lines under ``root``, within the bounds, and what was left out."""
    folders, problems = _run_folders(root.joinpath(*RUNS_FOLDER), since)
    runs: list[list[Record]] = []
    large = bad = total = 0
    for folder in folders:
        path = folder / RECORDS
        if path.is_symlink() or not path.is_file():
            continue
        size = path.stat().st_size
        if size > MAX_RECORD_BYTES:
            large += 1
            continue
        if total + size > MAX_RECORDS_TOTAL:
            problems.append("run records over 64 MiB in total; the oldest left out")
            break
        total += size
        lines, skipped = _parse_lines(path.read_bytes())
        bad += skipped
        runs.append(lines)
    problems += [f"{large} run records over 16 MiB"] * bool(large)
    problems += [f"{bad} bad lines"] * bool(bad)
    return runs, problems


def runs_source(root: Path, since: date) -> Reading:
    """The ``runs`` source: the fold of the run records, and how they read."""
    folder = root.joinpath(*RUNS_FOLDER)
    if folder.is_symlink() or not folder.is_dir():
        return Reading({}, [_source("runs", "missing", "no .agent-runs/workflows folder")], {})
    try:
        runs, problems = read_runs(root, since)
    except OSError as error:
        return Reading({}, [_source("runs", "missing", f"cannot read the runs: {error}")], {})
    status = "partial" if problems else "ok"
    return Reading(fold_runs(runs, since=since), [_source("runs", status, "; ".join(problems))], {})


def _source(name: str, status: str, reason: str) -> Source:
    return {"name": name, "status": status, "reason": reason[:200]}


def _rank(key: str) -> int:
    return next(
        (n for n, prefixes in enumerate(KEY_ORDER) if key.startswith(prefixes)), len(KEY_ORDER)
    )


def _count(metrics: Metrics, prefix: str, suffix: str) -> int:
    return int(sum(v for k, v in metrics.items() if k.startswith(prefix) and k.endswith(suffix)))


def _summary(
    window: str, *, counts: tuple[int, int], sources: list[Source], left_out: list[str]
) -> str:
    """What the owner and the agent read first: the window, the runs, the sources, the gaps."""
    workflow_runs, issue_runs = counts
    lines = [
        f"Retro window: {window}.",
        f"Runs started: {workflow_runs} workflow runs, {issue_runs} issue-to-pr runs.",
    ]
    if not sum(counts):
        lines.append("No run in the window: nothing to change.")
    lines.append("Sources:")
    lines += [
        f"- {item['name']}: {item['status']}" + (f" ({item['reason']})" * bool(item["reason"]))
        for item in sources
    ]
    lines.append("Left out:")
    lines += [f"- {line}" for line in left_out]
    return "\n".join(lines)[:MAX_SUMMARY]


def assemble(readings: list[Reading], *, days: int, since: date, until: date) -> dict[str, object]:
    """The script's output from every source's reading: capped keys, run count and summary."""
    merged: Metrics = {}
    sources: list[Source] = []
    idle: dict[str, list[str]] = {"skills": [], "agents": []}
    for reading in readings:
        merged |= {key: value for key, value in reading.metrics.items() if key not in merged}
        sources += reading.sources
        for kind, names in reading.extras.items():
            idle.setdefault(kind, []).extend(names)
    counts = (_count(merged, "workflow.", ".runs"), _count(merged, "issue_runs.outcome.", ""))
    ordered = sorted(merged, key=_rank)
    left_out = list(LEFT_OUT)
    if len(ordered) > MAX_KEYS:
        left_out.append(f"{len(ordered) - MAX_KEYS} metrics over the {MAX_KEYS} cap")
    found: dict[str, object] = {
        "days": days,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "runs": sum(counts),
        "nothing": sum(counts) == 0,
        "metrics": {key: merged[key] for key in ordered[:MAX_KEYS]},
        "idle": idle,
        "sources": sources,
        "left_out": left_out,
    }
    window = f"{since} .. {until} ({days} days)"
    found["summary"] = _summary(window, counts=counts, sources=sources, left_out=left_out)
    return found


def _arguments(argv: list[str]) -> tuple[int, Path, date] | str:
    """``(days, root, today)``, or what is wrong with the arguments."""
    parser = argparse.ArgumentParser(prog="metrics.py")
    parser.add_argument("--days", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--today", default="")
    given = parser.parse_args(argv)
    if not given.days.isdigit() or not 1 <= int(given.days) <= 90:
        return f"--days must be a whole number from 1 to 90, not {given.days!r}"
    try:
        today = date.fromisoformat(given.today) if given.today else datetime.now(UTC).date()
    except ValueError:
        return f"--today must be YYYY-MM-DD, not {given.today!r}"
    return int(given.days), Path(given.root), today


def main(argv: list[str]) -> int:
    found = _arguments(argv)
    if isinstance(found, str):
        print(f"metrics.py: {found}", file=sys.stderr)
        return 2
    days, root, today = found
    since = today - timedelta(days=days)
    readings = [runs_source(root, since)]
    print(json.dumps(assemble(readings, days=days, since=since, until=today)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
