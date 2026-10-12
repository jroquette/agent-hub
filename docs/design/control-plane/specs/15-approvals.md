# Approvals

**Phase:** P2 read-only (decisions P4 tagged inline) · **Route:** `/approvals`, `/approvals/{approval_id}` · **Answers:** "What is waiting for me to decide, and what happens if I say yes?"

## Purpose and primary user

The owner / tech lead's inbox of everything an agent cannot pass without a person: open `gate.request` events (plan approval, spec approval, human gates in a workflow) and guard "ask" requests (an agent wants to edit a path listed in `hub.json` → `guard.ask_before_edit`, such as `docs/adr/`). Principle 2 (human decides) lives here.

In P2 the app does not decide anything: it shows the material in full and tells the owner exactly where and how to decide in the terminal session that is waiting. In P4 the decision buttons arrive here.

The sidebar item "Approvals" carries a count badge (`waiting` ground) fed by the global SSE stream; the same items appear first in Portfolio "Needs you".

## Layout (1440 px)

```
+--------+-------------------------------------------------------------------------------------------------+
|Sidebar | TopBar: [All projects v]  [Search or jump to... Ctrl K]   (o Connected · last event 3 s ago)    |
|Approvals(3)+---------------------------------------------------------------------------------------------+
|        | Approvals                                                     [Open 3 | Decided (30 d)]          |
|        | 3 waiting · oldest 2 h 14 min                       Kind [All v]  Project [All v]               |
|        +------------------------------------------+-------------------------------------------------------+
|        | INBOX LIST (flex, min 480)               | DETAIL PANEL (panel = 480 px; 640 px at >= 1600)      |
|        |                                          |                                                       |
|        | > [Plan] Approve plan for AGH-48         | Approve plan for AGH-48 Layered memory     [Plan]     |
|        |   agent-hub · hub-workflow:planner       | agent-hub · requested by hub-workflow:planner         |
|        |   in session 5f21c0aa · waiting 2 h 14 min| in session 5f21c0aa · run 01922b10 · human gate      |
|        |                                          | waiting since 09:05 (2 h 14 min)                      |
|        |   [Guard ask] Edit under docs/adr/       | ----------------------------------------------------- |
|        |   agent-hub · main · AGH-112             | WHAT CHANGES IF I APPROVE                             |
|        |   docs/adr/0012-tracker-team-cap.md      |  - The run continues to Implement (step 4 of 8).      |
|        |   waiting 6 min                          |  - Agents will change 14 files in agent-hub           |
|        |                                          |    (9 new, 5 changed), per the plan's file list.      |
|        |   [Spec] Approve spec for LOK-311        |  - Budget committed: up to $10.00 (cap), $0.84 spent. |
|        |   loki-trader · requirements-analyst     |  - Nothing is pushed or merged: a PR comes later.     |
|        |   waiting 41 min                         | ----------------------------------------------------- |
|        |                                          | P2: HOW TO DECIDE (read-only here)                    |
|        |                                          |  Approve in the terminal session 5f21c0aa.            |
|        |                                          |  [Copy] cd ~/code/agent-hub-hub && claude --resume    |
|        |                                          |         5f21c0aa                                      |
|        |                                          |  Then answer the prompt "Approve this plan?" with     |
|        |                                          |  approve, or request changes in your own words.       |
|        |                                          | ----------------------------------------------------- |
|        |                                          | PLAN  (brain/features/layered-memory/plan.md)  [TOC]  |
|        |                                          |  ## Goal ...                                          |
|        |                                          |  ## Acceptance criteria                               |
|        |                                          |  | AC      | Description            | Repo | Verify |  |
|        |                                          |  | AC-48.1 | Given a hub with ...   | a-h  | make…  |  |
|        |                                          |  ...                                                  |
|        |                                          | ----------------------------------------------------- |
|        |                                          | P4 ACTION BAR (sticky bottom of panel)                |
|        |                                          | [Approve plan] [Request changes] [Reject]             |
+--------+------------------------------------------+-------------------------------------------------------+
```

Regions: header with `SegmentedControl` (Open / Decided), filters; inbox list (left); `ApprovalPanel` (right, `panel` token width, sticky header, scrollable body, sticky action bar in P4). Selecting an item updates the URL to `/approvals/{id}`; on first load with no id, the oldest open item is selected.

## Components

