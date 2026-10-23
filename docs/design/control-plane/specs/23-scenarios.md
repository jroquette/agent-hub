# Scenarios, scenario detail and scenario run

**Phase:** P2 with local writes (plan, start, the investigation session, the answer and the finding actions are strict
writes, [ADR 0040](../../../adr/0040-hub-web-keeps-local-settings-writes-hub-files-and-runs-checks.md)) ·
**Routes:** `/scenarios`, `/scenarios/:project/:name` (a scenario's name is unique per project only),
`/scenarios/:project/:name/runs/:runId` · **Answers:** "What will this scenario do in this environment, may it start,
and when a scenario run stops, what do I decide?"

The contract is [scenarios.md](../../scenarios.md); the decision is
[ADR 0041](../../../adr/0041-scenarios-actions-and-enforced-access.md). Glossary: a **scenario run** is a WorkflowRun of a
scenario; the UI always says "scenario run", and "run" alone means a workflow run.

## Navigation

- Sidebar, **Work** group: Sessions, Workflow runs, **Scenarios** (`clipboard-list`), Features (right after
  Workflow runs, since AGH-382 removed Workflows). Always shown: a place to start work, not a log. No badge; no `g`
  shortcut; the command palette lists it under Screens, and lists a scenario run found by search as "Scenario run
  <id>" in its own group.
- Breadcrumbs: Portfolio › project › Scenarios › name › Scenario run `<id>`.
- `/runs/:runId` of a scenario run redirects (`replace`) to its scenario run page. `/runs` lists workflow runs only
  (`kind=workflow`).
- View state in the URL: `?q=` (list filter, `replace`), `?env=` (detail: pre-fills the environment; the plan never runs
  on load), `?option=` and `?event=` (run page selection, `replace`).

---

## Screen 1: Scenarios (`/scenarios`)

**Answers:** "Which scenarios does my hub hold, and did their last scenario run pass, fail or wait for me?"

```
Scenarios                                                              [As of 14:02]
Flows your hub drives in a declared environment, step by step. Plan one to see what it will
do before anything runs.
6 scenarios in 2 packs · 1 scenario run waits for you
+-- Waiting for you ---------------------------------------------------------------------+
| (hand) order-lifecycle · scenario run 3f2a91c0 waits for you since 10:42  [Open …]     |
+----------------------------------------------------------------------------------------+
[/ Filter scenarios by name or description]
Scenario                               Pack       Steps   Last scenario run
order-lifecycle                        orders         9   (hand) Waiting for you · 10:42
  One order from fetch to an active cover                 3f2a91c0
stock-sync                             payments       3   Never run
Files that do not load (1)
scenarios/orders/returns.yaml:14   nodes[2].type   shell nodes are not allowed in a scenario
```

- **Data:** `GET /api/v1/scenarios?project=`; waiting from open human gates on `run:<id>` (as Run detail's
  `OpenGates`).
- **Table:** compact `DataTable`; Last scenario run is a `StatusBadge` (Waiting for you, Running, Done, Failed,
  Cancelled) + time + the short id as a link. Column priority: Scenario, Last scenario run, Steps, Pack, Project
  (only with several projects). Not built yet (AGH-458): the `IdChip` (copy the full id) and the badge's "since" time
  ("Waiting for you since 10:42").
- **Keys:** `/` focuses the filter. Not built yet (AGH-458): the rows' `j`/`k` and `Enter`/`o`.

| State | Copy |
|---|---|
| Empty | "No scenarios yet." / "Scenarios are YAML files in the hub's scenarios/<pack>/ folder, and the actions they call are in actions/<pack>/. Add one, then check that it loads from a terminal:" `./hub scenario list` |
| Only problems | "No scenario loads." / "Fix the files below; this page reads them again on every visit." |
| No match | "No scenarios match "refnd"." [Clear filter] |
| Error | `ProblemError` "Could not load scenarios" + detail + Retry |
| Stale | "As of 14:02" |

## Screen 2: Scenario detail (`/scenarios/:project/:name`)

**Answers:** "What will this scenario do in this environment, step by step, and may it start?" The primary action is
"Plan in <environment>", then "Start scenario run".

```
Portfolio › demo › Scenarios › order-lifecycle
order-lifecycle   pack orders · revision 1                                   [Discuss]
+-- Plan ------------------------------------------------------------------------------+
| Environment [personal]  external_ref [T-1]                         [Plan in personal] |
| Plans run each action's script in plan mode, with no credential. Nothing acts on the |
| system.                                                                               |
| personal · access write        Planned 14:03 · 4 steps: 2 read, 2 write · 1 asks you  |
| Step           Action              Effect  Service → endpoint          Policy          |
|   Values                                   What it will do                             |
| fetch-order    send-queue-message  write   queue → queue.example.com…  (v) Allow       |
| render-pdf     render-invoice-pdf  write   files → demo-invoices       (o) Denied      |
|   <$CTX.order_id from order-on-hold>       Runs with values known at run time         |
|   Draft: needs acceptance. Commit it in the hub checkout, then plan again:            |
|   git add -- actions/orders/render-invoice-pdf.yaml … && git commit -m '…'   [Copy]   |
| (o) Cannot start: render-pdf is denied in personal.                                   |
| Mode (•) Interactive ( ) Regression                      [Start scenario run] (off)   |
+---------------------------------------------------------------------------------------+
Step by step (numbered, step-kind icons)        Scenario runs (12): id · status · started
```

The step list and the Scenario runs card stack below 1600 px, so the Started column stays in view. Not built yet
(AGH-458): the Scenario runs table's keys (`j`/`k`, `Enter`/`o`).

- **Plan:** `POST …/plan` on the person's click only. Rows: step, action, effect (icon + label), service → endpoint
  (`PathText`), values (run-time ones as `<$CTX.<name> from <node>>`), the script's plan-mode summary, the policy
  (Allow, Asks you (neutral until a gate waits), Denied + the reason in words). A draft row shows "Draft: needs
  acceptance" and the exact `accept_command`; nothing commits from hub web.
- **Start:** enabled only on a current plan with no deny and no problem; a confirm dialog names the environment, the
  writes and the asks ("Start a scenario run in personal?", buttons "Start scenario run" / "Back to plan"). After 202,
  the page waits for the scenario run's first event, then opens it.
- **Mode:** Interactive (the default) "If a step does not reach its expected state, the scenario run pauses
  and a read-only agent investigates with you." · Regression "No agent and no token cost. The first step that does not
  reach its expected state fails the scenario run." · both: "Steps that ask still pause for your approval."
- **Environment field:** a select of the project's declared environments (`ScenarioDetail.environments`:
  "personal · access write"); when they cannot be read, a text field with this browser's recent environments.
