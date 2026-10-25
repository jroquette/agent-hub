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

- Sidebar, **Work** group: Features, Tickets, **Scenarios** (`clipboard-list`), Sessions, Workflow runs,
  Environments (AC-521.4.1). Always shown: a place to start work, not a log. No badge; no `g`
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

### New scenario with Claude (AGH-521)

- **AC-521.12.1 Entry.** Given the Scenarios list, with or without scenarios, then a New scenario button (in the
  header, and in the empty state) opens `/scenarios/new`.
- **AC-521.12.2 Guided form.** Given `/scenarios/new`, then it asks what to check (at least 10 characters, with
  example requests to start from), the environment, the pack (an existing one or a new kebab-case one) and an
  optional kebab-case name; "Create with Claude" waits until the request is valid.
- **AC-521.12.3 Hand-off to Claude.** Given a valid form, when the owner clicks Create with Claude, then the Discuss
  panel opens in the hub folder with the request (name, pack, environment, what to check) and the scenario format
  brief (`scenarios/brief.ts`, shared with the scenario page) as its first message, kept as a draft in this browser,
  as New workflow does.
- **AC-521.12.4 Watch the catalog.** Given the request sent, then the page watches the scenario catalog and, once a
  scenario of that name loads, links to it.
- **AC-521.12.5 Blank scenario.** Given a project, a kebab-case name and a pack, when the owner clicks "Create it blank
  and build with blocks", then a one-step scenario (a You step to replace) is saved through the builder's save, with
  no Claude, and its page opens in the builder; the button stays off until the name and pack are set.

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

### Scenario builder (AGH-521)