| Component | Variant / notes |
|---|---|
| `AppShell`, `Sidebar` (Approvals badge "3"), `TopBar`, `ProjectSwitcher`, `CollectorPill` | Standard |
| `SegmentedControl` | Open / Decided (30 d) |
| `DataTable` (list variant, no header) or plain list | Rows 64 px, two lines; selected row `accent-soft` |
| `StatusBadge` | waiting (open), done (approved), failed (rejected), idle (withdrawn: session ended before a decision) |
| `StageChip` (kind variant) | Kind labels: Plan, Spec, Human gate, Guard ask |
| `ApprovalPanel` | Header, "What changes if I approve", "How to decide" (P2), material, action bar (P4) |
| `Markdown` with `AcTable` | Rendered plan/spec; AC table with ids, Given/When/Then, repo, verification command |
| `DerivedLabel` | On "What changes if I approve" ("Derived from the plan and run caps") |
| `ProvenanceBadge` | On the material: provenance `agent` (planner) |
| `CodeBlock` | The exact terminal command, copy button |
| `DiffViewer` | For guard "ask" and spec diffs: the proposed edit (summary + inline diff) |
| `IdChip`, `IssueLink`, `Time`, `Money`, `PathText` | Content rules |
| `Button` | P4 "Approve plan" (primary), "Request changes" (secondary), "Reject" (danger-secondary) |
| `ConfirmDialog` | P4 Reject, and Approve on guard ask for protected paths |
| `Toast` | P4 result of the owner's own decision only |
| `Skeleton`, `EmptyState`, `ProblemError`, `AsOfStamp` | States |

## Inbox list: row content

Line 1: kind chip, verb phrase in `body-strong` ("Approve plan for AGH-48", "Allow edit under docs/adr/", "Approve spec for LOK-311", "Pass human gate 'Owner check' for AGH-112").
Line 2 (`small`, `text-muted`): project · requested by (agent id or "main" session) · issue · "waiting 2 h 14 min".
Right edge: waiting age as a figure, amber (`waiting`) after 1 h, never red (waiting is not failure).

Sort: oldest first (the one blocking longest). Group headers only when scope is All projects and more than 6 items: by project.

Sample inbox (synthetic, brief §10). Sample time: the inbox is shown as of 08 Oct 11:19, the moment before the AGH-48 plan was approved (flow 5); in the rest of the sample data AGH-48 is already REPORTED, with the plan approved at 11:22.

| Kind | Verb phrase | Project · requested by · issue | Waiting since |
|---|---|---|---|
| Plan | Approve plan for AGH-48 | agent-hub · hub-workflow:planner · AGH-48 (run 01922b10) | 09:05 |
| Spec | Approve spec for LOK-311 | loki-trader · hub-workflow:requirements-analyst · LOK-311 | 10:38 |
| Guard ask | Allow edit under docs/adr/ | agent-hub · main (session 7d93a2e4) · AGH-112 | 11:13 |

## Detail panel: plan approval for AGH-48

**Header.** "Approve plan for AGH-48 Layered memory" (subheading), kind chip, project, "requested by hub-workflow:planner in session 5f21c0aa" (session id links to the session timeline at the `gate.request` event), run link (`01922b10`, step "plan approval", attempt 1), "waiting since 09:05 (2 h 14 min)".

**What changes if I approve** (always above the material; `DerivedLabel` "Derived from the plan and the run's caps"):
- "The run continues to Implement (step 4 of 8 in feature rev 2)."
- "Agents will change 14 files in agent-hub (9 new, 5 changed), per the plan's file list." Expand to see the list with `PathText`.
- "Budget committed: up to $10.00 (cap). Spent so far: $0.84."
- "21 acceptance criteria become the definition of done (AC-48.1 to AC-48.21). 1 is a manual owner step (AC-48.21)."
- "Nothing is pushed or merged now. A PR is opened after Verify, and you merge it."
- If rejected instead: "The run stops at plan approval and the issue gets the label agent-failed with your reason."

**How to decide (P2 only).** A bordered box (`border-strong`, `surface-sunken`):

> **Approve in the terminal session**
> This app is read-only in this version. The session that asked is waiting at its prompt.
> 1. Open a terminal on the machine where it runs and resume it:
>    `cd ~/code/agent-hub-hub && claude --resume 5f21c0aa`
>    (If the terminal is still open, switch to it: its title shows "agent-hub-hub · /feature AGH-48".)
> 2. Answer the question "Approve this plan?" with `approve`, or describe the changes you want.
> 3. This item moves to Decided within a few seconds of your answer.

