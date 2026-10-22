# Environments

**Phase:** P2 shell + ADR 0040 writes · **Routes:** `/environments` (project picker),
`/projects/:project/environments`, `/projects/:project/environment/:name` (`?service=<repo>/<name>` opens the service
panel), `/projects/:project/environments/new`, `/projects/:project/environments/services/new[?repo=]`,
`/projects/:project/environments/discover[?discovery=<id>]`, `/projects/:project/environments/discover/:discoveryId` ·
**Answers:**
"Where do this project's systems run, what may agents do in each, and how do I fix any of it where it is shown?"

The screens of the declared environments and services (contract: [environments.md](../../environments.md), its
"From hub web" section and AGH-416's API). For a developer who is not an infra person: environments, access and
addresses above the fold, and the action that matters is changing the one wrong thing where it is shown. The UI says
**address**, never endpoint (`endpoints` stays the `hub.json` key). Every write goes through
`POST /projects/{project}/config/environments`: `hub.json` (the team's, left uncommitted with a notice to run
`./hub sync` and open a hub PR) or `hub.local.json` (only me, never committed; it may add its own environments and
only make a team environment stricter).

Built from the playground's UX designs v2 (overview, setup flows), v3 (environment page, service panel) and the Hub
config change (AGH-417, in parts: the address display, the screens, then the add flows of section 6); the
find-services part of v3 is section 7 (AGH-418).

## One place per verb

| | Environment | Service | Address |
| --- | --- | --- | --- |
| Read | Environments row → environment page | Environment page row → service panel | Environment page row, service panel |
| Create | Add environment flow | Add service flow | Service panel input |
| Change | Environment page section "Change" → in place → "Save {section}" | Service panel → "Save changes" | Service panel input |
| Remove | Environments row "Remove", environment page "Remove environment" | Service panel "Remove service" | Service panel row `x`, applied on "Save changes" |

## 1 · Environments `/projects/:project/environments`

```
Portfolio › demo › Environments
Environments                                    [Ask Claude about environments] [+ Add environment]
Where this project's systems run, what agents may do in each, and how to reach each repo's services there.
Environments 3
┌Environment──────────┬What agents may do─────────┬Secrets──────────────┬Services──┬Set by──┬────────────────┐
│staging              │◇ Agents ask before writing│▤ env file …/.env.st…│3 services│👥 Team │💬 Remove   ›  │
│Shared test env      │                           │  AWS profile tip-stg │          │        │                │
│production [⛨ Prod]  │🔒 Agents only read         │None yet              │None yet  │👥 Team │💬 Remove   ›  │
└─────────────────────┴───────────────────────────┴──────────────────────┴──────────┴────────┴────────────────┘
ⓘ agent-hub's own scripted actions follow this access strictly. Commands an agent types itself …
```

- The sidebar's **Work** group ends with Environments (`server`): the project open, else the one in scope, else
  `/environments`, a project picker (the shared `KnowledgeProjectIndex`). The add flows sit under the page's path, so
  the sidebar keeps Environments marked while one is open.
- One h1, one primary (**Add environment**; with no environment the empty state holds it), "Ask Claude about
  environments" beside it (off with the `AskBlocked` reason when sessions cannot start).
- The list is the shared `DataTable`: the whole row opens the environment's page (click or Enter), the name is a
  plain link, the row's Ask Claude and Remove ("Use team's" on a team environment I tightened) keep their own clicks.
  Columns: Environment (mono name, `ProductionBadge`, description), What agents may do (icon + words, "Team: …" when
  I tightened it), Secrets (env file, variable names, AWS profile, by name only; "None yet"), Services (how many have
  an address there), Set by (`ConfigSource`: Team, Yours, Tightened by you).
- Empty: `EmptyState` `server` "No environments yet" with "Add environment" and the command
  `./hub env add local --access write --local`.
- The Hub config screen keeps an **Environments** section with one summary row ("3 environments · 4 services") and
  "Open Environments"; its local-settings dialog points there.

## 2 · Environment page `/projects/:project/environment/:name`

```
Portfolio › demo › Environments › staging
staging [⛨ Production] [👥 Team]                          [Ask Claude about staging] [Remove environment]
┌ main (minmax 0,1fr) ───────────────────────────────────┐ 24 ┌ rail 320 ───────────────────────┐
│ What agents may do                          [Change]   │    │ What your agents read  (Preview) │
│ Secrets for scripted actions                [Change]   │    │ Every session reads this: …      │
│ Description                                 [Change]   │    │ ◇ Agents ask before writing      │
│ Services in staging 3                  [+ Add service] │    │ ▣ 3 services with an address     │
│ 📖 Demo_API                                          │    │ ▸ Show the services as the brief │
│ api · API or backend   https://api.stg.example.com  ⧉ ›  │    │   lists them                     │
│ ▸ 2 services not in staging yet                        │    │ Agents never see secret values … │
└────────────────────────────────────────────────────────┘    └──────────────────────────────────┘
```

- The route is singular so an environment named `new` never clashes with the add flows.
- Header: mono name, `ProductionBadge`, `ConfigSource`; "Ask Claude about {name}"; "Remove environment" (ghost), or
  "Use the team's access" for a team environment I tightened. An unknown name: "No environment called …".
- **Sections change in place, one at a time**, with the add flow's rows and words: *What agents may do* (a team
  environment first asks "Change it for": the whole team, saved in `hub.json`, or only me, saved in
  `hub.local.json` and only stricter; looser rows and "This is production" are off under only me with the reason);
  *Secrets for scripted actions* (where they live, below); *Description* (≤ 80). "Change" swaps the body for a form,
  Save is then the one primary, Cancel or `Esc` go back, and the other "Change" buttons say "Save or cancel the …
  change first.". A refused save shows the server's reason under the form and keeps it open.
