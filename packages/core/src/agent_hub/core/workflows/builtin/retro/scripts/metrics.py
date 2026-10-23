# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Gather step 1's numbers for the weekly retro, as one JSON object.

``metrics.py --days N [--root DIR] [--today YYYY-MM-DD]``, run in the hub (``--root``), reads:

- the workflow run records (``.agent-runs/workflows/*/records.jsonl``) started in the last ``N``
  days (1-90), folded into ``workflow.<name>.<number>``: runs, done, failed, cancelled, open,
  retries, review_rounds, gates, gate_wait_h_median, evals, no_ship, no_ship_rate,
  ``outcome.<value>`` and ``failed_at.<node>``. ``retro`` runs, ``issue-to-pr`` runs (the dated
  records count those) and scenario runs are left out;
- ``python3 scripts/retro_metrics.py --days N``: ``issue_runs.*``, ``prs.*``, ``ci.*`` and
  ``memory.*`` (a ``gh … failed`` warning drops its zeros and marks ``github`` missing);
- ``./hub skill-usage --days D`` (D the smallest of 7, 30 or 90 covering ``N``):
  ``skill.<name>.runs_<D>d``, ``agent.<name>.runs_<D>d`` and the idle counts;
- ``python3 scripts/mine_transcripts.py --days N``: ``transcripts.*`` counts, never its text.

It prints ``{"days", "since", "until", "runs", "nothing", "metrics", "idle", "sources",
"left_out", "summary"}``: ``metrics`` maps each key to a number (at most 300), ``runs`` counts the
runs started in the window, ``nothing`` is true when there is none and both run counts (the
run records and ``issue_runs``) were read (a missing one is named in ``left_out``), ``idle``
names the skills and agents not run, ``sources`` says how each source read (``ok``,
``partial`` or ``missing``, with a reason) and ``left_out`` names what the numbers do not cover.
Every source missing exits 1; a ``--days`` outside 1-90 or a bad ``--today`` exits 2.
"""

import argparse
import json
import re
import statistics
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import NamedTuple

Record = dict[str, object]
Metrics = dict[str, float]
Source = dict[str, str]
# ``(argv, timeout in seconds) -> (exit code, stdout, stderr)``, run in the hub.
Runner = Callable[[list[str], int], tuple[int, str, str]]

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
MAX_OUTPUT = MIB
# The sources the run count comes from: "nothing to change" needs both read.
COUNT_SOURCES = frozenset({"runs", "issue_runs"})
TIMED_OUT = 124
NOT_RUN = 127
RETRO_METRICS = ["python3", "scripts/retro_metrics.py"]
RETRO_METRICS_TIMEOUT = 300
SKILL_USAGE = ["./hub", "skill-usage"]
SKILL_USAGE_TIMEOUT = 120
MINING = ["python3", "scripts/mine_transcripts.py"]
MINING_TIMEOUT = 300
TOP_COSTS = 10
PR_KEYS = ("merged", "median_cycle_h", "agent_prs", "agent_merged_without_edits")
CI_KEYS = ("runs", "failed")
MEMORY_KEYS = ("inbox_pending", "learnings_added_or_changed")
# retro_metrics.py prints these on stderr and zeros on stdout: zeros that must not become evidence.
GH_FAILED = {"prs": "gh pr list failed", "ci": "gh run list failed"}
USAGE_HEADER = "| Project | Kind | Name | 7 d | 30 d | 90 d | Last used |"
USAGE_RULE = "| --- | --- | --- | --- | --- | --- | --- |"
NOT_READ_LINE = "Some items were not read; the list may be incomplete."
USAGE_COLUMN = {7: 3, 30: 4, 90: 5}
USAGE_KINDS = {"skill": "skills", "agent": "agents"}
MAX_ROWS = 150
COUNTS_LINE = re.compile(
    r"^Sessions: (\d+) · cost \(sessions with cost records\): \$([0-9.]+)"
    r" · Stop-gate blocks: (\d+)$",
    re.MULTILINE,
)
BLOCKS_HEADING = "## Guard / hook / permission blocks"
BLOCK_BULLET = re.compile(r"^- (\d+)× ", re.MULTILINE)
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


def _ok(name: str) -> Source:
    return _source(name, "ok", "")


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
    counted = f"{workflow_runs} workflow runs, {issue_runs} issue-to-pr runs"
    if _uncounted(sources):
        lines = [
            f"Retro window: {window}.",
            f"Runs started: unknown ({counted} read; see Left out).",
        ]
    else:
        lines = [f"Retro window: {window}.", f"Runs started: {counted}."]
        lines += ["No run in the window: nothing to change."] * (not sum(counts))
    lines.append("Sources:")
    lines += [
        f"- {item['name']}: {item['status']}" + (f" ({item['reason']})" * bool(item["reason"]))
        for item in sources
    ]
    if any(item["name"] == "transcripts" and item["status"] != "missing" for item in sources):
        lines.append("Guard blocks count the transcript report's top 10 reasons: a lower bound.")
    lines.append("Left out:")
    lines += [f"- {line}" for line in left_out]
    return "\n".join(lines)[:MAX_SUMMARY]


def _uncounted(sources: list[Source]) -> list[Source]:
    """The run-count sources that were not read: with one, no run read is not a quiet window."""
    return [
        item for item in sources if item["name"] in COUNT_SOURCES and item["status"] == "missing"
    ]


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
    uncounted = _uncounted(sources)
    left_out += [
        f"the run count: {item['name']} is missing ({item['reason']})" for item in uncounted
    ]
    if len(ordered) > MAX_KEYS:
        left_out.append(f"{len(ordered) - MAX_KEYS} metrics over the {MAX_KEYS} cap")
    found: dict[str, object] = {
        "days": days,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "runs": sum(counts),
        "nothing": sum(counts) == 0 and not uncounted,
        "metrics": {key: merged[key] for key in ordered[:MAX_KEYS]},
        "idle": idle,
        "sources": sources,
        "left_out": left_out,
    }
    window = f"{since} .. {until} ({days} days)"
    found["summary"] = _summary(window, counts=counts, sources=sources, left_out=left_out)
    return found


def run_command(argv: list[str], timeout: int, *, cwd: Path) -> tuple[int, str, str]:
    """The default ``Runner``: ``argv`` in ``cwd``, each stream cut at 1 MiB."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, the hub's own scripts and shim
            argv, cwd=cwd, capture_output=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return TIMED_OUT, "", f"timed out after {timeout} s"
    except OSError as error:
        return NOT_RUN, "", f"{argv[0]}: {error}"
    out = done.stdout[:MAX_OUTPUT].decode("utf-8", "replace")
    return done.returncode, out, done.stderr[:MAX_OUTPUT].decode("utf-8", "replace")


def _failed(code: int, err: str) -> str:
    first = next((line.strip() for line in err.splitlines() if line.strip()), "")
    return f"exit {code}: {first}"


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return round(value, 2) if isinstance(value, float) else value


def _numbers(prefix: str, values: object, names: Iterable[str] | None = None) -> Metrics:
    """``<prefix>.<name>`` for each number in the mapping ``values`` (only ``names`` if given)."""
    if not isinstance(values, dict):
        return {}
    found: Metrics = {}
    for name in values if names is None else names:
        number = _number(values.get(name))
        if number is not None:
            found[f"{prefix}.{_part(str(name))}"] = number
    return found


def _per_repo(report: dict[str, object], section: str, names: tuple[str, ...]) -> Metrics:
    repos = report.get(section)
    found: Metrics = {}
    for repo, values in repos.items() if isinstance(repos, dict) else ():
        found |= _numbers(f"{section}.{_part(str(repo))}", values, names)
    return found


def _issue_runs(report: dict[str, object]) -> Metrics:
    runs = report.get("agent_runs")
    runs = runs if isinstance(runs, dict) else {}
    found = _numbers("issue_runs.outcome", runs.get("outcomes"))
    costs = _numbers("issue_runs.cost_usd", runs.get("cost_per_issue"))
    top = sorted(costs.items(), key=lambda item: -item[1])[:TOP_COSTS]
    return found | dict(top)


def parse_retro_metrics(code: int, out: str, err: str) -> Reading:
    """The ``issue_runs`` and ``github`` sources from ``retro_metrics.py``'s report."""
    report: object = None
    if code == 0:
        try:
            report = json.loads(out)
        except ValueError:
            report = None
    if not isinstance(report, dict):
        reason = _failed(code, err) if code else "not a JSON object"
        missing = [_source("issue_runs", "missing", reason)]
        return Reading(
            {}, [*missing, _source("github", "missing", "retro_metrics.py did not run")], {}
        )
    found = _issue_runs(report)
    failures: list[str] = []
    for section, names in (("prs", PR_KEYS), ("ci", CI_KEYS)):
        warning = next((line for line in err.splitlines() if GH_FAILED[section] in line), "")
        failures += [warning.strip()] * bool(warning)
        found |= {} if warning else _per_repo(report, section, names)
    found |= _numbers("memory", report.get("memory"), MEMORY_KEYS)
    github = _source("github", "missing", "; ".join(failures)) if failures else _ok("github")
    return Reading(found, [_ok("issue_runs"), github], {})


def skill_window(since: int) -> int:
    """The smallest ``hub skill-usage`` window (7, 30 or 90 days) that covers ``since`` days."""
    return next(window for window in (7, 30, 90) if since <= window or window == 90)


def _usage_row(line: str, column: int) -> tuple[str, str, int] | None:
    """``(kind, name, runs)`` from one table row, or None when it does not parse."""
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) != len(USAGE_HEADER.strip("|").split("|")) or cells[1] not in USAGE_KINDS:
        return None
    if not cells[column].isdigit() or not cells[2]:
        return None
    return cells[1], _part(cells[2].removeprefix("/")), int(cells[column])


def _usage_problems(out: str, *, unparsed: int, over: int) -> list[str]:
    problems = ["some items were not read"] * (NOT_READ_LINE in out)
    problems += [f"{unparsed} rows not parsed"] * bool(unparsed)
    return problems + [f"{over} rows over {MAX_ROWS}"] * bool(over)


def parse_skill_usage(code: int, out: str, err: str, *, days: int) -> Reading:
    """The ``skill_usage`` source from ``hub skill-usage --days <days>``'s table."""
    lines = [line.strip() for line in out.splitlines()]
    if code or USAGE_HEADER not in lines:
        reason = _failed(code, err) if code else "no usage table in the output"
        return Reading({}, [_source("skill_usage", "missing", reason)], {})
    rows: list[tuple[str, str, int]] = []
    unparsed = over = 0
    for line in lines[lines.index(USAGE_HEADER) + 1 :]:
        if not line.startswith("|") or line == USAGE_RULE:
            continue
        row = _usage_row(line, USAGE_COLUMN[days])
        if row is None:
            unparsed += 1
        elif sum(kind == row[0] for kind, _, _ in rows) >= MAX_ROWS:
            over += 1
        else:
            rows.append(row)
    idle = {
        plural: [name for kind, name, runs in rows if kind == singular and not runs]
        for singular, plural in USAGE_KINDS.items()
    }
    found: Metrics = {f"{plural}.idle": len(names) for plural, names in idle.items()}
    found |= {f"{kind}.{name}.runs_{days}d": runs for kind, name, runs in rows}
    problems = _usage_problems(out, unparsed=unparsed, over=over)
    status = (
        _source("skill_usage", "partial", "; ".join(problems)) if problems else _ok("skill_usage")
    )
    return Reading(found, [status], idle)


def parse_mining(code: int, out: str, err: str) -> Reading:
    """The ``transcripts`` source: only the counts of ``mine_transcripts.py``'s report, never its
    reason text (it is transcript text)."""
    counts = COUNTS_LINE.search(out) if code == 0 else None
    if counts is None:
        reason = _failed(code, err) if code else "no counts line in the report"
        return Reading({}, [_source("transcripts", "missing", reason)], {})
    section = out.split(BLOCKS_HEADING, 1)[1] if BLOCKS_HEADING in out else ""
    section = section.split("\n## ", 1)[0]
    blocks = sum(int(found.group(1)) for found in BLOCK_BULLET.finditer(section))
    found: Metrics = {
        "transcripts.sessions": int(counts.group(1)),
        "transcripts.cost_usd": round(float(counts.group(2)), 2),
        "transcripts.stop_gate_blocks": int(counts.group(3)),
        "transcripts.guard_blocks": blocks,
    }
    return Reading(found, [_ok("transcripts")], {})


def outside_sources(days: int, runner: Runner) -> list[Reading]:
    """The three commands' readings: retro_metrics.py, hub skill-usage, mine_transcripts.py."""
    window = skill_window(days)
    period = ["--days", str(days)]
    return [
        parse_retro_metrics(*runner([*RETRO_METRICS, *period], RETRO_METRICS_TIMEOUT)),
        parse_skill_usage(
            *runner([*SKILL_USAGE, "--days", str(window)], SKILL_USAGE_TIMEOUT), days=window
        ),
        parse_mining(*runner([*MINING, *period], MINING_TIMEOUT)),
    ]


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


def main(argv: list[str], *, runner: Runner | None = None) -> int:
    found = _arguments(argv)
    if isinstance(found, str):
        print(f"metrics.py: {found}", file=sys.stderr)
        return 2
    days, root, today = found
    since = today - timedelta(days=days)
    run = runner or partial(run_command, cwd=root)
    readings = [runs_source(root, since), *outside_sources(days, run)]
    sources = [item for reading in readings for item in reading.sources]
    if all(item["status"] == "missing" for item in sources):
        reasons = "; ".join(f"{item['name']} ({item['reason']})" for item in sources)
        print(f"metrics.py: every source is missing: {reasons}", file=sys.stderr)
        return 1
    print(json.dumps(assemble(readings, days=days, since=since, until=today)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