The command is built from the hub path (`GET /hubs`) and the session id; `[Copy]` copies only the command line. If the session is no longer running (no activity and `session.end` received), the box changes to: "Session 5f21c0aa ended without a decision. Restart the step from the terminal: `cd ~/code/agent-hub-hub && claude "/feature AGH-48 --resume-at plan-approval"` (proposed CLI)."

**Material.** The rendered `plan.md` with a sticky mini TOC (Goal, Approach, Files, Acceptance criteria, Risks, Out of scope). The AC table (`AcTable`, from `spec.md` ACs joined with `features.json`):

| AC | Description | Repo | Verification command |
|---|---|---|---|
| AC-48.1 | Given a hub with `brain/auto/workspace/`, when `hub sync` runs, then the folder is gitignored | agent-hub | `uv run pytest packages/generator/tests/unit/test_gitignore.py -k workspace` |
| AC-48.2 | Given a personal note, when the brief is built, then it is read only for its owner | agent-hub | `uv run pytest -k personal_memory_brief` |
| … | (19 more) | | |
| AC-48.21 | Given the feature is merged, when the owner opens a new session, then the layered memory loads (manual owner step) | agent-hub | manual: see eval.md "Owner steps" |

Commands are mono and copyable; descriptions are truncated to 2 lines with expand. A footer link "Open feature record" goes to `/features/agent-hub/layered-memory`.

## Detail panel: guard "ask" on a protected path

The guard hook asks before an agent edits any path in `hub.json` → `guard.ask_before_edit` (sample: `docs/adr/`). In Claude Code this is a permission prompt in the terminal; the app mirrors it.

```
| Allow edit under docs/adr/                                   [Guard ask]     |
| agent-hub · main session 7d93a2e4 · AGH-112 · waiting 6 min                  |
|------------------------------------------------------------------------------|
| WHY THIS ASKS                                                                |
|  docs/adr/ is listed in hub.json guard.ask_before_edit. Accepted ADRs are    |
|  never edited; a new ADR supersedes them.                                    |
| WHAT CHANGES IF I ALLOW                                                      |
|  - Creates docs/adr/0012-tracker-team-cap.md (+48 -0). New file: no         |
|    existing ADR is modified.                                                 |
|  - Allows this one edit only. Later edits under docs/adr/ ask again.         |
| PROPOSED EDIT                                     [Unified | Split]          |
|  + # 0012 Cap the tracker team list                                          |
|  + Status: proposed ...                                                      |
| HOW TO DECIDE (P2)                                                           |
|  Answer the permission prompt in the terminal running session 7d93a2e4:      |
|  choose "Yes" to allow this edit or "No" and say why.                        |
```

If the edit modifies an existing accepted ADR (not a new file), the "What changes" list leads with a `failed`-colored line: "Edits accepted ADR 0007. Project rule: accepted ADRs are never edited; supersede with a new ADR instead." This is the only case where the panel shows a red line: it flags a rule conflict, not a failure.

The proposed edit comes from the `gate.request` payload (tool input of the pending Edit/Write). Content is redacted before storage; a secret inside the diff renders as a `RedactionChip` (`[redacted: api key]`) with no reveal.

## Data mapping

| Element | Entity.field (brief §3) | API resource | Source · latency |
|---|---|---|---|
| List rows | open gate.request events not yet matched by gate.result | `GET /approvals?scope=&status=open` → `items[]` `{id, kind, project, issue_key, requested_by, session_id, run_id, step, created_at}` | claude_code hooks · real time |
| Badge count | count of open approvals | `GET /events/stream` → `approvals.count` | real time |
| Kind | gate.request payload.kind (plan, spec, human_gate, guard_ask) | `items[].kind` | hooks / executor |
| Verb phrase | derived from kind + issue / path | `items[].title` (server-built, final copy) | derived |
| Waiting since | gate.request timestamp | `items[].created_at` | hooks |
| Material (plan/spec) | Feature record files `plan.md`, `spec.md` | `GET /approvals/{id}` → `material.{path, markdown, commit}` | hub files · on open |
| AC table | features.json ACs (id, description, repo, verification command) | `material.acs[]` (joined server-side with `GET /features/{project}/{slug}`) | hub files |
| What changes if I approve | derived: next step, plan file list, caps, ACs | `GET /approvals/{id}` → `consequences[]` (strings + structured fields) | derived server-side |
| Budget lines | WorkflowRun.caps.budget, total cost | `consequences.budget_usd`, `consequences.spent_usd` | executor + otel |
| Guard ask diff | gate.request payload tool input (redacted) | `material.diff` `{path, change: create|modify, unified}` | hooks |
| Terminal command | Hub path + session id | `how_to_decide.{command, session_alive}` built from `GET /hubs` path | derived |
| Decided tab | gate.result events | `GET /approvals?status=decided&period=30d` → `{decision, decided_by, decided_at, where: terminal|app, comment}` | hooks / app |
| P4 decision | gate.result written by the app | `POST /approvals/{id}/decision` `{"decision":"approve|request_changes|reject","comment"}` | app → hook relay |

