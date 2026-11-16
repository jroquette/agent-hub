# Hub config · Repositories: add, change and remove a repo

**Status:** approved by the owner on 2026-10-27 (AGH-578, plan task 2.5), with O1–O5 as answered below. · **Phase:** P2 + ADR 0040 hub writes · **Route:** `/projects/:project/config#repositories`
(`?repo=<dir>` opens that repo's card; unchanged) · **Answers:** "Which repos does this hub manage, and how do I add
one, fix one or drop one without editing hub.json by hand?"

The Repositories section of the Hub config screen, which is read-only today, gets add, change and remove. The
contract is the `hub-repos` feature spec (D-api, D-web, AC-6): every write is
`POST /api/v1/projects/{project}/config/repos` with `op` `add_repo`, `set_repo` or `remove_repo`. The API and
`hub repo` call the same core use case, so they accept and refuse the same changes with the same messages. The
change is written to `hub.json` and left uncommitted, like the environment writes
([ADR 0040](../../../adr/0040-hub-web-keeps-local-settings-writes-hub-files-and-runs-checks.md),
[23-environments.md](23-environments.md)). hub web never clones, fetches, syncs or deletes a folder.

There is no screen spec for Hub config. Its existing behaviour is the code (`apps/web/src/screens/hub-config/`) and
AC-382.27 to AC-382.37 ([19-brain-and-skills.md](19-brain-and-skills.md)). This file covers only the Repositories
section. The README's Departures still win over it.

## What changes

| Part | Before | After |
| --- | --- | --- |
| Section head | Title, purpose, "Ask Claude to change the repositories" | Same, plus **Add repo** (default button, `plus`) after the Ask button |
| Repo card body | Read rows: Default branch, Branch, Commit title, PR title, Fast check, Full check | An action row first: **Change** and **Remove** (ghost, `x`), then the same read rows |
| Change | None: "Ask Claude to change …" per row | The card's rows are replaced in place by the repo form, as the Environment page's sections do |
| Add | None | A "New repo" form card at the end of the list, where `hub.json` will add the repo |
| Remove | None | `ConfirmDialog`. If the server refuses, the dialog stays open and lists one line per reference |
| After a save | Not applicable | Toast "Added repo {dir}" / "Updated repo {dir}" / "Removed repo {dir}", plus the shared `UncommittedNotice` with that write's next-step lines |
| Header primary | "Ask Claude to change the config" is always primary | It shows as a default button while a repo form is open, so Save is the one primary (O2) |
| `UncommittedNotice` | Its Ask Claude text says "environment changes" | It says "changes", and the notice can show extra next-step lines (O3) |

## What stays

The rest of the screen: header, breadcrumbs, the "Where values come from" card, the rail and its per-repo sub-links,
the other sections, "Change my settings" and its dialog, every row's Ask button, the who-set-it labels and the
`?repo=` deep link. A repo's `services`, `conventions` and `ui_paths` are not edited here: services stay on
Environments, and conventions and UI paths stay with Ask Claude. No new route: the forms are not in the URL, as the
Environment page's section forms are not.

## Purpose and primary user

The hub's owner or a developer with the hub checked out, adding a repo after `hub init` or fixing a wrong check or
branch. They want to change one repo, see that `hub.json` accepted it, and know what to run next (`./hub sync`, and
after an add `./hub setup` and `/onboard`). The action that matters most in this section is **Add repo**. Inside an
open form it is that form's Save.

## One place per verb

| | Repo |
| --- | --- |
| Read | Repositories section → repo card (the first one opens by default, `?repo=` opens another) |
| Create | Section head "Add repo" → "New repo" form at the end of the list → "Add repo" |
| Change | Card "Change" → the form in place → "Save repo" |
| Remove | Card "Remove" → `ConfirmDialog` "Remove repo" |

Only one repo form is open at a time. While one is open, the other cards' Change and Remove and the head's Add repo
are off. Their tooltip says "Save or cancel the change to {dir} first." (for an add: "… to the new repo first.").

## Layout (1440, sidebar expanded; the same at 1280 with the sidebar collapsed)

Read mode, two repos, the first one open:

```
Repositories ⎇                                  [Ask Claude to change the repositories] [+ Add repo]
Per repo: the base branch, how branches, commits and PRs are named, and the checks the agents run. …
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ▾ 📖 demo-api   app · acme/demo-api                                                              │
│                                                                      [Change]  [× Remove]        │
│ Default branch   main                         👥 Set by the team                         💬      │
│ Branch           roquettejh/{issue}-{slug}    …                                                  │
│ Fast check       make check-fast · timeout 150 s (built-in)                                      │
│ Full check       make check                                                                      │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ▸ 📖 demo-web   web · acme/demo-web                                                              │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Change in place (the card's summary stays and the rows give way to the form, at most 640 px wide):

```
│ ▾ 📖 demo-web   web · acme/demo-web                                                              │
│  Saved to hub.json, the team's file. It stays uncommitted until you open a hub PR.               │
│  The folder cannot change here: remove the repo and add it again.                                │
│  GitHub repo                 [acme/demo-web                    ]  owner/name, e.g. acme/demo-web │
│  Full check                  [make check                       ]                                 │
│  Fast check (optional)       [                                 ]  Empty: no fast check; …        │
│  Fast check timeout (optional)[   ] seconds                       1 to 160. Empty: 150 (built-in)│
│  Role (optional)             [web                              ]  Empty: app.                    │
│  Default branch (optional)   [trunk                            ]  Empty: the project's main.     │
│  Branch, commit title and PR title patterns: ask Claude to change them.                          │
│  ┌ ⓧ This change was not saved ───────────────────────────────────────────┐   (only after a 422) │
│  │ • hub.json: Input should be less than or equal to 160                  │                      │
│  └────────────────────────────────────────────────────────────────────────┘                      │
│                                                Nothing changed yet.   [Cancel]  [Save repo]      │
```

Labels sit above their input, with the help line under the input, as in "Change my settings". The drawing puts them
side by side only to save space. Add: a card after the last repo with the h3 "New repo". It has the same form with
**Folder** first, the intro line "Saved to hub.json, the team's file. hub web does not clone the repo: run ./hub
setup after.", and the footer reason · Cancel · **Add repo**.

### Breakpoints ([31-responsive.md](31-responsive.md); the screen's own container queries)

- **Wide ≥ 1600 and Desktop 1280–1599:** as drawn. The form stays at most 640 px wide inside the card. When the
  Discuss panel is docked the content column narrows, and the container rules below apply.
- **Container ≤ 900 px** (the screen's rule): the rail moves above the sections. The form is unchanged.
- **Container ≤ 640 px:** config rows wrap to two columns (the screen's rule). The card's action row and the form's
  footer wrap, with Save last and the blocked reason on its own line above the buttons.
- **Tablet 768–1279:** best effort. Nothing is hidden or redesigned (see O5).
- **< 768:** the system-wide "This view needs a wider screen." rule. Nothing is added.

## Components

| Component | Use |
| --- | --- |
| `Section` (`parts.tsx`) | Gets an `actions` slot for Add repo after the Ask button. This extends an existing part, not a new component |
| `RepoCard` (screen) | Gets the action row and the form in place of the rows |
| Section form frame (`SectionForm`, `hub-config/parts.tsx`: Cancel, the save verb, the refusal above the actions, Esc cancels, nothing closes while pending) | The repo form's frame, shared with the Environment page's section forms. It gets a `reason` slot (why Save is off) and a `refusal` slot (each form shows its own block) |
| **`RepoForm`** (`new`, screen-local) | The repo fields of add and change, and the rules below. Considered: `SetupFlow`, which asks one question per step, is too heavy for three required fields that the CLI takes in one line; `SidePanel` (service panel) moves the form away from the card it changes and covers the page at 1280; `LocalSettingsDialog` holds "only me" values (`hub.local.json`), and putting team writes in it would blur who set what |
| `Button`, `Tooltip` | Add repo, Change, Remove, Cancel, Save; reasons for buttons that are off |
| `Banner` `tone="error"` `boxed` | The refusal block under the form: `circle-alert`, the title and one line per problem |
| `ConfirmDialog` (danger) | Remove. Its `children` hold the refusal lines when the server refuses |
| `Toast` via `SavedToast` / `useSaveNotices` | What was done |
| `UncommittedNotice` | After any repo write, with the extra lines below |
| `CopyButton` | Already in the notice for `./hub sync`. The added lines are plain text |

Tokens: none new. Cards `radius-lg` on `surface`, `border`. Inputs `.ah-input` (`border-control`, `radius-md`,
`control` height). Mono values (folder, GitHub repo, commands, branch) in Geist Mono. Field gaps `space-1` (label to
input to help) and `space-4` (between fields). Refusal `failed` / `failed-soft` through `Banner`. Focus `focus-ring`.
Targets ≥ `control-sm`. No motion beyond the existing toast.

## Content

Glossary words: **repo**, **hub**. The folder is called "folder" (never "dir" on screen), the gates "Full check" and
"Fast check" as in the read rows.

| Element | Copy |
| --- | --- |
| Head button | Add repo |
| Card actions | Change (accessible name "Change repo {dir}") · Remove (accessible name "Remove repo {dir}") |
| Add form title | New repo |
| Add intro | Saved to hub.json, the team's file. hub web does not clone the repo: run ./hub setup after. |
| Change intro | Saved to hub.json, the team's file. It stays uncommitted until you open a hub PR. · The folder cannot change here: remove the repo and add it again. |
| Folder (add only) | Label "Folder" · help "The repo's folder next to the hub, ../{folder}. Letters, digits and _, joined by . or -." · placeholder `demo-web` |
| GitHub repo | help "owner/name, e.g. acme/demo-web." |
| Full check | help "The command agents run before a PR, e.g. make check." |
| Fast check (optional) | help "The command the Stop hook runs while agents work, e.g. make check-fast. Empty: no fast check; agents stop without one." |
| Fast check timeout (optional) | suffix "seconds" · help "Seconds the Stop hook gives the fast check, 1 to 160. Empty: 150 (built-in)." |
| Role (optional) | help "A word for what the repo is, e.g. api or web. Empty: app." |
| Default branch (optional) | help "The base of its worktrees and PRs. Empty: the project's {project default_branch}." |
| Scope line (change) | Branch, commit title and PR title patterns: ask Claude to change them. |
| Save | Add repo / Save repo · pending "Adding…" / "Saving…" |
| Blocked reasons (beside Save) | "Fill in the folder, GitHub repo and full check." · "Nothing changed yet." · "GitHub repo and full check cannot be empty." · "Fast check timeout: a whole number of seconds." |
| Duplicate folder (add, as typed) | Under Folder: "Already a repo here: {existing} (folders are compared ignoring case)." |
| Refusal block | Title: the problem's `title` ("This change was not saved"), then each problem's `message` on its own line, **as the API sends it** (O1) |
| Changed on disk | "hub.json changed on disk since this page loaded. Nothing was saved. The page now shows the file as it is; check and save again." (`refusalOf`, the environments' words) |
| Repo gone after reload | "{dir} is no longer in hub.json. Nothing was saved." (inline `Banner` warning at the top of the section) |
| No server | "Could not reach the server. Nothing was saved." |
| Remove title | Remove repo {dir}? |
| Remove consequences | "Agents stop working in {dir} after ./hub sync." · with one team service: "Its service goes with it: {name}." · with more: "Its {N} services go with it: {names}." · "../{dir} and its worktrees stay on disk." · "hub.json changes; run ./hub sync and open a hub PR." |
| Remove buttons | Cancel · Remove repo (pending "Removing…") |
| Remove refused | The refusal block in the dialog, one line per reference (e.g. "repo demo-web is still named at guard.ask_before_edit[0]", "repo demo-web is still named in hub.local.json at repos[0].dir"), then **Ask Claude to drop these** (default, `message-square`) |
| Remove off (one repo) | Tooltip "The only repo: hub.json needs at least one." |
| Toasts | Added repo {dir} · Updated repo {dir} · Removed repo {dir} |
| Notice extra lines | After add: "Run ./hub setup to clone ../{dir}." · "Run /onboard to set {dir}'s gates and project rules." After remove: "../{dir} and its worktrees are left in place." · "A teammate whose hub.local.json names {dir} in repos must drop that entry." After change: none (the notice's sync sentence covers it) |

The next-step lines are the CLI's § Texts (plan, O5), in sentence case. The web holds them, because the API returns
only the `HubConfigView`.

## Data mapping

| Shown | Source | When missing |
| --- | --- | --- |
| Cards, values | `GET /projects/{p}/config` → `repos[]` (`dir`, `github`, `role`, `default_branch` {value, source}, `check_fast`, `check_fast_timeout`, `check`) | The section's existing error and loading states. `hub.json` always has ≥ 1 repo |
| Change form's starting values | The same `RepoConfigView`. Default branch starts filled only when its `source` is `repo`, else empty with the project's value in the help. Fast check empty when `null` or `""`. Timeout empty when `null` | — |
| Project default branch | `view.default_branch.value` | Help reads "Empty: the project's default branch." |
| Duplicate folder | `view.repos[].dir`, compared ignoring case | — |
| Remove's services line | `view.environments.services` where `repo` = {dir} and the source is `hub.json` | Line left out when there are none |
| Remove off | `view.repos.length === 1` | — |
| Write | `POST /projects/{p}/config/repos`. **add**: `{op: "add_repo", dir, github, check}` plus each optional field that is not empty. **change**: `{op: "set_repo", dir}` plus only the fields that differ from the starting values; a cleared optional field goes in `unset` (`role` only when the shown role was not `app`, since empty already means `app`). **remove**: `{op: "remove_repo", dir}`. Text inputs have `maxlength` 200 (the body bound) | — |
| After 200 | The returned `HubConfigView` replaces the cached config (`setQueryData`) | — |
| 422 problems | `errors[]` `{pointer, message}`. A pointer `repos[<i>].<key>` also marks its field (`dir`→Folder, `github`, `check`, `check_fast`, `check_fast_timeout`, `role`, `default_branch`). Other pointers (`guard.…`, `events[…]`, `modules.contract-sync.…`, `hub.local.json` ones, `$`) are listed only | A 422 without `errors`: title and `detail` |
| "Changed since" | A problem whose message holds "changed since" → the config is reloaded | — |

## Interactions and keyboard

- **Add repo** opens the "New repo" card at the end of the list, scrolls it into view and focuses Folder. **Change**
  opens the form in the card and focuses GitHub repo.
- `Enter` in a field submits when Save is on. `Esc` pressed inside the form cancels it unless a save is pending or a
  dialog or panel is above it; `Esc` elsewhere (the Discuss panel) leaves it open. While the form is open its card
  stays open: its summary does not fold it. Cancel and `Esc` do not ask, matching the Environment page's section forms; the form is one screen
  of fields.
- Tab order: the section head (Ask, Add repo) → cards. Inside a form: fields top to bottom → Cancel → Save. The
  refusal block is not in the tab order, except "Ask Claude to drop these" in the remove dialog.
- **Focus after:** Cancel an add → Add repo. Cancel a change → that card's Change. Added → the new card's summary,
  opened (`?repo={dir}`, replace). Updated → the card's Change. Removed → Add repo, and `?repo=` is dropped if it
  named the removed repo. A refusal leaves focus where it was (on Save, which stays focusable while pending through
  `aria-disabled`; if focus was lost meanwhile, it goes to Save); the alert announces it.
- **Changed on disk:** the config reloads and the form stays open. Fields the person did not touch take the new
  values, and touched fields keep what they typed, so Save never undoes a change someone else made to another key.
  If the repo being changed is gone, the form closes and shows the "no longer in hub.json" line, which can be
  dismissed and goes away with the next save or remove.
- **Remove:** Remove opens the dialog. Confirm sends the write. A refusal keeps the dialog open with the lines, and
  Remove repo stays on, so the person can fix the files and try again. "Ask Claude to drop these" closes the dialog,
  attaches the lines as a reference (source `hub.json`) and opens the Discuss panel. It is off, with the reason, when
  sessions cannot start (`AskBlocked`).
- No new shortcuts ([01-navigation.md](01-navigation.md) keyboard map: `Esc` closes the topmost layer).

## States

| State | Section | Form | Remove dialog |
| --- | --- | --- | --- |
| Loading | The screen's existing `Skeleton` (no change) | Opens from loaded data; no loading of its own | — |
| Empty | Not possible: `hub.json` needs ≥ 1 repo. One repo: Remove off with its reason | Add: every field empty, Save off with "Fill in the folder, GitHub repo and full check." Change: starting values, Save off with "Nothing changed yet." | — |
| Saving | Other repo actions off | Save "Adding…"/"Saving…", Save and Cancel off, `Esc` ignored | "Removing…", nothing closes it |
| Refused (422) | — | The refusal block under the fields, `role="alert"`, the form kept open with every value, fields named by a pointer get `aria-invalid` | The block in the dialog, one line per reference, the dialog kept open |
| Stale (changed on disk) | Config reloads | The changed-on-disk line; untouched fields refreshed | The same line |
| Offline / no server | — | "Could not reach the server. Nothing was saved." | same |
| Success | Toast; the `UncommittedNotice` (persistent until dismissed) with the write's extra lines; the notice keeps one line set per added or removed repo since it last opened | Closes | Closes |
| Broken `hub.local.json` | The screen's existing warning banner | A write that the cross-file check refuses shows the server's `hub.local.json` lines verbatim | same |
| Config unreadable | The screen's `ProblemError`; no repo actions | — | — |
| First run | A hub from `hub init` has one repo: its card, Change on, Remove off | — | — |

## Accessibility

- Each form is a `<form>` named by its heading (the card's repo name, or "New repo"). Every input has a `<label>`,
  `aria-describedby` to its help line, and `aria-required="true"` for Folder, GitHub repo and Full check (no native
  `required`, so no browser bubble). "(optional)" is part of the label text.
- A field named by a refusal gets `aria-invalid="true"` and its `aria-describedby` also points at that problem's line.
- The blocked reason beside Save is visible text with `aria-live="polite"`, not only a tooltip.
- The refusal block is `Banner` error: `circle-alert` icon, a title and words, `role="alert"`, so it is never
  conveyed by colour alone. The lines are a list.
- The card action row's buttons name their repo ("Remove repo demo-web"). The `<details>` summary keeps no buttons
  inside it.
- Off buttons with a reason use the screen's existing `Tooltip` pattern. The one-repo Remove reason is also in the
  card for screen readers through its accessible description.
- The timeout input is `inputmode="numeric"` text, not `type="number"`.
- The screen's axe test runs with the add form, a change form, a refusal and the remove dialog open (plan 2.10).

## UX principles applied

| Choice | Why |
| --- | --- |
| Change in place inside the card, one form at a time | H6 recognition: the values being changed stay where they were read; 23-environments "sections change in place, one at a time" |
| Add form at the end of the list | H2 match: `hub.json` appends the repo there, so the card appears where the form was |
| Required fields first, optional ones marked "(optional)" with what empty means | H5 error prevention, H6; content fundamentals |
| Save off with a visible reason; duplicate folder caught as typed | H5; AC-417.15's precedent |
| Server messages shown as sent, each on its own line, form kept | Spec D-web; H9; one set of messages for CLI and web |
| Changed-on-disk reload that keeps only touched fields | H5, H3: no silent overwrite of someone else's change |
| Remove confirms with the verb and what goes with it; refused remove names each reference and offers the one fix | H3, H9; principle 2 (human decides) |
| Uncommitted notice with the next commands, not a toast | Toasts only for results; the next steps must persist (H1, alarm fatigue rule) |
| Status by icon and words | WCAG 1.4.1; Visual foundations |
| Labels, help, `aria-invalid`, focus return, targets ≥ 24 px | WCAG 1.3.1, 3.3.1, 3.3.2, 2.4.3, 2.5.8 |

## Acceptance criteria (AGH-578)

- **AC-578.1** Given the Hub config screen, when the Repositories section is read, then its head has Add repo, and
  each open repo card has Change and Remove that name the repo.
- **AC-578.2** Given Add repo is pressed, when the form shows, then Folder, GitHub repo and Full check are required
  and come first, the optional fields say what empty means, Save stays off with its reason until the three are filled,
  and a folder another repo has (ignoring case) is flagged before saving.
- **AC-578.3** Given a filled add form, when Add repo is pressed, then one `add_repo` write is sent with only the
  fields given. On 200 the new repo's card opens with focus on it, the toast says "Added repo {dir}", and the
  uncommitted notice names `./hub sync`, `./hub setup` and `/onboard`.
- **AC-578.4** Given a repo, when Change is pressed, then its rows become the form in place with its current values
  and no folder field. Only changed fields are sent, a cleared optional field is sent in `unset`, GitHub repo and
  Full check cannot be saved empty, and on 200 the card shows the new values with "Updated repo {dir}" and the notice.
- **AC-578.5** Given a write the API refuses (422), when the answer arrives, then the form (or the remove dialog)
  stays open with every value, and each problem's message shows on its own line exactly as sent, under the fields.
- **AC-578.6** Given `hub.json` changed on disk since the page read it, when a save is refused for it, then the
  config reloads, the form keeps only the fields the person changed, and it says nothing was saved.
- **AC-578.7** Given a repo, when Remove is pressed, then a confirmation says what goes with it and what stays on
  disk. A refusal lists one line per reference with "Ask Claude to drop these". With one repo, Remove is off with the
  reason.
- **AC-578.8** Given any open repo form, refusal or remove dialog, when the screen's a11y test runs, then it finds no
  serious or critical violation.

| Feature AC | Element and state |
| --- | --- |
| AC-6 "lists" | Repo cards (unchanged read), AC-578.1 |
| AC-6 "adds" | New repo form → `add_repo`, AC-578.2, AC-578.3 |
| AC-6 "changes" | Change form → `set_repo` with `unset`, AC-578.4 |
| AC-6 "removes" | Remove dialog → `remove_repo`, AC-578.7 |
| AC-6 "shows the 422 messages verbatim" | Refusal block, AC-578.5, AC-578.7 |
| AC-6 "a11y test has no serious or critical violation" | AC-578.8 |
| D-web "names `./hub sync` and the uncommitted `hub.json`" | `UncommittedNotice` after every write, AC-578.3, AC-578.4 |
| Plan 2.5 "changed since the page read it" | AC-578.6 |

## Needs a spec change

- **AC-382.31** ([19-brain-and-skills.md](19-brain-and-skills.md)) says that team-only rows have no edit action. The
  repo cards now have Change and Remove, which write `hub.json`. The AC gains "except the Repositories section's
  Change, Remove and Add repo, which change `hub.json` (24-hub-config-repos.md)". This lands in the same PR as the code.
- `UncommittedNotice`'s Ask-Claude text changes from "environment changes" to "changes", and the notice takes extra
  lines (O3). That is code in `notices.tsx` and no spec text.

## Open questions (for the owner)

Owner answers (2026-10-27): O1 the recommended option (the pattern message is replaced by the field's format line);
O2, O4 and O5 the recommended option; O3 keep the sentence, add the next-step lines, and the shared sentence names
both files: "Run ./hub sync to update AGENTS.md and .claude/settings.json, then …".

- **O1 · Model messages that quote a regex.** A bad GitHub repo, folder or branch comes back as the model's line,
  e.g. `hub.json: String should match pattern '^[A-Za-z0-9_]+…$'` (plan E3). Shown verbatim, that is a regex.
  *Recommended:* show every message as sent, except that this one pattern message is replaced by the field's own
  format line ("owner/name, e.g. acme/demo-web."). The Environments screen already does this (`refusalOf`'s pattern
  help). The other choice is fully verbatim, as D-web says.
- **O2 · One primary while a form is open.** The header's "Ask Claude to change the config" is primary. *Recommended:*
  it shows as a default button while a repo form is open, so Save is the view's one primary. The other choice: leave
  the header as it is and accept two primaries for that moment.
- **O3 · The uncommitted notice.** *Recommended:* keep its sentence ("Run ./hub sync to update AGENTS.md, then …")
  and add the write's next-step lines under it, and fix its Ask-Claude text to say "changes". Open point: the sentence
  says only AGENTS.md, while a repo change also rewrites `.claude/settings.json` (the CLI line names both). Should the
  shared sentence name both?
- **O4 · "Ask Claude to drop these"** in a refused remove. It is the one fix for references that cannot be edited on
  this screen (guard paths, events, contract-sync, `hub.local.json`). *Recommended:* keep it. The other choice: drop
  it, and the lines alone tell the person what to edit.
- **O5 · Tablet.** [31-responsive.md](31-responsive.md) says tablets are "read, no editing", but the screen does not
  hide its existing edit buttons there. *Recommended:* nothing hidden; the forms reflow (best effort).

## Alternatives considered

- **An add page with `SetupFlow`** (one question per step, like Add environment). It lost because the Environments
  flows use steps since one choice fills several values. A repo is three required texts and four optional ones that
  the CLI takes in one line, so steps would add five screens and hide the card the repo lands in.
- **A `SidePanel` for add and change** (like the service panel). It lost because it separates the form from the card
  whose values it changes, covers the page below 1600 px, and differs from how the same screen family edits a
  section in place (Environment page).