- **Services in {name}**, grouped by repo: name, kind, the address here (see Addresses), set-by-you and note icons,
  a copy button; a row opens the service panel. The project's other services fold below ("not in {name} yet"), each
  opening the panel to give it an address here.
- **What your agents read** (rail, sticky and never taller than the view; under the main column below a 1100 px
  container): a plain title and `DerivedLabel` "Preview"; who gets it (every session through AGENTS.md and the brief,
  or only my sessions for my own environment); the access and how many services have an address; the brief's service
  lines folded behind "Show the services as the brief lists them", with their 60-line / 2000-character limit; "Agents
  never see secret values or the env file's contents."

## 3 · Service panel

The shared `SidePanel` (non-modal, no scrim; overlays the page below 1600 px and docks beside it from there; `Esc` and
the X close it, focus returns to the row that opened it), titled `repo › service`, its body:

- Kind (native select of the service kinds) and Description (optional, ≤ 80).
- **Addresses**: one row per environment (mono name, access icon and words, `ProductionBadge`, a mono input with an
  example address); the environment the panel was opened from is focused. A row set in `hub.local.json` says "Yours,
  in hub.local.json". `x` strikes a row through as "Removed on save" with "Undo". "Never a password: a URL takes no
  user or token."
- Footer: "Remove service" (confirmed: "Its N addresses go too. Agents stop seeing where it runs.", plus the hub PR
  line for a team service), the change count, Cancel and "Save changes" (off until something changed). Every change is
  one batch: both files written or neither. Closing with changes asks "Discard N changes?".

## 4 · Remove

| What | Confirm (`ConfirmDialog`) | After |
| --- | --- | --- |
| Environment, unused | "Remove environment {name}?" · "Agents stop seeing {name}." (+ team: the hub PR line) | Back to Environments, focus on Add environment, toast |
| Environment in use | "Remove {name} and its N addresses?" with each `repo › service · address`; one write | same |
| Team environment I tightened | "Use the team's access for {name}?" | The page stays |
| Service | "Remove {repo} › {service}?" | Panel closes, toast |
| One address | none: "Removed on save", undoable until Save | Save toast |

## 5 · Where an environment's secrets live

Asked in the add flow and in the page's Secrets section, by name only, never a value:

- **In an env file** (Recommended) · "Env file path" relative to the folder holding the hub and its repos. hub web
  lists the file's variable **names** (`GET /projects/{project}/env-file-keys`, [scenarios.md](../../scenarios.md)):
  "Actions will get these N variables:" (12 then "and N more"); "No file there yet." when missing; a warning when git
  does not ignore it; the reason when it is not read (outside the hub and its repos, through a link, not a regular
  file, over 64 KiB).
- **In my shell** · "Variable names", names only; a line holding a value (`NAME=…`) is refused before going on.
- **Not yet**. Then "AWS profile (optional)": the profile name in `~/.aws/config`, never its keys.