## Interactions

- `j` / `k` move through the list; the panel follows. `Enter` focuses the panel. `Esc` returns focus to the list.
- `o` opens the requesting session at the gate.request moment; `i` opens the issue.
- Copy button on the terminal command; `Kbd` hint "c" copies when the panel has focus.
- The material's TOC is sticky inside the panel; clicking a heading scrolls the panel only.
- Deep link `/approvals/{id}#acceptance-criteria` opens with the AC table in view.
- New requests arrive via SSE: they insert at the right position with a 150 ms fade (`dur-base`); the selected item never changes on its own. A polite live region announces at most once every 30 s: "1 new approval: Allow edit under docs/adr/."
- When an open item is decided in the terminal, its row animates to Decided (fade out) and the panel shows: "Approved in the terminal by José Henrique Roquette at 11:22. The run moved to Implement." with a link to the run.
- P4 keyboard (when the panel has focus): `a` Approve, `r` Request changes, `x` Reject. Each opens its form; none acts in one keystroke.

## Actions by phase

| Action | Phase | Confirmation? | Consequence |
|---|---|---|---|
| Read material, copy command, open session/issue | P2 | No | None |
| Approve plan / spec / human gate | P4 | No dialog; button shows "Approving…" then result. Undo is not offered (see why). The button is disabled for 1 s after the panel opens so a stray Enter cannot approve unread material | `POST /approvals/{id}/decision` `{"decision":"approve"}`; the waiting session receives the gate.result and continues (run moves to Implement live) |
| Allow guard edit on a new file | P4 | No | Allows one Edit/Write; the hook re-asks on the next one |
| Allow guard edit that modifies an accepted ADR or any existing file under a protected path | P4 | Yes, `ConfirmDialog` | Allows overwriting protected content; the dialog says which rule it bypasses |
| Request changes | P4 | Comment required (min 10 chars), no dialog | Sends the comment to the session as the gate answer; the agent revises and asks again (new approval item, linked "revision 2") |
| Reject | P4 | Yes, `ConfirmDialog`, reason required | Run stops; `agent-failed` label and the reason posted to the issue; cannot be resumed from this gate |

Why approve has no dialog: approving continues reversible work (nothing is pushed or merged before the owner merges the PR); the "What changes" summary is the confirmation, shown before the button. Reject and protected-path overwrite end work or bypass a rule, so they confirm. This keeps confirmations rare enough to be read (alarm and confirmation fatigue).

**Request changes form** (inline, replaces the action bar):
- Label: "What should change?" Placeholder: "e.g. Split AC-48.12 into two criteria; add a test for the missing .gitkeep."
- Helper: "Your comment goes to the planner in session 5f21c0aa. It will revise the plan and ask again."
- Buttons: "Send request" (disabled until 10 chars) / "Cancel".

**Reject dialog:**
- Title: "Reject the plan for AGH-48?"
- Body: "The run 01922b10 stops at plan approval. AGH-48 gets the label agent-failed and your reason as a comment. To try again, start a new run."
- Field: "Reason (posted to AGH-48)" required.
- Buttons: "Reject plan" (danger) / "Keep waiting".

**Protected-path dialog (guard):**
- Title: "Allow editing an accepted ADR?"
- Body: "docs/adr/0007-composition-root.md is an accepted ADR. Project rule: accepted ADRs are never edited; a new ADR supersedes them. Allow this one edit anyway?"
- Buttons: "Allow this edit" / "Deny".

