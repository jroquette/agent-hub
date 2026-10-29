# 0053. Interactive-path latency budgets

- Status: accepted
- Date: 2026-10-28
- Deciders: José Henrique Roquette

## Context and Problem Statement

An interactive path is any code that a person waits on: a `hub` command, a hook on a Claude Code tool call, the
start of a session, an API route or page of `hub web`, a restart of `hub web`, and the Stop gate.

The v0.27.0 audit found batch work on these paths: the doctor rules on every request, a brief with network calls at
session start, the full test suite at every Stop, a fold of the whole event log, and a git lookup of the release on
every `./hub`. No rule says what may run there, and until `make perf` (AGH-599) nothing measured it.

The limits we have today are kill limits (hook timeouts in the generated settings, `check_fast_timeout` up to 160 s)
or test constants spread over the suite (the guard's 1.5 s p95 ceiling in `test_guard_extension.py`, the 2 s
session-detail smoke in `apps/web/e2e/smoke.spec.ts`). They are not budgets. [SPEC](../SPEC.md) had no
non-functional requirements section.

Which paths are interactive, what is the budget of each, how is it measured, and what may not run on them?

Decision drivers:

- Each performance ticket and each review must point to one rule.
- The budgets must be measured one way, by `make perf`, and be enforceable in CI (AGH-602).
- An accepted ADR is never edited, so its numbers are frozen when it is accepted.

## Considered Options

### (a) The numbers

- **A1. The ticket's table as written** (300 ms per command, 150 ms `--version`, 80 ms per hook, 1.5 s session,
  150 ms per route, 800 ms and 5 API calls per page, 1 s and 300 MB per restart, 30 s Stop). Simple, but ambiguous:
  per hook script or per tool call, median or p95, cold or warm. It also collides with the event sensor's 0.5 s
  timeout, with `./hub` through `uvx` and with `check_fast_timeout`.
- **A2. The same targets, each measure defined.** Every number is measured one way and each milestone knows its
  target. The table is longer, and the per-tool-call hook sum adds work (the guard must lose about 40 ms, or stop
  running in sequence with the sensor).
- **A3. Relaxed where the cause is outside our code** (guard 120 ms, `./hub` left out for good, session 3 s,
  restart at 400k events only). Green sooner, but it gives up on the audit's worst problems: session start and `./hub`.

### (b) Where the budgets live

- **B1. Only in the ADR.** `make perf` and CI need a data file anyway, so the two drift with no check, and every
  tightening needs a new ADR.
- **B2. Only in a data file, with no numbers in the ADR.** No drift, but the ADR no longer names each budget, and a
  loosening is an ordinary file edit.
- **B3. Both, with a one-sided drift test.** The ADR table is the ceiling; the data file holds the live values and
  may only be tighter. A test fails when the file is looser than the ADR. The cost is a small table parser in a test.

### (c) Enforcing what is not allowed

- **C1. A written rule only.** No cost, but ADR 0012's written hook rule did not stop the audit's findings.
- **C2. A review checklist.** It covers every item but depends on judgment and misses indirect calls.
- **C3. A test for every item.** Deterministic, but the most work, and a "full scan" or "full suite" is hard to test
  without false alarms.
- **C4. Tests where they are cheap, a checklist line for the rest, `make perf` as the backstop.** Two mechanisms to
  keep, and the checklist items still depend on judgment.

### (d) The reference machine

The options keep the E labels of the options note the owner decided on.

- **E1. The CI runner.** It enforces, but it is shared and noisy, and its size depends on the plan.
- **E2. A developer laptop.** It is what the owner feels, but it cannot be reproduced or enforced.
- **E3. A reference machine class**, the audit's: CI is held to it with a margin. If the CI runner is smaller, the
  margin or the runner must cover the gap.

## Decision Outcome

Chosen options: **A2, B3, C4 and E3**. A2 is the only table that can be measured without doubt. B3 lets the ADR name
every budget while tightening stays a data change. C4 tests what can be tested reliably and still names the rest.
E3 keeps the audit's numbers comparable.