A team environment's secrets are the team's: saving changes `hub.json`.

## 6 · Add flows

Adding an environment or a service is its own page under the Environments path, one question per step, opened from
the Environments page or the environment page and returning there (only within the project) with "Added {name}" and,
for a `hub.json` write, the uncommitted notice.

- **Frame** `184px minmax(0, 640px) 264px` (container fallbacks: the preview under the card below 1135 px, one column
  below 879 px; no min-height): the step list (each done step shows its answer and leads back to it), the card (h2
  question, help, the choices, Back · blocked reason · Cancel · Continue), and a live preview of what agents will read
  and where it lands. Every choice is a one-column list of `OptionRow`s with an icon (no orphan tile at any count);
  a field sits inside the choice that asks for it. Cancel past the first step asks to discard the answers.
- **Add environment**: kind (This machine, Test or staging, Production, My own copy, Something else: it fills name,
  access, production and who it is for), name and description (a name another environment has, ignoring case, is
  refused), what agents may do (+ "This is production"), who it is for (the whole team: `hub.json`; only me:
  `hub.local.json`), where its secrets live (section 5), review with what happens next.
- **Add service**: what runs (API or backend, Frontend or portal, Database, Queue or topic, Storage bucket, Function
  or job, Something else), which repo and its name, its address in each environment in one list, review. With no
  environment the card says to add one first.

## 7 · Find services with Claude

A read-only Claude session reads the picked repos and proposes environments, services and their addresses; the
person reviews each proposal and adds the ones they pick ([ADR 0046](../../../adr/0046-read-only-discovery-sessions.md),
contract in [environments.md](../../environments.md#discoveries)).

```
Services in staging 3                          [⌕ Find services with Claude] [+ Add service]
```

- **Entry**: the environment page's services head, "Find services with Claude" (secondary, `folder-search`) before
  Add service; off with the reason in a tooltip when sessions cannot start (the container, no `claude`).
- **Start** `…/environments/discover`: h1 "Find services with Claude", the intro "Claude reads the repos' config and
  proposes environments, services and their addresses. It changes nothing: you review each proposal and choose what
  to add." One card: "Which repos should Claude read?" (a `book` `OptionRow` per repo, all checked; none checked
  blocks the start, "Pick at least one repo."), "Which environments should it look for?" (each declared environment
  with its access icon and words, all checked, then "Suggest environments we have not declared"), a "What Claude
  reads" disclosure (the files it looks at; never `.env` files or a file the guard blocks; it can only read) and the
  honest line "Claude reads code, not your AWS account." Cancel goes back; the primary **Find services with Claude**
  is the consent: the session starts on the click.
- **Progress** (same route, `?discovery=<id>`, polled every 3 s while running): "Claude is reading N repos" with a
  live "Reading" badge and the session's cost so far, the scope line, "Open the conversation" and **Stop** (ends the
  session). Finished: a "Finished" badge, a line counting what was found (new, different from yours, probably
  missing) and the primary **Review N proposals**. Stopped: "Stopped before Claude sent its proposal. Nothing was
  written." and Start again. Failed: `ProblemError` "Claude could not finish reading the repos" · "{reason}. Nothing
  was written." with a retry that opens the form again.
