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

import re
import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

Record = dict[str, object]

# Last week's retro is not activity; issue-to-pr runs are counted from the dated records.
LEFT_OUT_WORKFLOWS = frozenset({"retro", "issue-to-pr"})
SHIP_VERDICTS = frozenset({"SHIP", "SHIP-WITH-OWNER-STEPS", "NO-SHIP"})
REVIEW_NODE = "review"
TOP_FAILED_AT = 3
UNSAFE = re.compile(r"[^A-Za-z0-9_.:/-]")


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