### Budget ceilings

These are the ceilings. A number is the highest value allowed; `—` means no limit of that sort. The columns `kind` and
`paths` map each row to the rows of `make perf`: `kind` is the probe kind, and `paths` is either one canonical path or
`every`, which means each path of that kind that no other row names. A row whose `kind` is `—` is not a `make perf`
row yet. A row with `—` in all three limit columns has no budget.

| Interactive path | kind | paths | Measure | p95 (ms) | API calls | peak RSS (MB) |
| --- | --- | --- | --- | --- | --- | --- |
| `hub --version` | cli | `hub --version` | Wall time from spawn to exit of the installed `hub` | 150 | — | — |
| A simple `hub` command | cli | every | Wall time from spawn to exit of the installed `hub` (`hub brief --no-network` today) | 300 | — | — |
| `./hub` through `uvx` | cli | `./hub --version (local uvx stand-in)` | Its own row: no budget until AGH-606, then the `hub` row plus 300 ms | — | — | — |
| One hook script | hook | every | Wall time from spawn to exit of each hook script, fed a synthetic input (the Stop gate with no change included) | 80 | — | — |
| A session ready, Claude aside | hook | `session_start (local uvx stand-in)` | Wall time of the SessionStart hook | 1500 | — | — |
| All hooks on one tool call | — | — | Sum of the hook scripts that run on one tool call (guard and event sensor on a PreToolUse Bash call); measured today by adding the p95 of the `make perf` rows `guard (PreToolUse Bash)` and `event_sensor (PreToolUse, sensor closed)` | 150 | — | — |
| An API route | route | every | Warm (after the first request), sequential requests, on the 400,000-event fixture | 150 | — | — |
| A page ready | page | every | Cold load on a warm server with an empty browser cache; ready when no `/api/v1/` request is in flight for 500 ms after `load`; API calls counted during the load | 800 | 5 | — |
| `hub web` restart, first HTML | restart | `hub web start → GET /` | Start of `hub web` to the first HTML answer, 400,000 events | 1000 | — | 300 |
| `hub web` restart, first data | restart | `hub web start → /api/v1/sessions` | Start of `hub web` to the first `/api/v1/sessions` answer, 400,000 events | 1000 | — | 300 |
| `hub web` restart at 1M events | — | — | Both restart rows of `make perf` run by hand with `PERF_EVENTS=1000000`: measured now, enforced from milestone 4 | 1000 | — | 300 |
| Stop gate, code changed | — | — | Wall time of the repo's own `check_fast` run by the gate; not a `make perf` row: measured by timing that command by hand (`make check-fast` here) | 30000 | — | — |

Rules for every row:

- **p95** is the 95th percentile of wall time over warm runs (`PERF_RUNS`, 10 by default; the restart rows use
  `PERF_RESTART_RUNS`, 3 by default, so there the p95 is in effect the slowest run): the uv cache is filled and `.pyc`
  files are compiled. The first run after an install or an upgrade is not judged.
- **A hook** must meet both its script row (80 ms) and the per-tool-call sum (150 ms).
- **API routes:** from milestone 2, parallel requests must be no slower than sequential ones, as a new row.
- **Pages:** from milestone 3, the API calls a page makes while its tab is idle become a new row.
- **The Stop gate:** the 150 s default and 160 s maximum of `check_fast_timeout` stay as kill limits, not budgets.

### Measuring and the budgets file

- `make perf` (AGH-599, [TESTING.md](../TESTING.md) "Performance (`make perf`)") is the one measuring tool. Its
  runner exits 0 (all rows measured, also when a row is over), 1 (`PERF_STRICT=1` and a row is over) or 2 (the suite
  failed); `make perf` exits non-zero in both failure cases. CI enforces the rows through AGH-602.
- The live values are in [`scripts/perf/budgets.json`](../../scripts/perf/budgets.json), keyed by `(kind, path)`,
  the one file that `make perf` and AGH-602 read. It may tighten a ceiling or add rows (new paths, new limits) with
  no ADR. A looser value needs a new ADR that supersedes this one.
