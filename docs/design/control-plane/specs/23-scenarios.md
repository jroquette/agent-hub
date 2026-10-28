# Scenarios, scenario detail and scenario run

**Phase:** P2 with local writes (plan, start, the investigation session, the answer and the finding actions, and a
scenario run's breakpoints, Step and Continue, a scenario's Migrate and its Delete are strict writes,
[ADR 0040](../../../adr/0040-hub-web-keeps-local-settings-writes-hub-files-and-runs-checks.md)) ·
**Routes:** `/scenarios`, `/scenarios/:project/:name` (a scenario's name is unique per project only),
`/scenarios/:project/:name/runs/:runId` · **Answers:** "What will this scenario do in this environment, may it start,
and when a scenario run stops, what do I decide?"

The contract is [scenarios.md](../../scenarios.md); the decision is
[ADR 0041](../../../adr/0041-scenarios-actions-and-enforced-access.md), and for scenarios written as blocks and their
debugger [ADR 0049](../../../adr/0049-scenario-blocks-and-run-control.md). Glossary: a **scenario run** is a
WorkflowRun of a scenario; the UI always says "scenario run", and "run" alone means a workflow run.

## Navigation

- Sidebar, **Work** group: Features, Tickets, **Scenarios** (`clipboard-list`), Sessions, Workflow runs,
  Environments (AC-521.4.1). Always shown: a place to start work, not a log. No badge; no `g`
  shortcut; the command palette lists it under Screens, and lists a scenario run found by search as "Scenario run
  <id>" in its own group.
- Breadcrumbs: Portfolio › project › Scenarios › name › Scenario run `<id>`.
- `/runs/:runId` of a scenario run redirects (`replace`) to its scenario run page. `/runs` lists workflow runs only
  (`kind=workflow`).
- View state in the URL: `?q=` (list filter, `replace`), `?env=` (detail: pre-fills the environment; the plan never runs
  on load), `?run=` (detail: the scenario run shown on the blocks, `replace`; AGH-596), `?option=` and `?event=` (run
  page selection, `replace`). An old `?mode=run` or `?view=document` link opens the one screen, and the page drops
  both by a `replace`, keeping `?env=` (AC-596.2.1).

---

## Screen 1: Scenarios (`/scenarios`)

**Answers:** "Which scenarios does my hub hold, and did their last scenario run pass, fail or wait for me?"

```
Scenarios                                                  [As of 14:02]  [+ New scenario]
Flows your hub drives in a declared environment, step by step. Plan one to see what it will
do before anything runs.
6 scenarios · 2 packs · 1 waits for you
+-- Waiting for you ---------------------------------------------------------------------+
| (hand) order-lifecycle · scenario run 3f2a91c0 waits for you since 10:42  [Open …]     |
+----------------------------------------------------------------------------------------+
[/ Filter scenarios by name or description]
     Scenario                                          Steps   Last scenario run
(h)  order-lifecycle  [orders]                             9   (hand) Waiting for you 10:42  [⋯]
     One order from fetch to an active cover                   3f2a91c0
(x)  refund-check  [orders]                                4   (x) Failed 09:12              [⋯]
     Checks a refund reaches the shop                          71d0be2a
     stock-sync  [payments]                                3   Never run                     [⋯]
     No description.
Files that do not load (1)
scenarios/orders/returns.yaml:14   nodes[2].type   shell nodes are not allowed in a scenario
```

- **Data:** `GET /api/v1/scenarios?project=`; waiting from open human gates on `run:<id>` (as Run detail's
  `OpenGates`).
- **Rows** (AGH-596): the Features list's rows, in a card under column heads, not a `DataTable`. Each row has a lead
  icon (the waiting hand, a running dot or the failed mark), the name as a link with its pack as a tag (and its
  project, with several projects), its description (or "No description."), its steps and its last scenario run: a
  `StatusBadge` (Waiting for you, Running, Done, Failed, Cancelled), its time and the short id as a link, or "Never
  run". Not built yet (AGH-458): the `IdChip` (copy the full id) and the badge's "since" time ("Waiting for you since
  10:42").
- **Keys:** `/` focuses the filter, and `Escape` in it clears it, then leaves it. A row is one tab stop: `Enter` (or
  `o`) opens its scenario, and `j`/`k` move between rows (`useRowKeys`).

#### The list as the Features list, and Delete (AGH-596)

The owner validated these in the playground (snapshot `3df1fa457`, on v0.26.0); where the section above says otherwise,
this wins.

- **AC-596.1.7 Rows.** Given the Scenarios list, then it shows the scenarios as Features-list rows in a list named
  Scenarios, each with its name as a link, its pack as a tag, its description (or "No description."), its steps and
  its last scenario run (badge, time, short id link).
- **AC-596.1.8 Project tag.** Given scenarios in several projects, then each row also shows its project as a tag; with
  one project, no project tag shows.
- **AC-596.1.9 Order.** Given rows whose last scenario run waits for you, is running or failed, then they come first in
  that order (waiting, running, failed, then the rest), each group by name; waiting and failed rows carry their tone.
- **AC-596.1.10 Summary.** Given the list, then the header says "N scenarios · M packs", and "K wait for you" when K is
  more than 0, as the Features list's summary does.
- **AC-596.1.11 Page box and filter.** Given the list, then the page is a box centred and capped at 1440 px, with the
  Features toolbar's search (`/` focuses it; `Escape` clears it, then leaves it).
- **AC-596.1.12 Open.** Given a row, when it is clicked, or focused and Enter is pressed, then its scenario opens; the
  name link and the run's short id open their own pages, not the row's.
- **AC-596.1.13 Narrow.** Below 1280 px the Steps column hides; below 1100 px the last run's time hides and the row's
  head wraps.
- **AC-596.1.14 Row menu.** Given a row, when its "Actions for <name>" menu (`⋯`) opens, then it offers Open scenario
  and Delete scenario…; `Escape` or a click outside closes it, and `Escape` puts focus back on its button.
- **AC-596.1.15 Delete.** Given Delete scenario… chosen, then a confirm "Delete scenario <name>?" says "This removes
  <path> from the <project> hub folder.", "Its recorded scenario runs stay.", "The actions it calls in
  actions/<pack>/ stay." and "hub web cannot undo this. Until you commit the removal, restore it in the hub with
  `git restore <path>`." Delete scenario (it reads "Deleting…" while it is on its way) sends `DELETE
  /api/v1/scenarios/{project}/{name}`; the dialog closes, a toast says "Deleted scenario <name>." with Copy restore
  command and leaves after 6 s, and focus moves to the next row, else the previous one, else the filter.
  `git restore` brings back only the last committed version of the file. A scenario that was never committed cannot
  be restored, and nor can edits that were not committed.
- **AC-596.1.16 Refused.** Given the server refuses the delete (a 409), then the dialog stays open with "Could not
  delete the scenario. <detail> Nothing was deleted."; a 401 says "Deleting is locked in this browser. Open the link
  hub web printed when it started (it ends with ?token=…) once in this browser."
- **AC-596.1.17 Already gone.** Given the scenario is already gone (404), when the delete is confirmed, then it counts
  as done: the dialog closes and the toast says "<name> was already gone from the hub folder.", with no restore
  command.
- **AC-596.1.18 Not during a run.** Given a scenario whose last scenario run is running or waits for you, when its
  menu opens, then Delete scenario… is off and says "A scenario run of it is in progress. Let it end or cancel it
  first."
- **AC-596.1.19 From the scenario page.** Given a scenario's page, when its Scenario actions menu (in the breadcrumb
  row) deletes it, then the page replaces itself with `/scenarios`, which shows the deleted toast once (not again on
  Back or a reload) and focuses the Scenarios heading; the menu's Delete is off while the newest scenario run is
  running.

| State | Copy |
|---|---|
| Empty | "No scenarios yet." / "Scenarios are YAML files in the hub's scenarios/<pack>/ folder, and the actions they call are in actions/<pack>/. Describe one and Claude writes it, or add one by hand and check that it loads from a terminal:" `./hub scenario list` [New scenario] |
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
  as New workflow does. The brief teaches the blocks format (`version: 2`, stages and what each block holds, as
  Describe with Claude does), so the scenario Claude writes opens in the builder as stages.
- **AC-521.12.4 Watch the catalog.** Given the request sent, then the page watches the scenario catalog and, once a
  scenario of that name loads, links to it.
- **AC-521.12.5 Blank scenario.** Given a project, a kebab-case name and a pack, when the owner clicks "Create it blank
  and build with blocks", then a scenario written as blocks (`version: 2`: one stage, "First stage", holding one You
  block to replace) is saved through the builder's save as revision 1, with no Claude, and its page opens in the
  builder as stages; the button stays off until the name and pack are set.

## Screen 2: Scenario detail (`/scenarios/:project/:name`)

**Answers:** "What will this scenario do in this environment, step by step, and may it start?" The page builds and
runs the scenario on one screen (AGH-596): the builder's blocks, a run bar over them, a run strip for the scenario run
shown on them, and a run panel beside them. The primary action is "Plan in <environment>", then "Start scenario run".

```
Portfolio › demo › Scenarios › order-lifecycle                            [⋯ Scenario actions]
order-lifecycle   pack orders · revision 1     [Blocks|Graph|YAML]   No problems   [Save]
Environment [personal · access write ↕]  Scenario run mode [Interactive|Regression]  |
  [Inputs · 1 set] [Plan again] [Clear plan]                        [Start scenario run]
(v) Can start in personal · 4 blocks: 2 read, 2 write · 1 asks you
(o) Scenario run 3f2a91c0 is running in personal · Interactive · at block 1.2 · started 14:05
                                      [Open scenario run →] [Cancel scenario run] [x] Follow
+-- Variables | Actions --+-- Blocks ----------------------------------+-- Run panel ----------+
| ...                     | (milestone) Stage 1 · Fetch order          | This plan             |
|                         |  1.1 (play) Send the order       (v) Done  | personal · access     |
|                         |      Sends one message to the queue        |   write               |
|                         |      queue-send · queue orders · +1 value  | 4 blocks: 2 read, ... |
|                         |      Kept order_id = 42                    | Before you start      |
|                         |      Plan: Sends 1 message · (v) Allow     | 1 draft action to ... |
|                         |  1.2 (timer) Wait until order is ON_HOLD   | Scenario runs (12)    |
|                         |      checks every 15 s, up to 10 min       | (o) 3f2a91c0 personal |
|                         |      Running · check 3     (o) Breakpoint  |              [Shown]  |
+-------------------------+--------------------------------------------+-----------------------+
```

- **Data:** `GET /api/v1/scenarios/{project}/{name}`; the shown scenario run's record (`GET
  /scenario-runs/{id}`, streamed while it runs); open gates from `GET /approvals`.
- **Plan:** `POST …/plan` on the person's click only (Plan, or Enter in the run bar). A row of the plan lands on its
  block as a "Plan: …" line with its policy (Allow, Asks you (neutral until a gate waits), Denied + the reason in
  words). A draft action is listed once, in Before you start, with one commit command; nothing commits from hub web.
- **Start:** enabled only on a current plan with no deny and no problem, and no scenario run of it in progress; a
  confirm dialog names the environment, the counts, the asks, the breakpoints and the mode ("Start a scenario run in
  personal?", buttons "Start scenario run" / "Back to plan", Back to plan focused). After 202, the page stays: the new
  scenario run shows on the blocks (`?run=`) and Follow turns on.
- **Mode:** Interactive (the default) "If a block does not reach its expected state, the scenario run pauses and a
  read-only agent investigates with you." · Regression "No agent and no token cost. The first block that does not
  reach its expected state fails the scenario run." · both: "Blocks that ask still pause for your approval." (a graph
  scenario says "step").
- **Environment:** a select of the project's declared environments ("personal · access write", "live · production ·
  access read"), its title the access in words ("Agents only read here."). Without `?env=` it opens on the last
  environment used in this browser that is still declared and not production, else the first one that is not
  production: never production unless picked.
- **Content hash:** a tooltip on the step ("Pinned when the scenario run starts: sha256:…").

| State | Copy |
|---|---|
| No environment | "Choose an environment to plan in." |
| Unsaved | "Save your changes, then plan: a plan reads the saved file." (Plan reads "Save and plan") |
| No plan | "Plan the scenario to see what each step will do in personal. Nothing is changed by a plan." (Start off: "Plan the scenario first.") |
| Planning | "Planning in personal… each step's script runs in plan mode." · after 10 s "Still planning. A plan stops after 5 min." |
| Can start | "Can start in personal · 4 steps: 2 read, 2 write · 1 asks you" |
| Draft actions | "Cannot start: 1 draft action needs acceptance. See Before you start." (a link to Before you start) |
| Plan problems | "Cannot start: the plan has 1 problem." (Start off: "Fix the problems first.") |
| Denied | "Cannot start: fetch-order and resolve-cover are denied in qa." |
| Denied, no step named | "Cannot start in qa: the plan does not allow a start there." |
| Stale plan | "This plan is for personal. Plan again to start in qa." · "The steps changed since this plan. Plan again to start." · "Save your changes, then plan again: a plan reads the saved file." · "This plan is for external_ref T-1. Plan again to start with the new values." (Plan reads "Plan again") |
| In progress | Start off: "A scenario run of it is in progress." |
| Production | "live is a production environment: writes and destroys are denied there, and breakpoints are off." |
| Undeclared | verdict "Environment qa is not declared in this hub." · run panel "Environment qa is not declared in this hub. Declare it in hub.json, or in hub.local.json for yourself:" `./hub env add qa --access read` |
| Invalid inputs (422) | Values to plan and start with opens, each message under its input's field; a message for no field shown is listed in the run panel |
| `hub.local.json` invalid | "hub.local.json cannot be read or conflicts with hub.json, so the environments are unknown. Run ./hub doctor to see the problem, fix the file, then plan again." |
| Plan timeout (502) | "The plan did not finish in 5 min, so it was stopped. A plan-mode script may hang: run it from a terminal to see which." `./hub scenario plan order-lifecycle --env personal` |
| Locked (401) | "Planning is locked in this browser. Open the link hub web printed when it started (it ends with ?token=…) once in this browser." |
| Container (404 `run-control-off`) | "Plans and scenario runs cannot start from the agent-hub container: it has no credentials and no env files. Run hub web on your machine, or plan from a terminal:" `./hub scenario plan order-lifecycle --env personal`; Plan turns off |
| Start refused (409) | "Could not start the scenario run" / the server's detail (steps named) / "Nothing was started." |
| Start failed (502) | "Could not start the scenario run" / "hub web could not launch hub scenario run. Run it from a terminal to see why:" `./hub scenario run order-lifecycle --env personal` |
| Tablet (768–1279) | "Starting a scenario run needs a desktop screen." in Start's place |
| Not found | "Scenario order-lifecycle not found" / "Project demo has no scenario order-lifecycle that loads. It may have been renamed, or its file may not load." |
| No scenario runs | "No scenario runs yet. Plan, then start one from the bar above." |

A scenario written as blocks says "block" where these say "step".

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
  Superseded by AGH-596's one screen (below).
- **AC-521.11.3 Run panel beside the steps.** Given a wide screen, then the plan, mode and start controls sit in a run
  panel beside the storyline; an action's name opens a panel with its description, effect, inputs and script, and
  the scenario's file opens as text. Superseded by AGH-596's one screen (below).
- **AC-521.11.4 Live run.** Given a scenario run of this scenario that is running, then the page follows it: a banner
  says it is running in its environment, links to the scenario run and offers Cancel (the run page's own command),
  and each step's card shows its status in that run as it moves (Done, "Running · check 3", Not started). Superseded
  by AGH-596's run strip (below).

### Departures (AGH-596, build and run on one screen)

The owner validated these in the playground (snapshot `3df1fa457`, on v0.26.0). They supersede AC-521.11.2 to
AC-521.11.4 (the storyline, the run panel beside it, the live banner); AC-521.11.1 stays. Where another section says
otherwise, this wins.

- **AC-596.2.1 One screen.** Given an old link to the page's Run mode or Document view (`?mode=run`, `?view=document`),
  when it opens, then the page is the builder only (its View offers no Run), and the two params are dropped by a
  `replace` while `?env=` is kept.
- **Run bar.** The bar under the toolbar holds the environment, the Scenario run mode, a separator, then Inputs, Plan
  and Clear plan, and Start at its end; the verdict line sits under it.
  - **AC-596.2.2 Environment.** It lists the declared environments as "name · [production · ]access X", offers
    "Choose an environment" while none is chosen, says the access in words in its title, and is off while planning.
  - **AC-596.2.3 Never production by default.** Given no `?env=`, the page opens on the last environment used in this
    browser that is still declared and not production, else the first one that is not production.
  - **AC-596.2.4 Mode.** The Scenario run mode (Interactive, the default, or Regression) is sent with the start, and
    the confirm words the mode's stop.
  - **AC-596.2.5 Inputs.** Given a required input nothing gives a value, when Plan is pressed (or Enter in the bar),
    then "Values to plan and start with" opens. An Inputs button ("Inputs · N to fill", "Inputs · N set") toggles it.
  - **AC-596.2.6 No plan on load.** Given the page opens, then no plan is requested; the verdict says "Plan the
    scenario to see what each step will do in <env>. Nothing is changed by a plan." and Start is off ("Plan the
    scenario first.").
  - **AC-596.2.7 Verdict.** Given a plan, then the verdict says "Can start in <env> · N steps: … · N asks you", or
    names the denied steps, a denial with no step, the draft actions (a link to Before you start) or the plan's
    problem count; Start's title repeats the reason.
  - **AC-596.2.8 Start.** Given a startable plan, when Start is pressed, then the confirm names the environment, the
    counts, the asks, the breakpoints and the mode, with Back to plan focused. Once accepted the page stays, `?run=`
    names the new scenario run, its row in Scenario runs is Shown and its strip shows (AC-596.2.33: at once, with
    Follow on). A refusal shows the server's reason and "Nothing was started."; a scenario run that is late to
    report never offers a second start.
  - **AC-596.2.9 Stale plan.** Given unsaved changes, another environment or changed blocks since the plan, then the
    verdict says why ("Save your changes, then plan again…", "This plan is for X. Plan again to start in Y.", "The
    steps changed since this plan…"), Start stays off, and Plan reads "Save and plan" or "Plan again".
    **AC-596.2.34:** so does a change of an input's value ("This plan is for external_ref T-1. Plan again to start
    with the new values."), so a start never sends the old values.
  - **AC-596.2.10 Clear plan.** Clear plan removes the plan, its verdict and its lines on the blocks.
  - **AC-596.2.11 Production.** Given a production environment picked, then a banner says "<env> is a production
    environment: writes and destroys are denied there, and breakpoints are off.", and no breakpoint is offered or
    sent.
  - **AC-596.2.41 Room.** The bar's controls are grouped, and the environment select leaves room for its chevron.
- **Kept on the one screen.** The snapshot dropped these; the delivery keeps them, as the states table above says:
  on a tablet (768–1279 px) Start's place says "Starting a scenario run needs a desktop screen."; an environment the
  hub does not declare (an old `?env=`) shows in the select as "qa · not declared", the verdict says so and the run
  panel gives `./hub env add qa --access read`; a plan's 422 puts each message under its input's field in Values to
  plan and start with (which opens), and lists the others in the run panel; after 10 s of planning the verdict adds
  "Still planning. A plan stops after 5 min."
- **Run strip.** One line under the verdict for the scenario run shown on the blocks: the newest one while it runs,
  or the one `?run=` names.
  - **AC-596.2.12 Running.** It says "Scenario run <id> is running in <env> · <mode> · at block X · started <time>",
    links to the scenario run (Open scenario run), offers Cancel scenario run and a Follow checkbox (on: the current
    block scrolls into view as the run moves), and a new start is off.
  - **AC-596.2.13 Waiting.** Given the run waits on a gate of this scenario, then it says "waits for you at block X:
    an approval" (or "an investigation"), and that block reads "Waiting for you: approval" (or "investigation").
  - **AC-596.2.14 Debug pause.** Given a debug pause, then it says "is paused before block X <reason> in <env>", the
    run panel shows the debug bar, the held block reads "Paused before it" and the run's own breakpoints show pressed.
  - **AC-596.2.16 A past run.** Given a finished run shown, then the strip says "· Done in <env> at <time>", the
    blocks read "Last run: …", and Hide its states clears `?run=` and the strip.
  - **AC-596.2.17 Not on these blocks.** Given a shown run of an older revision, or blocks changed since the file was
    read, then no state is laid on the blocks and the strip says "· it ran an older revision of the file, so its
    states are on its page" or "· you changed the blocks since, so its states are hidden".
- **Run panel.** The right column while no block is open in the editor.
  - **AC-596.2.18 Its place.** It holds, in order, the debug bar, the plan's problem, This plan, Before you start and
    Scenario runs; opening a block puts the editor in its place, and the run bar stays.
  - **AC-596.2.19 This plan.** It shows "<env> · [production · ]access X", the counts, "Planned before your changes:
    plan again to start." when stale, the production banner and each problem.
  - **AC-596.2.39 Before you start.** Given draft actions, it says "N draft action(s) to commit" and "You can plan now.
    A scenario run starts once these actions are committed in the hub checkout: one commit does it.", offers Copy the
    commit command, then "then plan again", and folds the actions and the command under "Which actions (N) and the
    command". No block carries a Draft action chip.
  - **AC-596.2.40 / AC-596.2.42 One commit.** The commit joins the draft actions' `git add` paths, each once, with
    one message "Accept actions a, b"; a command of any other shape is kept and joined with `&&`; a single draft
    action's command is the server's, word for word.
  - **AC-596.2.20 Scenario runs.** It lists the newest five with status, id link, environment, time and Show (Shown
    when pressed); "Show all N" and "Show fewer" when there are more; with none, "No scenario runs yet. Plan, then
    start one from the bar above."
  - **AC-596.2.35 Container.** Given the container's 404 `run-control-off` answer to a plan, then the panel says
    "Plans and scenario runs cannot start from the agent-hub container…" with the terminal command, and Plan turns
    off.
- **On the blocks.**
  - **AC-596.2.21 / AC-596.2.22 States.** Given a shown run, then each row shows its state (Done, "Running · check
    N", Not started), the current row is `aria-current="step"`, and a block written as blocks shows "Kept name =
    value" for what it captured.
  - **AC-596.2.23 Plan lines.** Given a plan, each row has a "Plan: …" line under its values ("Planned before your
    changes · …" when stale) and its policy as a `PolicyBadge` (an ask neutral).
  - **AC-596.2.24 Breakpoints before a start.** Off production, a block's Breakpoint button (or `b` on its row)
    toggles it; the confirm says "It pauses before block 1.2, its breakpoint." and the start sends the breakpoints
    in file order.
  - **AC-596.2.15 Breakpoints of a live run.** Given a live run shown off production, a toggle writes the run's whole
    set (`PUT …/breakpoints`), and is `aria-disabled` while that is on its way.
  - **AC-596.2.25 Quick actions.** On hover or focus a row shows Rename (`F2`), Duplicate (`⌘D`), Delete and More
    (`Shift F10`, the row menu); Delete says "Deleted step X." ("Deleted stage X and its steps." for a stage).
  - **AC-596.2.26 Rename in place.** `F2` on a row edits its sentence in place; Enter writes it (Unsaved) and focus
    returns to the row; `Escape` leaves it as it was.
  - **AC-596.2.28 / AC-596.2.31 Timing.** A selected Wait until row's timing chip edits "How often it checks" in
    place, even when the row sets no value, and the row reads the new pace.
  - **AC-596.2.37 What it does.** A row's second line says what it does in words: its action's first sentence (when
    not the title), "until …", "checks every X, up to Y", what it keeps.
  - **AC-596.2.43 Title room.** A step's title keeps its room when the row's right side is full (badges, plan line,
    quick actions): the right side never pushes the title out.
  - **AC-596.2.38 Technical line.** The action name and its short values move to a quieter line under it; a JSON
    body or a value over 40 characters is only counted ("+N values") until the row is selected.
  - **AC-596.2.36 The tree.** On a graph scenario too, the `+` in each gap is hidden from the tree (`aria-hidden`),
    which holds only its items.
- **AC-596.2.29 Check.** The toolbar's check reads "No problems" (" · N draft actions to commit"), and its popover
  says "Nothing to fix in the file. N draft actions need a commit … Before you start." or "The scenario file has no
  problem."
- **AC-596.2.30 Page box.** On a wide screen the blocks sit against the left column (at most 960 px, no auto margin),
  in a page box capped at 1920 px; Save is primary only with changes.

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
  Since AGH-596 a selected action or check step opens in place (§ The open step, below): its second line and its
  technical line give way to the open part.
- **AC-521.13.2 Left column.** Given the builder, then its left column has a Blocks tab (the default), a Variables tab
  listing every value by where it comes from (set in the scenario, the chosen environment's values, kept values) and
  an Actions tab with the hub's actions, which previews an action, adds it, and makes or edits actions. Below 1440 px
  the column gives way while a step is open; below 1600 px Describe and Chat show their icon only.
- **AC-521.13.3 Environment in view.** Given the environment bar under the toolbar, then the chosen environment is kept
  in `?env=`, its values fill the Variables tab and the Start row asks for nothing it gives, and plans run there; a
  plan made before the last change says so. Since AGH-596 the environment bar is the run bar (§ Departures (AGH-596)),
  and the environment it opens on is never a production one unless picked.
- **AC-521.13.4 Step editor.** Given a step opened, then its editor has Settings and Script tabs. Settings shows only
  the values the step sets; inputs that come from the environment, the run or a default fold into one box with "Set
  one for this step". Script says what the action does, where each input gets its value in the chosen environment,
  what it gives back and the script's source. A new action can be written from the editor and used at once. Since
  AGH-596 the Script tab shows the files in Script and Action file tabs with Expand (the shared `ActionFiles`, also
  in the open step), each file coloured by its language with a badge naming it.
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

#### The open step (AGH-596)

The owner validated these in the playground (snapshot `3df1fa457`, on v0.26.0). A selected action or check step opens
in place, under its title, as one group named "Step N settings" (`ServicePicker.tsx` and `OpenStep.tsx` cite this
section).

```
 1.1  (play) Send the order                                      Changes data
      What it does
        Action      send-queue-message · Python   Sends one message to the queue.
        > Show the code it runs     [Script | Action file]  [Expand]
      Values for this step                                      1 needs a value
        [Queue (SQS) ↕]  [orders-queue]
          target · Required · Queue (SQS) · Orders to pay · orders-queue-personal
        message_group  [Edit message_group: demo]
        body  JSON                                              [Edit body] [Copy body]
          { "event_type": "order.created", "ref": <$INPUTS.external_ref> }
        priority    (!) Needs a value                         [Set it in the panel]
      Values from earlier
        external_ref   Scenario input · asked when the scenario run starts
        order_id       Kept by 1.2                                      [Go to 1.2]
      Keeps for later steps
        message_id     <$CTX.message_id> from message_id
```

- **AC-596.3.20 By task.** Given an open step, then it reads in this order: What it does (Action with its runtime,
  Checks and Until for a check, the folded code), Values for this step, Values from earlier, and Keeps for later
  steps. It is part of its row: no card and no status colours, a hairline under the title, and the effect said only
  by the row's badge, not again inside.
- **AC-596.3.2 JSON body.** Given a value that is a JSON body with a bare reference (`$INPUTS.external_ref`), then
  the open step shows it as indented JSON, coloured, in the app's code well, the reference as the builder's token, not
  as quoted text; a closed row shows no body. **AC-596.3.26:** the well runs left to right at the row's full width.
- **AC-596.3.21 Body actions.** A body is listed in Values for this step under its name, with "Edit <name>" (it opens
  the side panel at that field) and "Copy <name>", above its code well.
- **AC-596.3.3 Value notes.** A value the step sets shows under the input's name, with "Required · <the input's
  description>" as its note.
- **AC-596.3.25 / AC-596.3.8 Editable values.** Each plain value is a chip on one line, cut with an ellipsis, and a
  Tab stop named by what it edits ("Edit <name>: <value>", "Edit how often it checks: every …"); it edits in place
  and is written back as the value's own type.
- **AC-596.3.11 Only what the step sets.** Inputs the step does not set and something else gives (the run, the
  environment, a default, such as a region or an account) are not listed.
- **AC-596.3.22 Values from earlier.** Each reference a value uses is listed with where it comes from: a scenario
  input (asked at start, or "Scenario input · <value> from <env>", or "Not asked by the scenario"), "Kept by N" with
  "Go to N", which selects that step, or "Not given by any earlier step".
- **AC-596.3.23 Needs a value.** A required input that nothing gives (not set by the step, not a scenario input, not
  in the environment, no default) is listed as "Needs a value", with an icon and words, counted on the group's title
  ("1 needs a value", "2 need a value"), with "Set it in the panel", which opens the side panel's Settings at that
  field.
- **AC-596.3.24 Draft.** Given a draft action, then What it does says "Draft: needs acceptance" with what that means
  and a button that copies its commit command.
- **AC-596.3.12 / AC-596.3.15 The code it runs.** The action's script and file fold under "Show the code it runs", at
  the end of What it does; one click shows them in the same Script and Action file tabs, with Expand (a dialog titled
  "<path> · <action>"), as the side panel's Script tab.
- **AC-596.3.14 What each file is.** In the open step, the script says "Runs." (the code this step executes, with the
  step's values as its inputs) and the action file "Declares." (it is not run: it names the script, its inputs, its
  effect and its answer). The side panel shows no such line.
- **AC-596.3.13 Colours.** An action's file, in the open step and in the action panel, is coloured by its extension's
  language and a badge names it (Python, Bash, YAML, JSON…).
- **AC-596.3.16 / AC-596.3.28 Layout.** Each row puts its label in a fixed column and its value right after it, both
  left-aligned, with its note across the row; tokens keep their own width; the groups sit on `surface`; the open
  part has the same 12 px inset on both sides.
- **AC-596.3.5 Row menu.** The row menu (More, the handle or a right-click) renders on `document.body`, next to the
  button that opened it, so an open step never clips it.
- **AC-596.3.29 Accessibility.** With a service input open and its list shown, axe finds no serious or critical
  violation.

#### Service inputs (AGH-596)

An action input of type `service` names a declared service ([scenarios.md](../../scenarios.md) § Actions). In the
builder it is picked, never typed, the same way in the open step and in the side panel's step editor.

- **AC-596.4.1 / AC-596.4.10 A field, never a text box.** Given an editable scenario, then a service input is a
  field (a button "target: <service>" or "target: choose a service"), in the open step and in the side panel; a pick
  in either sets the step's value.
- **AC-596.4.2 The list.** Given the field pressed, then a dialog "Choose <input>" lists the declared services
  grouped by kind under headings (Queues (SQS), Databases, APIs and backends…), the kinds in the snapshot's fixed
  order (APIs, then databases, then queues…), then by name. Kinds are named with the Environments page's words: a
  `queue` kind is "Queue or topic" ("Queues and topics" as a heading). Each row keeps the `server` icon, and the
  current pick shows a check.
- **AC-596.4.3 Addresses.** Each row shows its address in the run bar's environment (its URL, else its resource), or
  "no address in <env>"; the header says "services in <env>".
- **AC-596.4.4 Search.** Typing in "Find a service by name, kind or address" keeps the services whose name, kind,
  address, description or repo hold the text; with none left it says "Nothing matches."
- **AC-596.4.5 None declared.** With no service declared it says "No service is declared in <env>. Add one in
  Environments."
- **AC-596.4.6 Pick.** Up and Down, then Enter (or a click), picks a service: the list closes, the step's `with`
  value is set and the draft is Unsaved; `Escape` or a press outside closes it with no change.
- **AC-596.4.7 Not set yet.** A service input the step does not set yet still has its row, with an empty field, so
  where it goes is chosen in the step.
- **AC-596.4.11 / AC-596.4.12 Kind.** A kind select ("Kind of service for <input>": Any kind and each declared kind)
  sits before the field; chosen, it filters the list and its header names the kind; left alone, it shows the picked
  service's own kind.
- **AC-596.4.13 / AC-596.4.15 Written value.** A pick is written by its name alone, and as `<repo>/<name>` only when
  another repo declares a service of that name; the field shows the name alone either way ("target: orders-queue").
- **AC-596.4.14 Row.** In the open step a service row reads kind then service: the kind select stands in the label
  column, and the input's name moves to the note under the row. **AC-596.3.17:** the select and the field are both
  24 px controls, and the field shows the service's name, its address in the tooltip.
- **AC-596.4.16 / AC-596.4.17 / AC-596.3.27 Note.** The note says what is picked ("<input> · Required · <kind in
  words> · <the service's description> · <address in env>", or "no address in <env>"), or what to choose when
  nothing is ("Choose a service in <env>", "Choose a <kind> in <env>"); a required one with nothing picked says
  "Needs a value" and counts on the group. It never repeats the action's own words about the input.
- **AC-596.4.9 / AC-596.3.18 Not declared.** A value that names no declared service shows with "not declared in
  <env>" and an icon.

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
  with Undo; a problem on its name shows under the field, one on its steps above it); it moves by its handle, Alt
  arrows or its row menu (Move up, Move down, Delete stage). A step goes only into a stage's list (or a group's), a
  stage only between stages.
- **A block's editor.** No "Runs after", no "Only if" and no "Runs when": position is order. More: id shows the
  block's own id, empty when it runs under the one its place gives (`fetch-order--1`, the placeholder); one given is
  written to the file and the references to the old one follow it. The placeholder typed in is given too: the block
  keeps that id when it moves, and a block then put at its old place runs under the same one, which the check refuses
  on the given `id` until one of them has another. The field refuses `self` (its help says why: `$self.output` reads a
  block's own output), as it refuses an id that is not kebab-case: the block keeps the id it had.
- **References follow their block.** No edit changes which block a `$<id>.output` (or `$LOOP_PREV.<id>.output`)
  reference reads: when a block with no id of its own gets another place id (a block inserted, moved or removed before
  it, a move to another stage, its stage renamed), every reference to it is rewritten to the new one, all at once; a
  reference to a removed block is written `<id>-removed`, an id no place gives, so the check names it rather than a
  block now at that place reading as it. An id two blocks share (two stages of one slug) is not rewritten, before the
  edit or after it: a block given in More: id the id another block has, or another block's place id, keeps the
  references to either as written, and so does the id it is given after. A stage name is written as it is typed, and
  its blocks' references follow them from the ids they ran under before the rename began, so a name typed through
  another stage's ("Order" on the way to "Order pay") loses none. In the review of Claude's proposal, a block taken
  from the proposal keeps its references as Claude wrote them (they read the proposal's places, which the draft
  reaches once the blocks before them are taken too); a block of the draft's alone (its removal or its change
  rejected) has its references follow the blocks they read, to the block that takes one's place when that change is
  accepted (a changed block, one Claude gives an id of its own); a block both hold reads the block it reads in both,
  or the one of its two the draft still holds, and is left as written otherwise. A reference is rewritten only inside
  a value (never a key) and only to an id a reference can name, spelt as the grammar spells one (`[a-z][a-z0-9_-]*`):
  one to a block given any other id (a proposal's `k"q`, `CTX`, a file the load refused) stays as written, for the
  check to name. `$self.output` is a block's own output, never a reference to a block named `self` (an id the check
  refuses): a rename of that block leaves it as written, and no reference is rewritten to it
  (`$LOOP_PREV.self.output` does read the block, and follows it).