The scenario page's builder, as the owner validated it in the playground (its v6 and the two commits after it); the
v1 to v5 layouts (a free block canvas, Scratch-like snapping blocks, sentence blocks, step cards with arrows) were
rejected and are not built. Its relation to ADR 0049's tree format is in that ADR's delivery notes: the builder edits
`version: 1` files through the builder API ([API.md](../../../API.md#scenarios)) as below, and a file written as
blocks (`version: 2`, the `hub init` example among them) as its stages (Version 2 in the builder, after this list).

- **AC-521.13.1 Step list.** Given a scenario, then the builder reads it top to bottom as numbered steps, two lines per
  step, that say what each does; groups (Repeat, If paths, At the same time lanes) are indented; a Start row says where
  the scenario starts and what it asks for; a `+` in each gap inserts a step there; a step moves by its handle, Alt
  arrows or its row menu (rewiring what waits for what), Delete removes it with an Undo toast; rows say their effect
  and status to screen readers. What the list cannot show stays as loose steps; Graph and YAML are views beside it.
- **AC-521.13.2 Left column.** Given the builder, then its left column has a Blocks tab (the default), a Variables tab
  listing every value by where it comes from (set in the scenario, the chosen environment's values, kept values) and
  an Actions tab with the hub's actions, which previews an action, adds it, and makes or edits actions. Below 1440 px
  the column gives way while a step is open; below 1600 px Describe and Chat show their icon only.
- **AC-521.13.3 Environment in view.** Given the environment bar under the toolbar, then the chosen environment is kept
  in `?env=`, its values fill the Variables tab and the Start row asks for nothing it gives, and plans run there; a
  plan made before the last change says so.
- **AC-521.13.4 Step editor.** Given a step opened, then its editor has Settings and Script tabs. Settings shows only
  the values the step sets; inputs that come from the environment, the run or a default fold into one box with "Set
  one for this step". Script says what the action does, where each input gets its value in the chosen environment,
  what it gives back and the script's source. A new action can be written from the editor and used at once.
- **AC-521.13.5 A scenario's values.** Given the Start editor, then each value reads as name, value and what it is: a
  value left empty is asked each time the scenario runs, a value set is its default (typed as the input declares); the
  Variables tab and the editor call these "Set in the scenario". In the step editor, an action input the step leaves
  out shows the run's value ("from the run", with Set for this step), and repeats of a run value can be dropped in
  one click.
- **AC-521.13.6 Shared values in the environment.** Given a value most steps share (an account id, a stack name), then
  one click moves it into the chosen environment's values (a `hub env` write) and drops its repeats; the Variables tab
  saves an environment value.
- **AC-521.13.7 JSON values.** Given a JSON input (a message body), then it is edited as Fields (one row per key: a
  literal, or a value from earlier as a token) or as JSON (indented, checked as you type; an invalid text never reaches
  the file), and a bare reference (`"minutes":$INPUTS.minutes`) round-trips unchanged. "Use a value from earlier"
  opens a menu grouped by source, shared by the value field and the JSON rows, and inserts at the cursor.
- **AC-521.13.8 Blocks tab.** Given the Blocks tab, then it lists the step types (Do, Check, Control, You) and the hub's
  actions as ready blocks (Run <action>, and Wait until for a read-only one); a block dragged into the list shows a
  line at the gap it lands in (inside a Repeat, an If path or a lane too), and a click or Enter adds it after the
  selected step. An empty scenario still shows its Start row, so the first block has somewhere to land, and can start
  from a shape.
- **AC-521.13.9 Describe to Claude.** Given Describe with Claude, then the owner describes the scenario (or a part of
  it) in words and Claude writes a proposal, which the builder shows as suggested steps to review and accept into the
  draft, or reject; the proposal is dismissed either way. A condition typed in words becomes condition rows, naming
  what it cannot match and guessing nothing.
- **AC-521.13.10 Save and unsaved work.** Given changes, then the server's check pins each problem on its step and keeps
  Save off while the document does not load; Save writes over the file the builder read, and an unchanged document
  writes nothing. Unsaved work is kept in this browser across a reload; while the page is open, a change made outside
  asks whether to load the file's version or keep yours (Keep mine replaces it on save); after a reload, work kept for
  an older version of the file is not restored.

#### Version 2 in the builder (AGH-517)

A scenario written as blocks opens in the same builder, edited as its stages; a graph keeps everything above. The page
mounts the builder of the file's format, so a file migrated (or edited outside into the other format) opens in the
other one. The builder never writes YAML: it holds the file's JSON, the server writes the canonical text.

```
(flag) Starts in personal · Asks for shop_order_id
(milestone) Stage 1 · Fetch order · 2 steps
     1.1  (play) Run an action  queue-send · message demo.fetch-orders
     1.2  (timer) Wait until order_status is ON_HOLD and ...  every 15 s, up to 10 min · keeps order_id
(milestone) Stage 2 · Review · 2 steps
     ...
[+ Add step]  [+ Add stage]
```

- **AC-507.15 Stages of blocks.** Given a `version: 2` scenario, then the step list shows a header row per stage, in
  file order, and every block in its stage under it, numbered by its block address (`2`, `2.3`, `2.3.then.1`,
  `2.3.p2.1`, `4.1.2`), with no loose step; opened and left unchanged, nothing is to save (a block moved away and back
  writes the same document again), and a change saves the file's JSON with only that change.
- **AC-507.24 Round trip.** Given any tree document, then the builder reads it into its model and writes back the
  JSON the server parsed (`program.test.ts` over every tree fixture), its keys in the canonical order, so an edit undone
  leaves nothing to save.
- **Stages.** A stage is added from the Blocks tab's Stage block (after the selected step's stage, or at the end), a
  `+` between stages or Add stage; its header opens its editor (name, what it is for, Delete the stage and its steps,
  with Undo); it moves by its handle, Alt arrows or its row menu (Move up, Move down, Delete stage). A step goes only
  into a stage's list (or a group's), a stage only between stages.
- **A block's editor.** No "Runs after", no "Only if" and no "Runs when": position is order. More: id shows the
  block's own id, empty when it runs under the one its place gives (`fetch-order--1`, the placeholder); one given is
  written to the file and the references to the old one follow it. The placeholder typed in is given too: the block
  keeps that id when it moves, and a block then put at its old place runs under the same one, which the check refuses
  on the given `id` until one of them has another.
- **References follow their block.** No edit changes which block a `$<id>.output` (or `$LOOP_PREV.<id>.output`)
  reference reads: when a block with no id of its own gets another place id (a block inserted, moved or removed before
  it, a move to another stage, its stage renamed), every reference to it is rewritten to the new one, all at once; a
  reference to a removed block is written `<id>-removed`, an id no place gives, so the check names it rather than a
  block now at that place reading as it. An id two blocks share (two stages of one slug) is not rewritten, before the
  edit or after it: a block given in More: id the id another block has, or another block's place id, keeps the
  references to either as written, and so does the id it is given after. A stage name is written as it is typed, and
  its blocks' references follow them from the ids they ran under before the rename began, so a name typed through
  another stage's ("Order" on the way to "Order pay") loses none. A proposal's block accepted in place of the one it
  changes keeps the references to that place.
- **Graph view.** A picture of how the blocks run (the nodes they translate to, each selected with its block), with
  nothing to add or move there: "The graph shows how the blocks run: edit them in Blocks."
- **Claude.** Describe with Claude teaches the tree's keys (stages, `do`, `wait_until`, `you`, `wait`, `include`,
  `repeat`, `if`, `together`; no `nodes`, `depends_on`, `trigger_rule` or `when`), and the format brief after them is
  the tree's (no graph header, node types or `until_when`; the page's Discuss brief too); it names a place by its
  address (a stage's: at its end); the proposal is reviewed block by block by address (stages matched by name, each
  stage's blocks aligned), each change accepted or rejected on its own ("Accept block 1.4"), and Accept all takes the
  proposal's stages as the review listed them. Each block the proposal removes is a change of its own, even one alike
  another's (two `queue-send demo.poll` blocks); a decision stays on its block as other changes are accepted (a removal
  follows its block to its new address, a new or changed block keeps its place in the proposal), and the review closes
  when every change the draft still differs by is decided, one an accept brings in (a reference it moved) included.
- **Migrate, for a graph.** More › Migrate to stages of blocks opens a dialog that checks first (`POST
  …/migrate` with `check` and the hash of the file the builder read) and shows the file as blocks, or each step a
  tree cannot hold and why, with nothing written; Migrate writes it over the file the check read (the check's
  `content_hash` as `base_content_hash`) and the page opens the stages. A file changed since the check is refused
  (409 `stale_document`, shown in the dialog with Check again, which checks the file as the builder reads it now); a
  write that migrates nothing lists its own problems and offers no Migrate. With unsaved changes it asks to save them
  first, and checks nothing. Where it has got to (checking, checked, refused, written) is read out in a polite live
  region.
- **Accessibility.** Written as blocks, the tree holds only its items (stage headers, steps, an empty list's item
  with its button); the "+" in a gap is the pointer's way, and the keys add from a row (`a`), the Blocks tab, Add step
  and Add stage.

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