- **Content hash:** a tooltip on the step ("Pinned when the scenario run starts: sha256:…").

| State | Copy |
|---|---|
| No plan | "Plan the scenario to see what each step will do in an environment." |
| Planning | "Planning in personal… each step's script runs in plan mode." · after 10 s "Still planning. A plan stops after 5 min." |
| Can start | "Can start in personal." (+ "1 step asks you before it runs.") |
| Denied | "Cannot start: fetch-order and resolve-cover are denied in qa." |
| Stale plan | "This plan is for personal with external_ref T-1. Plan again to start with the new values." |
| Production | "live is a production environment: writes and destroys are denied there." |
| Undeclared | "Environment qa is not declared in this hub. Declare it in hub.json, or in hub.local.json for yourself:" `./hub env add qa --access read` |
| `hub.local.json` invalid | "hub.local.json cannot be read or conflicts with hub.json, so the environments are unknown. Run ./hub doctor to see the problem, fix the file, then plan again." |
| Plan timeout (502) | "The plan did not finish in 5 min, so it was stopped. A plan-mode script may hang: run it from a terminal to see which." |
| Locked (401) | "Planning is locked in this browser. Open the link hub web printed when it started (it ends with ?token=…) once in this browser." |
| Container (404 `run-control-off`) | "Plans and scenario runs cannot start from the agent-hub container: it has no credentials and no env files. Run hub web on your machine, or plan from a terminal:" |
| Start refused (409) | "Could not start the scenario run" / the server's detail (steps named) / "Nothing was started." |
| Not found | "Scenario order-lifecycle not found" / "Project demo has no scenario order-lifecycle that loads. It may have been renamed, or its file may not load." |
| No scenario runs | "No scenario runs yet." / "Start one from the plan above." |

### Departures (AGH-521, storyline and live run)

The owner validated these in the playground (snapshot `20261023T210306Z`); where the section above says otherwise, this
wins.