- `tests/unit/scripts/perf/test_budgets.py` (part of `make check-fast`) reads this table. It fails when a file
  value is looser than its row's ceiling, when a probed path with a budget here has no entry in the file, or when
  this table names a path that `make perf` does not produce.
- The budgets file goes under `hub.json` → `guard.ask_before_edit`, so the guard asks before any edit (a separate
  hub PR).

### The reference machine

Linux, 4 vCPU, Python 3.14, warm uv cache: the machine class of the audit. CI is held to it with AGH-602's noise
margin. A laptop run is information only. Every `perf.json` row records its machine.

### What is not allowed on an interactive path

| Not allowed | How it is enforced |
| --- | --- |
| A network call with no cache | A test that hooks and simple `hub` commands make no network call (AGH-633) |
| A new database connection per query | AGH-600's tests count connections per request on key routes |
| A full scan of the event log | AGH-600's SQL statement counts on key routes; a Definition of Done line |
| The doctor rules | A Definition of Done line in [CONTRIBUTING.md](../CONTRIBUTING.md) |
| A full test suite | A Definition of Done line (the Stop gate runs only the repo's `check_fast`) |

`make perf` and AGH-602 are the backstop for all five: they catch the effect on the paths they measure.

### Exceptions

- The event sensor's 0.5 s timeout when `hub web` hangs ([ADR 0021](0021-hook-event-sensor.md)) is a named
  exception to the hook budgets. The budget covers the normal case, with the sensor's server closed or answering.
- `./hub` through `uvx` has no budget until AGH-606 removes the release lookup; then its row is the `hub` row plus
  300 ms.

### Existing breaches

- The store engine uses `NullPool` (`packages/storage/src/agent_hub/storage/engine.py`), so every `engine.connect()`
  opens a new SQLite connection. AGH-609 fixes it.
- The audit's paths over budget: `hub --version` 1.72 s, `./hub --version` 4.9 s, the guard 118-126 ms, session
  start 6.1 s, `/api/v1/sessions?issue=` 1.6 s, a feature route 2.27 s, the skills route 886 ms, search 242 ms, the
  features page 60 API calls, a feature page 18, the home page 10, and the first API answer after a restart 15.6 s and
  1.35 GB.

### Consequences

- Good: each milestone has an exact target, and each review can point to one rule.
- Good: tightening a budget is a data change; a quiet loosening fails `make check-fast`.
- Good: [ADR 0012](0012-cli-subsumes-hub-scripts.md)'s rule that hooks do not call the CLI, and
  [ADR 0021](0021-hook-event-sensor.md)'s sensor timeout, stay. They are now cases of this general rule; nothing is
  superseded.
- Bad: the table here shows the ceiling, not the live value; a reader checks `scripts/perf/budgets.json` for that.
- Bad: a small markdown-table parser in a test, and two enforcement mechanisms (tests and a checklist) to keep.
- Bad: the per-tool-call hook sum (150 ms) means the guard must lose about 40 ms, or stop running in sequence with the
  sensor.
- Neutral: the older, looser test budgets (the guard's 1.5 s ceiling, the 2 s session-detail smoke) are retired once
  `make perf` enforces the matching rows (AGH-634). The tighter constants in `test_performance.py` stay as regression
  floors on their own fixtures.

## More Information

- [SPEC](../SPEC.md) "Non-functional requirements" links this ADR and the budgets file.
- [TESTING.md](../TESTING.md) "Performance (`make perf`)": the suite, its canonical paths, knobs and exit codes.
- [ADR 0005](0005-testing-strategy.md): the testing strategy; `make perf` is in no gate.
- Tickets: AGH-599 (`make perf`), AGH-600 (SQL statements and connections per request), AGH-602 (CI enforcement),
  AGH-606 (`./hub` release lookup), AGH-609 (`NullPool`), AGH-633 (no network in hooks and simple commands),
  AGH-634 (retire the looser test budgets).