- **Review** `…/environments/discover/:discoveryId`: h1 "Review what Claude found" with the "Proposed by Claude"
  label, the repos read and "Open the conversation", Discard proposal (a confirmation: "The items you did not add are
  dropped. Nothing in hub.json changes."). A `SegmentedControl` filters All · New · Differs · Already declared. One
  table, caption "Proposals from Claude": a checkbox, What, Details, Found in (each evidence `path:line` with a copy
  button) and Status (the server's: `plus` New, `git-compare` "Differs from yours" with yours, `check` Already
  declared), grouped Environments, then Services by repo. New rows start checked; production environments and
  differences wait for the person; already declared rows cannot be picked. A service whose environments are neither
  declared nor selected says so and is skipped. "Probably missing" lists what Claude could not find a definition for,
  each with Add by hand (the Add service flow for its repo); "Not read" and "Left out by agent-hub" list the files it
  skipped and the items the server dropped, with the reason. A sticky bar counts the selection, Select all new,
  Clear and **Add N for the team**: one batch to `hub.json` (environments first), then "Added …" and the uncommitted
  notice; a refusal shows its reason in the bar and keeps the choices.
- **Banner**: while the newest discovery runs, the Environments page shows "Claude is reading the repos for
  services." with Open progress; once it has finished and is not discarded, "Claude found N items in the repos." with
  Review N proposals. A stopped or failed one shows nothing.

## Addresses and other long values

A service's address is shown **whole when it fits**; else it is cut in the middle with an ellipsis, its last 18
characters (the host's end) always whole, the whole address in a tooltip while it is cut, and a copy button beside it.
The cut follows the box as it is resized (the browser measures it, not a character count). The shared `FitText`
component does it; the chat's files list uses it for its root line, folders and file names (the extension stays
whole, the whole name in a native title).

## States

| State | Environments / environment page | Service panel | Add flows |
| --- | --- | --- | --- |
| Loading | `Skeleton` blocks | — | Shell real, card skeleton |
| Empty | No environments: `EmptyState` above; no services: "No services yet. Add the API, portal or database each repo runs." | — | Add service without environments: "Add an environment first" |
| Error | `ProblemError` ("Could not read this project's hub.json" … "Run ./hub doctor in the hub for the line to fix."); unknown environment | Refusal under the fields, `role="alert"` | The refusal in the card, answers kept |
| Stale | A file changed on disk since it was read is refused; the config reloads and says so | same | same |
| Broken hub.local.json | Warning `Banner` with "Ask Claude to fix it"; only the team's environments show | — | Only me off with the reason |

Find services with Claude: loading is a `Skeleton`; a review with nothing to add is the `EmptyState` "Claude found
nothing new"; an unknown or discarded discovery is `ProblemError` "No such search"; sessions off disable the
primary with the reason.

## Accessibility

Access, production and "Removed on save" are icon + words, never colour alone; each choice list is a `fieldset`
with a visually hidden legend; rows that open are keyboard reachable (Enter); copy and remove buttons name their
target ("Copy the address of Demo_API › api in staging", "Remove the staging address"); every screen passes the
axe check (`npm test -- -t a11y`).

## Departures from the UX designs

- Rename of an environment or a service in place (v3 B1/B3) is not built: the API renames (AGH-416), the screens
  do not yet.
- The service panel is main's shared `SidePanel` (docks from 1600 px) rather than the agent-session drawer the
  design named.
- A service's address on the environment page is shown whole when it fits, else cut in the middle (FitText, below),
  not `PathText` at a fixed character count.

- Find services with Claude (v3 section 5) is built without: per-repo progress and partial results (the proposal comes
  with Claude's final reply, so progress is the session's state, cost and conversation), editing a row before adding
  it, "Only me" (proposals go to the team's `hub.json`), the Added status and "N proposals left" after an apply, and
  the evidence line's disclosure (the `path:line` with a copy button). The entry is on the environment page's
  services head; the Environments page has no services head since v3's later table, so it shows the banner only.

## Acceptance criteria (AGH-417)

- **AC-417.1** Given a long value in a box of any width, when `FitText` renders it, then the whole text is on the
  line, its `tail` characters in a part that never shrinks and the rest cut in the middle when it does not fit, with
  the whole text as a native title; with `tooltip`, the whole text shows in a tooltip only while the line is cut. The
  chat's files list shows its names this way (the extension whole).
- **AC-417.2** Given a project, when the sidebar's Work group is read, then it ends with Environments, which goes to
  the project open, else the one in scope, else the `/environments` project picker; the add flows keep it marked.
- **AC-417.3** Given environments, when the Environments page opens, then it has one h1 with Add environment as its
  primary and Ask Claude beside it, and lists each environment in a table with what agents may do (in words and
  icons), its secrets by name, how many services have an address there and who set it; with none, an `EmptyState`
  holds Add environment.
- **AC-417.4** Given the environments table, when a row is clicked anywhere or focused and Enter pressed, then the
  environment's page opens; its name is a plain link, and its Ask Claude and Remove buttons do their own thing without
  opening it.
- **AC-417.5** Given an environment some addresses use, when it is removed, then one confirmation lists each address
  that goes with it and one write removes them all; going back to the team's looser access asks first.
- **AC-417.6** Given an environment, when its page opens, then it shows what agents may do, where its secrets live
  and its description, its services grouped by repo with their address there and the others folded below; an unknown
  name says it does not exist.
- **AC-417.7** Given the environment page, when a section's Change is pressed, then that section turns into the add
  flow's rows in place while the others are locked; a team environment asks whether to change it for the team
  (`hub.json`) or only me (`hub.local.json`, only stricter, production off); secrets are saved by name only; a
  refused save shows the reason under the form and keeps it open.
- **AC-417.8** Given a service, when its row is opened, then a side panel changes its kind, description and every
  address at once, saved as one batch; a removed address is struck through and undoable until Save; Remove service
  asks first; closing with changes asks to discard them; focus returns to the row.
- **AC-417.9** Given the environment page, when the agents panel is read, then it says plainly who gets what agents
  read, the access and how many services have an address, folds the brief's service lines behind a disclosure, and
  stays within the view's height.
- **AC-417.10** Given a service with an address in the environment, when its row is shown, then the address is whole
  when it fits, else cut in the middle with its host's end whole, the whole address in a tooltip, and a copy button.
- **AC-417.11** Given the Hub config screen, when its Environments section is read, then it is one summary row
  (environments and services counted) with Open Environments.
- **AC-417.13** Given the Environments page, when Add environment is pressed, then a page asks one question per
  step (kind, name, what agents may do, who it is for, secrets, review) with a step list whose done steps show their
  answer and lead back, and a live preview; the kind fills the name, access, production and who it is for; the review
  says what happens next; adding returns to the page that opened the flow with "Added {name}".
- **AC-417.14** Given the secrets step, when an env file is picked, then only its path field shows and its variable
  names are listed (never a value) and only the path is sent; when the shell is picked, a variable line holding a
  value keeps the flow from going on.
- **AC-417.15** Given an environment name another environment has, ignoring case, when it is typed in the add flow,
  then the flow refuses it before going on.
- **AC-417.16** Given environments, when Add service is used, then it asks what runs, which repo and its name, and
  its address in each environment in one list, and adds the service with each address in one write; with no
  environment it sends people to add one first.
- **AC-417.17** Given an add flow opened from a page, when it finishes or is cancelled, then it goes back to that
  page, only within the project (else the Environments page); every choice is a one-column list of icon rows, and
  Cancel past the first step asks to discard the answers.

## Acceptance criteria (AGH-418)

The API's are AC-418.1 to AC-418.7 ([agent-sessions.md](../../agent-sessions.md#read-only-sessions-agh-418),
[environments.md](../../environments.md#discoveries)).

- **AC-418.8** Given an environment page, when its services head is read, then "Find services with Claude" sits
  before Add service and opens the start form; when sessions cannot start, it is off with the reason.
- **AC-418.9** Given the start form, when it opens, then every repo and declared environment is checked and
  "Suggest environments we have not declared" is on; with no repo checked the start is blocked with "Pick at least
  one repo."; pressing Find services with Claude posts the picked repos, environments and the suggestion choice at
  once and shows the progress of the new discovery.
- **AC-418.10** Given a discovery, when its progress is shown, then a running one says Claude is reading with its
  cost so far, Open the conversation and Stop; a finished one counts what was found and offers Review N proposals; a
  stopped one says nothing was written and offers Start again; a failed one shows the reason and that nothing was
  written.
- **AC-418.11** Given a finished discovery, when it is reviewed, then each environment and service shows what was
  found, where (`path:line`, copyable) and the server's status; new rows start selected, production environments and
  differences wait for the person, already declared rows cannot be picked, and the filter shows one status at a time.
- **AC-418.12** Given selected proposals, when Add N for the team is pressed, then one batch adds them to `hub.json`,
  environments first, a new service with only the addresses whose environment is declared or selected (a service left
  with none is skipped and says why), a different address replaced in its environment's file, then "Added …" and the
  uncommitted notice show.
- **AC-418.13** Given a proposal, when it lists probably missing items, files not read or items left out, then each
  shows its reason, and a missing service offers Add by hand in its repo; Discard proposal asks first and goes back to
  the Environments page.
- **AC-418.14** Given the newest discovery of a project, when the Environments page opens, then a running one shows a
  banner with Open progress and a finished one a banner with Review N proposals; a stopped or failed one shows none.
- **AC-418.15** Given the playground's dev proxy, when the web app calls a project's `environment-discoveries`
  routes, then they go to the server that drives the sessions, as `/api/v1/agent-sessions` does (ADR 0036).
