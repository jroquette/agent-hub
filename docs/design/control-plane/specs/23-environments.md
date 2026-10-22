# Environments

**Phase:** P2 shell + ADR 0040 writes · **Routes:** `/environments` (project picker),
`/projects/:project/environments`, `/projects/:project/environment/:name` (`?service=<repo>/<name>` opens the service
panel), `/projects/:project/environments/new`, `/projects/:project/environments/services/new[?repo=]` · **Answers:**
"Where do this project's systems run, what may agents do in each, and how do I fix any of it where it is shown?"

The screens of the declared environments and services (contract: [environments.md](../../environments.md), its
"From hub web" section and AGH-416's API). For a developer who is not an infra person: environments, access and
addresses above the fold, and the action that matters is changing the one wrong thing where it is shown. The UI says
**address**, never endpoint (`endpoints` stays the `hub.json` key). Every write goes through
`POST /projects/{project}/config/environments`: `hub.json` (the team's, left uncommitted with a notice to run
`./hub sync` and open a hub PR) or `hub.local.json` (only me, never committed; it may add its own environments and
only make a team environment stricter).

Built from the playground's UX designs v2 (overview, setup flows), v3 (environment page, service panel) and the Hub
config change (AGH-417, in parts: the address display, then these screens, then the add flows of section 6 with
their acceptance criteria); the find-services part of v3 is AGH-418.

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