- **Graph view** (redrawn by AGH-596, `StageGraph`). A picture of how the blocks run, drawn from the blocks, not from
  the nodes they run as, with nothing to add or move there: "The graph shows how the blocks run: edit them in
  Blocks." (AC-596.5.12).
  - **AC-596.5.7 / AC-596.5.8 Stages.** Between a Start and an End marker, each stage is a band (a region named
    "Stage <n>: <name>") with its number, name and block count; its blocks run left to right with an arrow between
    two, and wrap at the band's edge, so the graph uses the screen's width.
  - **AC-596.5.9 Groups.** An If is a frame with its condition and two paths, "If yes" and "Otherwise"; At the same
    time is a frame with a lane per path ("Path 1", "Path 2"…); a Repeat is a frame around a round's blocks ("Each
    round, at most N"). An If nested in another shows its own condition.
  - **AC-596.5.10 Current block.** Given a scenario run shown and at a block, its card is marked as current, as in
    Blocks.
  - **AC-596.5.11 Select.** A click selects a card (`aria-pressed`); "Open it in Blocks" opens Blocks with that block
    selected; with nothing selected the button reads "Back to Blocks".
  - **AC-596.5.13 Accessibility.** Bands are regions, frames groups and cards buttons; axe finds no serious or
    critical violation.