- **AC-521.11.1 Step keys, file and actions.** Given `GET /api/v1/scenarios/{project}/{name}`, then each step carries
  its `with`, `capture`, `every`, `timeout`, `until_when` and `retry`, and the detail carries the scenario's `path`,
  its YAML and the actions its steps call, each with its effect, runtime, inputs, script and draft state
  ([API.md](../../../API.md#scenarios)).
- **AC-521.11.2 Storyline.** Given the scenario page, then its steps read as a numbered storyline of cards before any
  plan: each step in words with its action, the values it passes, what it keeps for later and where it stops; an
  `expect` step words its wait (every, until, timeout) and its stop changes with the mode (Interactive pauses,
  Regression fails). The plan's facts (effect, endpoint, policy, a draft's commit line) land in the step's own card.
- **AC-521.11.3 Run panel beside the steps.** Given a wide screen, then the plan, mode and start controls sit in a run
  panel beside the storyline; an action's name opens a panel with its description, effect, inputs and script, and
  the scenario's file opens as text.
- **AC-521.11.4 Live run.** Given a scenario run of this scenario that is running, then the page follows it: a banner
  says it is running in its environment, links to the scenario run and offers Cancel (the run page's own command),
  and each step's card shows its status in that run as it moves (Done, "Running · check 3", Not started).

## Screen 3: Scenario run (`/scenarios/:project/:name/runs/:runId`)

**Answers:** "Where did this scenario run get to, why did it stop, and what do I decide now?"

```
Scenario run 3f2a91c0  (hand) Waiting for you   order-lifecycle · personal · Interactive
Started 22 Oct 10:31 · 11 min · investigation 1 of at most 10
(hand) Paused at order-processed: it did not reach its expected state before its timeout
       (40 polls in 10 min). Steps that did not depend on it have run.
       Decide below: pick an option, retry the step, or stop the scenario run.
+-- Investigation chat ------------------+-- Options from the agent (proposal 2) ------+
| Investigation 1 · read-only agent      | ( ) o1 … plan: step · effect · where · policy|
| What the agent can do (folded list)    | (•) o2 … plan                                 |
| [DiscussChat]                          | (x) o3 … Cannot be picked: step 1 (…): draft  |
|                                        |     action: commit it to run. [Check again]   |
|                                        | [Pick option o2] [Retry order-processed]      |
|                                        | [Stop scenario run]                           |
|                                        | Findings (2): [Draft tracker issue] [Write    |
|                                        | inbox note]                                   |
+----------------------------------------+-----------------------------------------------+
Timeline (TimelineEvent rows): started · steps · polls · captures · gates and answers ·
investigation · investigation reads · proposals · workarounds · end      | Scenario run facts
```

- **On load while paused** the page calls `POST /scenario-runs/{id}/investigation` (one session per investigation;
  a second call returns it) and mounts `DiscussChat` with its permission cards: each allowed file write and `./hub`
  command still asks the developer.
- **Limits, stated beside the chat:** "Read the hub and its declared repos." · "Run read actions in personal." · "Write
  draft actions in actions/orders/." · "It cannot run writes or destroys, read env files, or reach other folders." ·
  "Each file write and ./hub command it is allowed still asks you here." · "These limits hold its tools; they are not a
  sandbox."
- **Options:** a radiogroup (`OptionRow`, a `disabled` prop added), each option with its plan; a refused option is
  disabled with "Cannot be picked: …" (the server's reason). The answer goes to `POST /scenario-runs/{id}/answer`
  after a confirm dialog:
  - Pick: "Pick option o2 and run it in personal?" "… Picking it is your approval of that step. Then order-processed
    runs again. Nothing is rewound."
  - Retry: "Retry order-processed in personal?"
  - Stop: "Stop this scenario run?" "It ends cancelled. Its findings are kept, nothing is rewound, and it cannot be
    resumed."
  A 409 pick refusal shows its reason and "Nothing was recorded."
- **Policy asks** (`<step>__ask`): the Waiting for you card (`OpenGates` + `GateDecision`, approve or reject) shows
  every open gate of the scenario run except the investigation gate (known from the record, never the id suffix):
  "<gate> waits for your approval since 10:32. Reject cancels the scenario run."
- **Findings:** "Draft tracker issue" opens the draft in a dialog, "Create issue in DEMO" creates it once. A failed or
  unfinished create says: "The issue may already exist in the tracker. The create failed or did not finish, so it is
  not retried here. Check DEMO first. To try again, run in a terminal:" `./hub scenario findings 3f2a91c0 --issue f1`.
  "Write inbox note" writes `brain/_inbox/<date>-scenario-<name>-<finding>.md` once, never over a note.
- **Timeline:** `TimelineEvent` rows; a click selects a row (`?event=`, replace). A captured `<credential NAME>`
  shows as a `RedactionChip`. Not built yet (AGH-458): the timeline keys `j`/`k`, `Enter`, `c`, and "Show all N
  polls" (a row lists its last 20 polls).
- **After an answer:** a toast ("Answer recorded: option o2 picked."), the resuming line in place of the pause banner
  until the record moves on, and focus on the page's heading once the paused view goes.

| State | Copy |
|---|---|
| Running | live badge; "Cancel scenario run" while not paused (Cancel only: no resume or abandon here) |
| No options yet | "No options yet. The agent is investigating; its findings and options appear here when it records them." |
| Answered | "Answer recorded: option o2 picked. The scenario run resumes; its events update this page." |
| Done | "Done at 10:58 · 9 steps · 1 workaround" |
| Failed (regression) | "Failed at order-processed: … Regression mode: no investigation." |
| Failed (limit) | "… The investigation limit is reached (10 of 10)." |
| Cancelled | "Stopped at 10:52 by Dana Demo in hub web. Findings are kept; nothing was rewound." |
| Session cannot reopen (409) | "The investigation session cannot be reopened with its limits, so it stays closed." |
| Workspace root (409) | "No investigation session: the hub or a declared repo sits at / or your home folder, where its reads would reach your own credentials. Move it into a folder of its own." |
| Container (404 `run-control-off`) | "This scenario run cannot be answered from the agent-hub container" / "Run hub web on your machine to talk with the agent and decide, or answer from a terminal:" `./hub workflow respond 3f2a91c0 --node order-processed__investigation --choice retry` |
| Record too large (422) | "This scenario run's record is too large to read here" / "hub web reads records up to 8 MiB. List its findings from a terminal:" `./hub scenario findings 3f2a91c0` |
| Not found | "Scenario run 3f2a91c0 not found" / "No scenario run has the id 3f2a91c0 in the registered hubs. It may belong to a hub that is no longer registered." |

## Responsive

Built: at 1280 and wider nothing hides (the plan tables' cells wrap, so Step and Policy stay in view), the chat and
the options sit side by side, and the step list and the scenario runs stack when they do not fit side by side. On a
tablet (768–1279) the detail plans but its start bar says "Starting a scenario run needs a desktop screen."

Not built yet (AGH-458), the target:

| Width | Scenarios | Detail | Scenario run |
|---|---|---|---|
| ≥ 1600 | as drawn | as drawn | chat 1fr, options 560 |
| 1280–1599 | all columns | the start bar is sticky in the plan card; the Scenario runs table's Duration column and "Show all 12" | chat ≥ 480, options 440; facts fold under the timeline |
| 768–1279 | Pack hides | columns by priority | options first; the chat opens in a `SidePanel` |
| < 768 | "This view needs a wider screen." | same | same |

## Accessibility

Each table has a caption that names its subject. Every status and decision is icon + label. A refused option's reason
is linked by `aria-describedby`. The verdict, the pause, the answer and the end are announced once, politely. Dialogs
open on their safe button and return focus. axe has no serious or critical violation (`npm test -- -t a11y`).

## UX principles applied

Human decides (principle 2): the pause and the answer bar sit above the fold, waiting amber, and every write is
confirmed with its environment. Show only what the record shows (principle 3): run-time values stay placeholders, and
a gate's kind comes from the record. Privacy (principle 5): credential marks are `RedactionChip`s. Honest limits: the
agent's limits sit beside its chat, and the best-effort sentence sits on Run detail. Plain language: each line names
the step, the environment and the reason.

## Decisions (AGH-364)

- The investigation chat is `DiscussChat` with its permission-mode switch hidden: the session stays in mode
  `default`, so each allowed file write and `./hub` command keeps asking. The top bar's Discuss is hidden on a
  scenario run's page, which has its own chat.
- A gate's kind (policy ask or investigation) comes from the run's own record: `GET /approvals` names it
  (`gate_kind`), and the scenario run's record names its investigations' gates. A gate is never classified by its id.
- An investigation read in the timeline names its action and effect; each action call's policy facts (effect,
  origin, decision, content hash) come from the record view's `actions`; each investigation names its session.
- A tablet gets the plan only; starting a scenario run needs a desktop screen.
- `/runs/:runId` of a scenario run redirects (`replace`) to its scenario run page; project overview's Work in flight
  and the command palette call it "Scenario run <id>", never "Run <id>".
- Product principle 1 ("no chat anywhere") predates ADR 0031/0033; its wording is updated through an ADR in a separate
  issue.
