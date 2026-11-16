# Decisions and open questions

Each item: the question, the recommendation taken in this design, the main alternative, why, and its status: **Decided in this design** (the screens assume it) or **Open for the owner** (screens show the recommendation but the owner should confirm). Numbering is stable for references from other specs (e.g. "see Q3").

## Summary
| # | Question | Status |
|---|---|---|
| Q1 | Session that never sent `session.end` | Decided in this design |
| Q2 | Idle threshold | Open for the owner |
| Q3 | Same fact from several sources | Decided in this design |
| Q4 | Comparing two sessions | Open for the owner |
| Q5 | Events arriving late or out of order | Decided in this design |
| Q6 | Clock skew between sources | Decided in this design |
| Q7 | Subagent sessions: own Session or nested | Decided in this design |
| Q8 | Cost when OTel and transcript disagree | Open for the owner |
| Q9 | How long ended tiles stay in Live | Decided in this design |
| Q10 | When to alert vs quiet status | Decided in this design |
| Q11 | Deep-link stability with UUIDv7 | Decided in this design |
| Q12 | Redaction of secrets in diffs | Decided in this design |
| Q13 | Multi-project time zones | Decided in this design |
| Q14 | "Workflow" vs "WorkflowRun" naming in UI | Decided in this design |
| Q15 | Proposed event types (step.start, run.end, learning.rejected, session.summary) | Open for the owner |
| Q16 | Learning effect: causality claims | Decided in this design |
| Q17 | Budget overrun behaviour shown in UI | Open for the owner |

---

### Q1 · A session that never sent `session.end`
- **Question:** Claude Code can crash, be killed or lose its hook; the collector then never sees `session.end`. What status does the session have?
- **Recommendation:** After 30 min with no event from any source, the API derives status **"ended (inferred)"**. Render: `StatusBadge` `ended` with a dashed `text-subtle` outline, label "Ended (inferred)" and tooltip "No end event received. Last activity 10:42 (transcript). agent-hub marked it ended after 30 min of silence." The end time shown is the last event time, marked with `DerivedLabel` "derived". Outcome column shows "unknown" (never "done"). If any event later arrives for the same session id, the inference is dropped silently and the session returns to live or idle; the timeline shows a lifecycle row "Resumed after 47 min" (`ev-lifecycle`). Duration counts until last activity, not until inference time. The Session detail header shows "No end event received" next to the badge.
- **Alternative:** Leave it "live" for ever, or "idle" with no end.
- **Why:** Show only what the record shows (principle 3): we did not see an end, so the end is labelled inferred. Live counts must not inflate with ghosts (situation awareness, calibrated trust).
- **Status:** Decided in this design (30 min value is configurable in Settings › Collector, default 30).