- **Graph cards** (AGH-596). A card reads as its Blocks row, from one shared place (`rowLines`), in a graph scenario's
  (`version: 1`) Graph view too:
  - **AC-596.5.1** its number (1.1), kind tile and title (named "Block 1.1, <kind>: <title>");
  - **AC-596.5.2** the same sentence of what it does and the same quiet technical line as the row;
  - **AC-596.5.3** a long or structured value only counted ("+1 value"), the line cut with an ellipsis, the full
    text in the card's tooltip;
  - **AC-596.5.4** its effect in words (Reads only, Changes data, Deletes data), "Draft" for a draft action and "N
    problems" for a block with errors;
  - **AC-596.5.5** its state in the shown scenario run;
  - **AC-596.5.6** on a neutral card: no coloured top edge, no lift on hover, no entry animation; kind shows only by
    its tile, and a selected card has an accent border.
- **Code in colour** (AGH-596, [ADR 0052](../../../adr/0052-syntax-highlighting-across-the-app.md)). The YAML view and
  Migrate's preview of the file as blocks are coloured as YAML (AC-596.5.16, AC-596.5.17); an action's files, in the
  action panel and the open step, by their language (AC-596.5.18); every command (`CodeBlock` with the `$` prompt) as
  shell (AC-596.5.19).