After a P4 decision, a `Toast` (the owner's own action): "Plan for AGH-48 approved. Run 01922b10 is implementing." with link "Open run".

## States

| State | What shows | Exact copy |
|---|---|---|
| Loading (>300 ms) | 3 skeleton rows + panel skeleton (title bar, 6 text lines) | (none) |
| Empty (open) | `EmptyState` in the list area; panel hidden | "Nothing waits for you." / "Plan approvals, human gates and guard requests appear here when an agent asks. 3 sessions are running." (count live; if 0: "No session is running.") |
| Empty (decided) | Inline | "No decisions in the last 30 days." |
| Material missing | Panel shows the header and "What changes", material area replaced | "The plan file brain/features/layered-memory/plan.md was not found at commit 4e1a9c2. The agent may not have written it yet." |
| Session gone | How-to-decide box variant; item status `idle` "Withdrawn" | "Session 5f21c0aa ended without a decision." + restart command (see above) |
| Partial: tracker down | Issue title from cache with `AsOfStamp` | "Issue title as of 08:55 (Linear not reachable)." |
| Error | `ProblemError` in the panel, list stays usable | e.g. "Could not load this approval" / "status 404 · Approval 0192… not found. It may have been decided." [Back to inbox] |
| P4 decision failed | Inline error under the action bar; buttons re-enabled | "Your approval was not delivered: the session is not reachable (status 409). Approve in the terminal instead:" + command |
| Live | New items fade in; waiting ages tick each minute | (see Interactions) |
| Stale | `AsOfStamp` in header; badge shows last known count with a clock icon | "As of 14:02 · collector offline. New requests will not appear until it reconnects." |

## Mobile glance layout (<= 640 px)

Approvals is a glance screen. Purpose on a phone: know what is waiting and read the "What changes" summary; deciding is a desktop or terminal act in P2 and, in P4, approve and request changes are allowed on mobile but reject is not.

```
+------------------------------+
| Approvals            3       |
|------------------------------|
| [Plan] Approve plan for      |
| AGH-48 · agent-hub           |
| waiting 2 h 14 min        >  |
|------------------------------|
| [Guard ask] Allow edit under |
| docs/adr/ · AGH-112          |
| waiting 6 min             >  |
|------------------------------|
| [Spec] Approve spec for      |
| LOK-311 · loki-trader        |
| waiting 41 min            >  |
+------------------------------+
  tap -> full-screen detail:
+------------------------------+
| < Approvals                  |
| Approve plan for AGH-48      |
| planner · waiting 2 h 14 min |
| What changes if I approve    |
|  - Continues to Implement    |
|  - 14 files in agent-hub     |
|  - Up to $10.00 ($0.84 spent)|
|  - 21 ACs, 1 owner step      |
| [Read the plan (21 ACs)]     |
| Decide in the terminal:      |
| claude --resume 5f21c0aa [c] |
|------------------------------|
| P4: [Approve plan] [Changes] |
+------------------------------+
```

Rows are 72 px (targets well above 24×24). The plan opens as a full-screen reader with the TOC in a bottom sheet. No AC table columns beyond id + description; verification commands are hidden on mobile ("Open on desktop to see verification commands").

## UX principles applied

| Choice | Principle (brief §7) |
|---|---|
| "What changes if I approve" above the material and the buttons | Calibrated trust (Lee & See): consequences visible before the decision; Endsley projection |
| Oldest first; amber age, never red | Endsley perception of what blocks longest; red reserved for failure (pre-attentive meaning stays stable) |
| P2 guidance with the exact command and where to type | Nielsen help and documentation; recognition over recall |
| Confirm only reject and protected-path overwrite | Optimistic UI only for reversible actions; confirmation fatigue |
| Request changes needs a comment | Human decides, and the agent needs actionable input; error prevention (Nielsen) |
| Approve disabled 1 s after opening | Error prevention; Fitts (prevents accidental activation on panel open) |
| No toast for new requests, polite live region rate-limited to 30 s | Alarm fatigue (Sendelbach & Funk); WCAG polite live regions |
| AC table with copyable commands | Explainability: the owner sees how each criterion will be verified |

## Responsive

- **1280×800:** sidebar collapsed; list 400 px, panel takes the rest (about 820 px); the AC table hides the Repo column (shown in the row expansion).
- **1920:** panel 640 px; the plan's TOC shows as a left rail inside the panel.
- **Mobile:** glance layout above.