### Q2 · Idle threshold
- **Question:** When is a live session "idle"?
- **Recommendation:** Idle after **5 minutes** with no event from claude_code hooks or transcript while no gate request is open. Waiting (open gate.request) never becomes idle. Tiles show "Idle · 7 min" with moon icon (`idle`). Long-running tool calls (a `make check` with no result yet) do not count as idle: a pending tool.call keeps the session live, shown as "Running make check · 6 min".
- **Alternative:** 2 min (catches stalls sooner, but flaps during long thinking turns), or adaptive per agent (p95 of that agent's gaps).
- **Why:** 5 min sits above the observed p95 gap between turns (about 2 min 40 s) so flapping is rare (alarm fatigue), and well under the 30 min inferred-end limit (Q1).
- **Status:** Open for the owner: confirm 5 min, or adopt adaptive thresholds once enough data exists.

### Q3 · The same fact from several sources, shown once
- **Question:** Tokens come from OTel and from the transcript; a PR link from the executor and from GitHub; a tool call from hooks and transcript. How do we avoid duplicates?
- **Recommendation:** Canonical events keep each source's record (identity = source + source_id), but the derived Session and the UI merge by a **precedence table** per fact, and show one value with its source in the tooltip ("From OpenTelemetry · transcript agrees"):

| Fact | Precedence (first wins) | Note |
|---|---|---|
| Tool call / result | claude_code hooks → transcript | transcript fills gaps if hooks were off |
| Message, reasoning summary | transcript | only source |
| Tokens and cost | otel → transcript | see Q8 for disagreement |
| Gate request / result | executor → claude_code hooks | |
| PR url, CI, review | github → executor | |
| Issue state, labels | linear → executor | |

The Raw events tab still lists every source's event, with a "merged into" column.
- **Alternative:** Show all sources side by side.
- **Why:** One value per fact lowers cognitive load; provenance stays one hover away (explainability).
- **Status:** Decided in this design.

### Q4 · Comparing two sessions
- **Question:** How does a user compare two sessions (e.g. attempt 1 vs attempt 2)?
- **Recommendation:** P3. Multi-select exactly 2 rows in the Sessions list → "Compare" → `/sessions/compare?a=…&b=…`. Layout: shared header table (agent, model, turns, tokens, cost, duration, outcome) with differences in `body-strong`; two timelines side by side aligned by **turn number** (not wall-clock), with a sync-scroll toggle; files touched as a Venn-like three-column list (only A · both · only B); cost per turn as two `LineChart` series. No "better/worse" judgement colors.
- **Alternative:** Overlay one timeline on the other; or compare only aggregates.
- **Why:** Turn alignment matches how attempts differ; side by side keeps each trace legible (Gestalt). Comparison is a common audit need for retries.
- **Status:** Open for the owner: confirm P3 scope and that only 2 (not N) sessions compare.

### Q5 · Events arriving late or out of order
- **Question:** Transcript events arrive after each turn, GitHub by polling, OTel cost after the session ends. How does the timeline behave?
- **Recommendation:** Order the timeline by event timestamp (UTC), ties by source order (hooks, transcript, otel, executor, github, linear) then source_id. A late event inserts in its time position with a `dur-base` fade and a small "arrived late" `caption` for 10 s; if the user is in follow-tail and the insertion is above the viewport, it does not scroll them (the "12 new events" pill counts only events below). Late enrichments after the end (cost, PR link) appear as `ev-lifecycle` rows "Cost updated after the session ended · +$0.0412" at the end, plus the header value changes with `DerivedLabel` "updated 14:31". SSE resumes with `Last-Event-ID` so nothing is lost on reconnect.
- **Alternative:** Order by arrival time.
- **Why:** The question "why did the agent do that" needs causal order; arrival order misleads. Telling the user something arrived late keeps trust.
- **Status:** Decided in this design.

### Q6 · Clock skew between sources
- **Question:** GitHub, Linear and the local machine have different clocks; small skew can put a CI result before the push.
- **Recommendation:** Local sources (hooks, transcript, otel, executor) share the machine clock and are trusted as is. Remote sources (github, linear) keep their own timestamps but the collector also records `received_at`; if a remote event would precede its causal parent (CI result before push) by < 2 min, the UI orders it after the parent and shows the original time in the tooltip "GitHub time 10:41:58 (2 s before the push; clock skew)". Skew > 2 min is a doctor info finding `collector.skew`.
- **Alternative:** Rewrite all timestamps to receive time.
- **Why:** Keeps immutable records (events are never edited) while showing a causal order humans expect.
- **Status:** Decided in this design.

### Q7 · Subagent sessions: own Session or nested
- **Question:** An `Agent` tool call starts a subagent with its own Claude Code session. Is it its own Session?
- **Recommendation:** Both: it is **its own Session** in the data (own id, agent, cost, transcript) with `parent_session_id` and `parent_event_id`. In the parent's timeline it renders as a nested `SubagentLane` (indent `space-5` per level, collapsed by default to one row "hub-workflow:quality-reviewer · 18 turns · $0.62 · done"), expandable in place, with "Open as session". The Sessions list hides child sessions by default (toggle "Include subagents"); Live sessions shows them as their own tiles grouped under the parent. Parent cost shows "incl. subagents $3.10" with a split.
- **Alternative:** Only nested (loses per-agent cost and metrics by role) or only separate (loses the causal picture).
- **Why:** Metrics by agent role need separate sessions; "why did it do that" needs the nested view.
- **Status:** Decided in this design.

### Q8 · Cost reconciliation when OTel and transcript disagree
- **Question:** OTel usage and transcript-derived token counts can differ (missed exports, retries, cache accounting).
- **Recommendation:** OTel is authoritative when present for the whole session. If the two differ by more than 1 % or $0.01, the Cost tab shows a `Banner` (info, not error): "Two sources disagree: OpenTelemetry $1.2734, transcript estimate $1.3110. Showing OpenTelemetry." Session and run totals use the chosen value so totals add up exactly. If OTel is missing for some turns, those turns use the transcript value and are marked "estimated" with a dashed segment in the stacked area. Runs sum sessions; no second rounding.
- **Alternative:** Take the maximum (conservative for budgets).
- **Why:** One consistent number; disagreement visible but quiet.
- **Status:** Open for the owner: OTel-first vs max-of-sources for budget enforcement.

### Q9 · How long ended tiles stay in Live sessions
- **Question:** When a session ends, does its tile vanish?
- **Recommendation:** Move it to an "Ended" group at the bottom for **2 minutes** with its outcome badge and summary line, then remove it (no animation beyond `dur-base` fade). A failed or blocked session stays 10 min. Hovering pauses removal. The group header shows "Ended · last 2 min".
- **Alternative:** Keep until dismissed.
- **Why:** Lets the eye register change (perception) without accumulating clutter; failures deserve longer dwell.
- **Status:** Decided in this design.

### Q10 · When to alert vs quiet status (alarm fatigue)
- **Question:** Which events interrupt the user?
- **Recommendation:** No toasts, sounds or browser notifications for routine events (session started/ended, run reported, tool error). Interruptions are reserved for the user's own action results (toasts) and, opt-in, browser notifications for: a gate waiting on me > 15 min, a run failed, collector offline > 5 min. Everything else is quiet status: Needs-you strip, sidebar badges, the waiting amber tile edge, the subtle red edge for errors. No flashing; one pulse dot loop. ARIA live regions are polite and rate-limited to one message per 10 s.
- **Alternative:** Toast on every failure.
- **Why:** Alarm fatigue (Sendelbach & Funk); calm, glanceable status keeps real alerts meaningful.
- **Status:** Decided in this design.

### Q11 · Deep-link stability with UUIDv7
- **Question:** Are links to sessions, events and runs stable?
- **Recommendation:** All entities use UUIDv7 ids; URLs use the full id (`/sessions/0192a3f1-…`) while the UI displays an 8-char short form (`5091b986`). The router also accepts any unique prefix ≥ 8 chars and redirects to the canonical URL. Selected event, tab, filters live in query params (`?tab=timeline&event=…&types=tool.call`). If an entity was deleted by retention, the URL shows `ExpiredContent` "This session's transcript expired on 2026-11-10. Structured events and summary remain." rather than 404. Events are linked by their canonical event id, stable across re-ingest because identity = (source, source_id).
- **Alternative:** Sequential ids per project.
- **Why:** Links pasted into Linear and PRs must keep working; time-ordered UUIDv7 also sorts naturally.
- **Status:** Decided in this design.

### Q12 · Redaction of secrets in diffs
- **Question:** An Edit diff or Bash output may contain a token.
- **Recommendation:** Redaction runs in the collector before storage, on payloads and diff blobs. The `DiffViewer` renders the redacted span as a `RedactionChip` `[redacted: github token]` inline in the line, keeping the line's add/remove ground. The whole value is replaced, never partially shown; no reveal button; copy of the line copies the chip text. A file whose diff had redactions gets a guard-colored shield count in Files & diffs ("1 redaction"). Line counts (+/−) are computed before redaction so they stay accurate.
- **Alternative:** Hide the whole line or the whole file.
- **Why:** Privacy first while keeping the diff readable; never invites copying sensitive data.
- **Status:** Decided in this design.

### Q13 · Multi-project time zones
- **Question:** Projects or teammates may live in different zones; whose time do we show?
- **Recommendation:** One viewer time zone for the whole app (local default, UTC toggle in the top bar). Times are never shown in a project's zone. Day-bucketed charts bucket by the viewer's zone and say so in the period line ("days in Europe/Lisbon"). Tooltips always add the UTC time. Exports use UTC ISO 8601.
- **Alternative:** Per-project zone in hub.json.
- **Why:** One consistent clock reduces mental conversion (working memory); local-first single user.
- **Status:** Decided in this design.

### Q14 · "Workflow" vs "WorkflowRun" naming in the UI
- **Question:** The glossary has Workflow (definition) and WorkflowRun ("run"). How does the UI keep them apart?
- **Recommendation:** UI copy: "workflow" for the definition, "run" for an execution; never "workflow run" in labels except the sidebar item "Workflow runs" (to disambiguate from Sessions) and the API path `/workflow-runs`. A Session is never called a run; tooltips say "This session belongs to run 01923f1e (issue-to-pr r4)". Run ids show as "run 01923f1e"; session ids as "session 5091b986". Workflows show revisions ("r4"), runs show the pinned revision and hash.
- **Alternative:** "Execution" for runs.
- **Why:** Glossary is binding; consistent words keep information scent.
- **Status:** Decided in this design.

### Q15 · Proposed event types
- **Question:** Should the closed type list add `step.start`, `step.end`, `run.end`, `learning.rejected`, `session.summary`?
- **Recommendation:** Yes, all five. Run detail's Gantt and the Workflows overlay need step boundaries; Learnings triage needs rejections as events for provenance; the summary card needs a stored, immutable summary.
- **Alternative:** Derive steps from executor logs.
- **Why:** Show only what the record shows: derived step boundaries would be guesses.
- **Status:** Open for the owner (contract change in docs/SPEC.md).

### Q16 · Learning effect: causality
- **Question:** Do we claim a learning "fixed" something?
- **Recommendation:** Never. Provenance trace and Metrics show before/after with n, "n < 5: too few to compare", no color judgement, and the fixed footer "Correlation, not proof." listing other changes in the window.
- **Alternative:** A "learning impact score".
- **Why:** Calibrated trust; a score would be over-read.
- **Status:** Decided in this design.

### Q17 · Budget overrun shown in the UI
- **Question:** A run can exceed its budget before the executor stops it (LOK-298: $14.62 of $10.00).
- **Recommendation:** `BudgetBar` amber at 80 %, red at 100 %, and beyond 100 % the bar stays full with an overflow notch and text "$14.62 of $10.00 (+46 %)". The projection line ("At this rate, budget reached in ~6 min") appears from 50 %. The run's failure banner states "Stopped at budget". Whether the executor hard-stops or lets the current turn finish is shown as "Stopped after the current turn".
- **Alternative:** Hide overrun amounts.
- **Why:** Show deviation from normal (Endsley); honest numbers.
- **Status:** Open for the owner: hard stop vs finish turn.