- **Claude.** Describe with Claude teaches the tree's keys (stages, `do`, `wait_until`, `you`, `wait`, `include`,
  `repeat`, `if`, `together`; no `nodes`, `depends_on`, `trigger_rule` or `when`), and the format brief after them is
  the tree's (no graph header, node types or `until_when`; the page's Discuss brief too); it names a place by its
  address, in the dialog as in the prompt ("Steps after block 1.2", "Steps at the end of stage 2"), and the brief
  says what an address is (stage, then step; `then`/`else`, `p<n>` for a Together's path, a Repeat's steps by their
  place), as "Ask Claude about this step" does when it names a block by its address. The proposal is
  reviewed change by change (stages matched by name, each stage's blocks aligned), and the review lists its changes
  once, when it opens, from the draft as it is then and the proposal: each block or stage added, changed or removed
  (one alike another's too: two `queue-send demo.poll` blocks removed are two changes), a stage's own change (its
  name, what it is for, its place among the stages), and the scenario's inputs and description when the proposal
  gives others. Each change keeps its name until the review closes, its kind in it ("Accept new block 1.4" by its
  address in the proposal, "Reject removed block 7.1" by its address in the draft the review opened on). The draft is
  always the one the decisions give, written again from the draft the review opened on and the proposal at each
  decision, never from the draft the last one gave: every change taken gives the proposal, none the draft as it was.
  The review closes when every change it listed is decided; Accept all and Reject all decide every change at once
  (Reject all after an accept gives back the draft the review opened on; Undo brings the accepts back). Any other edit
  of the draft (Back to my draft, then an edit or Undo) opens the review again on the draft as it then is. A proposal
  with no stages (a graph's `nodes`) says so in the banner: taken all, it leaves no stage. The banner counts new or
  changed stages (a stage's own change among them) apart from new or changed blocks ("Claude proposes 1 new or
  changed stage, 1 removed, changed inputs"). Under review the blocks shown are the proposal's, so none shows a row
  of a plan made for the draft; Back to my draft shows them again. For the same reason a proposal's row selected
  under review is not a block of the draft: Delete, Alt arrows, ⌘D, a block of the Blocks tab (click or Enter), Add to
  the scenario and Describe's "after" leave the draft as it is, and opening or closing the review clears the
  selection. The Blocks tab says so ("While you review Claude's proposal the draft is not edited: go back to your
  draft to add a block."), its blocks marked unavailable and named with no place, and the action panel's Add to the
  scenario is off.
- **New action.** "Ask Claude to write one" in a block's editor names the block by its address in a scenario written
  as blocks ("for the block 1.2 of this scenario"), with the brief's line on what an address is, as "Ask Claude about
  this step" does; a graph's step by its id.
- **Migrate, for a graph.** More › Migrate to stages of blocks opens a dialog that checks first (`POST
  …/migrate` with `check` and the hash of the file the builder read) and shows the file as blocks, or each step a
  tree cannot hold and why, with nothing written (to change in the builder, then open Migrate again); Migrate writes
  it over the file the check read (the check's `content_hash` as `base_content_hash`) and the page opens the stages.
  A file changed since the check is refused (409 `stale_document`, shown in the dialog with Check again, which reads
  the file again first, without waiting for the builder's next read, and checks it with that file's hash); a
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

### Debugging a run written as blocks (AGH-518)

A scenario run of a `version: 2` scenario ([ADR 0049](../../../adr/0049-scenario-blocks-and-run-control.md),
[scenarios.md](../../scenarios.md) § Debugging) shows the blocks it pinned when it started, and debugs them. Everything
on this page comes from the run (`ScenarioRunDetail.blocks`, its snapshot's tree), never from the scenario file as it
reads now, so an edit in the builder while the run is paused changes none of it, and Continue runs the pinned tree.

```
Scenario run 3f2a91c0  (hand) Waiting for you   order-lifecycle · personal · Interactive
(pause) Paused before block 2.1 (Do: queue-send), at its breakpoint.
        Nothing of this block has run yet.
        Step runs the next block and pauses before the one after it; Continue runs to the next
        breakpoint or the end. Neither answers a gate, edits a value, or re-runs or skips a block.
        [Step] [Continue]
Blocks                                                          | Scenario run facts
As this scenario run pinned them when it started: ...           | Values while paused
1    Stage: Fetch order                          (o) Breakpoint |   Inputs, environment values
  1.1  Do: queue-send               (v) Done     (o) Breakpoint |   included: shop_order_id = T-1
  1.2  Wait until: order-state      (v) Done     (o) Breakpoint |   Finished blocks
2    Stage: Review                               (o) Breakpoint |   > 1.1 queue-send · fetch-order--1 · Done
  2.1  Do: queue-send   (hand) Paused before it  (•) Breakpoint |   > 1.2 order-state · fetch-order--2 · Done · 3 polls
  2.2  You: Check the review, then approve.  Not started  (o)   |
Timeline
```

- **AC-507.17 Breakpoints.** Given a run's page, then each block row (address, kind and label, its state in the run
  from the timeline lines' `block`: Done, Running, Failed, Skipped, Not started, or Paused before it) ends with a
  Breakpoint toggle (a button, `aria-pressed`, named "Breakpoint before block 2.1" whatever its state; Tab reaches it,
  Space or Enter presses it). A press sends the run's whole set, in the pinned tree's order (`PUT …/breakpoints`); the
  toggles show the set on its way, then the one the server wrote, and a later pass pauses there (from the next block
  the run starts). The toggles show only once the hub says the run's environment is not production (hidden while the
  scenario reads), and never once the run ended done or cancelled. A scenario that no longer reads (an edit broke the
  file) or whose environments do not name the run's offers them, and Step and Continue, leaving it to the server's
  refusal (409 `workflow-run-debug-production` on production), so a paused run always has a Continue. While a change
  is on its way, the toggles are off but keep focus (`aria-disabled`).
- **Step and Continue** show only in a debug pause, in its bar above the blocks (where the investigation's banner
  sits), under the toggles' production rule: Step (`POST …/step`) runs the next block and pauses before the one after
  it; Continue (`POST …/continue`) runs to the next breakpoint or the end. After a press: "Step sent: the scenario
  run goes on, and its events update this page." and both stay off (`aria-disabled`, so the pressed one keeps focus)
  until the run leaves that pause; a refusal shows only in the pause it was sent from. When the bar leaves (the run
  resumed), focus that left with it goes to the page's heading. Cancel stays in the header. The page's announcer
  says "Scenario run paused before block 2.1" once, and the header badge reads Waiting for you.
- **AC-507.16 Values while paused.** While the run is paused (a debug pause, an investigation waiting for its answer,
  an open ask) and off production, the Facts column adds "Values while paused" (`GET …/values`, with the launch
  cookie): the run's inputs, environment values included, then each finished block, folded until opened (its address
  and label, node, status and poll count; inside: With, Output and, for a Wait until, Last poll). Captures stay in the
  facts above. Credential marks are `RedactionChip`s. A graph run's nodes show by id. The values are read again
  once another block has ended; the values shown stay until that read lands, so what was opened stays open. A
  value taller than its box (240 px) scrolls inside it.
- **AC-507.18 Pinned tree.** Given a builder edit while a run is paused, then the run page's blocks, toggles and bar
  are still the pinned tree's: an address the file no longer holds keeps its row and its toggle.
- **On the scenario page** (since AGH-596 the one screen; there is no Run mode), each block row of a `version: 2`
  scenario carries a Breakpoint button ("Breakpoint before block 1.2 (b)"; `b` on the focused row toggles it). Before
  a start, the start passes the toggled blocks the file holds now, in its order (`breakpoints`), and its confirm says
  "It pauses before block 1.2, its breakpoint."; a production environment offers no toggle and passes none. While a
  live scenario run off production is shown, the rows show the run's own set, pressed, and a toggle writes the run's
  whole set to it (`PUT …/breakpoints`). The run strip names a debug pause ("is paused before block 2.1 at its
  breakpoint, in personal") and the held block reads "Paused before it".

| State | Copy |
|---|---|
| Debug pause (breakpoint) | "Paused before block 2.1 (Do: queue-send), at its breakpoint." |
| Debug pause (step) | "Paused before block 2.2 (You: Check the review, then approve.), after a Step." |
| Sent | "Step sent: the scenario run goes on, and its events update this page." (or Continue) |
| Production | Blocks: "Breakpoints are off: live is a production environment." · bar: "Step and Continue are off: live is a production environment. To go on without stopping at breakpoints, resume it from a terminal:" `./hub workflow run --resume 3f2a91c0`; no values are read |
| Container (404 `run-control-off`) | "Breakpoints cannot be set from the agent-hub container. Set them from a terminal:" `./hub scenario break 3f2a91c0 --set 2.1 2.2` · "Step and Continue cannot be sent from the agent-hub container. Run hub web on your machine, or from a terminal:" `./hub scenario step 3f2a91c0` · "Values cannot be read from the agent-hub container: run hub web on your machine." |
| Locked (401) | "Debugging is locked in this browser. Open the link hub web printed when it started (it ends with ?token=…) once in this browser." |
| Refused (409, 422) | "Could not set the breakpoints" / "Could not send Step" and the server's detail |
| Not paused (values 409, the server's rule: an ask counts once its pass is held) | "The scenario run is not paused right now: its values show while it is paused." |

## Responsive

Built: at 1280 and wider nothing hides on the detail, and the chat and the options sit side by side. The Scenarios
list hides its Steps column below 1280 px, and its last run's time below 1100 px (AC-596.1.13). The detail's columns
narrow below 1600 px, and below 1440 px the left column gives way while a step is open (AC-521.13.2). On a tablet
(768–1279) the detail plans but Start's place in the run bar says "Starting a scenario run needs a desktop screen."

Not built yet (AGH-458), the target:

| Width | Scenarios | Detail | Scenario run |
|---|---|---|---|
| ≥ 1600 | as drawn | as drawn | chat 1fr, options 560 |
| 1280–1599 | all columns (built) | as built, above | chat ≥ 480, options 440; facts fold under the timeline |
| 1100–1279 | Steps hides (built) | columns by priority; Start off (built: the desktop line) | options first; the chat opens in a `SidePanel` |
| 768–1099 | Steps and the last run's time hide, the row's head wraps (built) | same | same |
| < 768 | "This view needs a wider screen." | same | same |

## Accessibility

Each table has a caption that names its subject. Every status and decision is icon + label. The Scenarios list is a
list named Scenarios whose rows are one tab stop each, with a spoken label (name, description, project, pack, steps
and last scenario run). On the scenario page the open step is a named group ("Step N settings") inside its tree item;
its editable values are Tab stops named by what they edit ("Edit <name>: <value>"), a body's scrolling code is
focusable and named ("<name>, as JSON"), and "Needs a value" is said with an icon and words. A service input's list is
a dialog with a search box and a list of options under group headings. On the Graph of a scenario written as blocks,
stages are regions, If, At the same time and Repeat are groups, and cards are buttons. A Breakpoint toggle is a
button whose name stays the same and whose state is `aria-pressed`, in the accent color when pressed (a set
breakpoint is not a status). The debug bar and the blocks are named regions; the values are a named complementary
landmark, like the facts. Each finished block's values are a `details` disclosure (closed by default), and each of
its With, Output and Last poll is focusable and named ("Output of 1.2"; a graph run's "Output of
order-processed"), since it can scroll. A toggle, Step or
Continue that is off while a press is on its way is `aria-disabled`, so focus stays on it; when the debug bar leaves,
focus goes to the page's heading. A refused option's
reason is linked by `aria-describedby`. The verdict, the pause, the answer and the end are announced once, politely. Dialogs
open on their safe button and return focus. axe has no serious or critical violation (`npm test -- -t a11y`).

## UX principles applied

Human decides (principle 2): the pause and the answer bar sit above the fold, waiting amber, and every write is
confirmed with its environment. Show only what the record shows (principle 3): run-time values stay placeholders, and
a gate's kind comes from the record. Privacy (principle 5): credential marks are `RedactionChip`s. Honest limits: the
agent's limits sit beside its chat, and the best-effort sentence sits on Run detail. Plain language: each line names
the step, the environment and the reason. The debugger (§ Debugging a run written as blocks) shows the run's own
record: the blocks it pinned, never the file as it reads now, and its values with credential marks as
`RedactionChip`s; it decides nothing for the person (Step and Continue answer no gate, edit no value), and it is off
on production, where the bar names the terminal command instead.

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
