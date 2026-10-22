# Knowledge › Brain and Skills: project index, page head and Brain tree

**Phase:** P2 (read-only, as built AGH-201, AGH-164, AGH-270) · **Routes:** `/knowledge/brain`, `/knowledge/skills`
(All projects), `/projects/:project/brain/*`, `/projects/:project/skills` · **Answers:** "What does each project's hub
know and what can its agents do, and where do I start reading?"

The owner validated this in the playground (AGH-270). It refines the pickers that `01-navigation.md` describes
("lists the registered projects as Brain's picker does") and the Brain screen of AGH-201; anything not named here
stays as those specify.

## Purpose and primary user

Owner and developer choosing which project's brain or skills to open, then finding a note in a brain they did not
write. With All projects in scope the picker is an index that says what is inside each project before it is opened;
inside a project the page says where it is and what it reads.

## Project index (All projects)

```
Brain
What each project's hub knows: current focus, decisions, playbooks and feature records. Open a project ...
+----------------+--------------------------------+-------+----------+-----------+-----------+---------------+
| Project        | Current focus                  | Notes | Features | Decisions | Learnings | Inbox         |
| [] agent-hub   | Ship the playground deliveries | 112   | 9        | 14        | 21        | (i) 3 to triage|
| [] demo        | No current focus recorded      | 4     | 0        | 0         | 1         | None          |
+----------------+--------------------------------+-------+----------+-----------+-----------+---------------+
Tip: pick a project in the scope switcher to open its brain directly.
```

Skills' index has the columns Project, Hub repo, Skills, Agents, Hooks, "Used in 30 days" and Diagnostics.

One shared component, `KnowledgeProjectIndex` (`screens/knowledge-index/`), renders both: a `DataTable` with a
caption, one row per registered project, the project name as a link, then the screen's own columns. Each count cell
reads the project's tree or catalog through the query the project page already uses, so the request is shared.

## Acceptance criteria

- **AC-270.1** Given All projects in scope, when Knowledge › Brain opens, then it shows the table "Projects and their
  brains" with one row per project: Project, Current focus (the first focus line of `now.md` and "+n more", else
  "No current focus recorded"), Notes, Features (folders under `brain/features/`), Decisions, Learnings and Inbox.
- **AC-270.2** Given a project whose `brain/_inbox/` holds notes, when the Brain index shows it, then its Inbox cell
  is a link "<n> to triage" to Learnings in that project's scope; with none it reads "None".
- **AC-270.3** Given All projects in scope, when Knowledge › Skills opens, then it shows the table "Projects and their
  skills, agents and hooks": Project, Hub repo, Skills, Agents, Hooks, "Used in 30 days" (skills and agents used at
  least once; hooks are not counted) and Diagnostics ("<n> with problems", linking to the catalog filtered on
  diagnostics, else "None").
- **AC-270.4** Given a count whose source is loading, failed or over its bounds, when the index shows it, then the
  cell is a skeleton, "—" with the reason in a tooltip, or the number followed by "+" with the reason in a tooltip.
- **AC-270.5** Given the index, when a row or its name is activated, then the project's Brain (or Skills) opens; with
  no project registered the index shows "No projects yet." and a link to register a hub in Settings.
- **AC-270.6** Given a project's Brain or Skills page, when it renders, then it shows the breadcrumb
  Portfolio › project › Brain (Skills) and a purpose line ("What <project>'s agents know, read from brain/ in its
  hub." / "What <project>'s agents can do, read from its hub's files. Nothing here runs them.").
- **AC-270.7** Given a long note, when the Brain shows it, then its text is capped at 80 characters per line.
- **AC-270.8** Given a project's Brain or Skills page, when the scope switcher renders, then it shows that project;
  choosing another project opens the same section of that project, and choosing All projects opens the section's
  index.
- **AC-270.9** Given a brain, when its tree renders, then the root notes are under "Start here" (Index and Now
  first, by those names), the folders under "Folders", and `_inbox/` apart under "Inbox · unreviewed" with a link
  "Triage in Learnings"; every folder shows how many notes it holds, subfolders included, in its accessible name.
- **AC-270.10** Given the Brain tree, when the user types in "Filter notes" (or presses `/` to focus it), then the
  tree becomes the flat list of notes whose path contains the text, each with its folder; with none it says
  "No note matches "<text>"." with "Clear filter", and `Esc` clears the filter.
- **AC-270.11** Given a hub with no `brain/` notes, when its Brain opens, then the tree shows "No brain in this hub"
  with the command `./hub sync`.

## Accessibility

Folder rows and note links are at least 24 px high. The tree's groups are sections labelled by their headings; the
filter has the accessible name "Filter brain notes". Count cells are tabular numbers.

## UX principles applied

| Choice | Principle |
|---|---|
| Counts before opening a project | H6 recognition over recall; information scent |
| Inbox apart, called unreviewed | Product principle 4 (provenance); the inbox is not authoritative |
| Breadcrumb and purpose line | H1 visibility of where you are; five-second test |
| Scope switcher follows the page | H4 consistency (`01-navigation.md`: changing scope on a project route opens that project's page of the same kind) |
| Filter with `/` and `Esc` | Keyboard map (`01-navigation.md`) |

## Toolkit catalog and Edit with Claude (AGH-271)

The owner validated these in the playground too. They refine the Skills catalog of AGH-164 and the Studio of AGH-262.

- **AC-271.1** Given the catalog, when it renders, then kind badges are neutral (they borrow neither the done or
  waiting status colors nor the accent), its type sizes are on the type scale, the managed tag and the New link
  have no dashed outline (kept for derived content), and a truncated invocation or description shows its full text
  on hover.
- **AC-271.2** Given the catalog at any width, when it lays out, then the group heading keeps its icon gap, kind tiles
  go four across or two by two (never three and an orphan), card titles keep room between name and kind, the hook
  rows of one event share one column grid (in a narrow column: name and tags over the command, the name never
  hidden), and the main column stretches when the filter rail stacks.
- **AC-271.3** Given a skill, agent or hook detail, when it renders, then "Edit with Claude" sits beside Discuss and
  opens the Studio on an edit draft of that item, the one already open for it when there is one.
- **AC-271.4** Given an edit draft, when its session starts, then Claude copies the item unchanged into
  `.hub-drafts/<id>/`, changes only the copy, and leaves the original alone; the Studio is titled "Edit <name>" and
  Drafts in progress marks it "editing".
- **AC-271.5** Given an edit draft, when the preview renders, then it shows the change as a diff against the current
  version, and its checks flag "no change yet" (not publishable), a rename and a managed item.
- **AC-271.6** (changed by AGH-295) Given an approved edit, when Publish is confirmed, then the web app calls the
  server's publish route (`POST /api/v1/projects/{project}/skills/drafts/{draft_id}/publish`, no message to Claude):
  the hub writes the draft's files over the item's (a hook replaces only itself in its file), records a `publish`
  version, deletes the draft and commits nothing. Claude only ever edits the draft. A managed item's dialog shows the
  hub.lock warning first and sends `confirm_managed`. The Studio shows "Publishing…" until the route answers, then
  settles on its answer: "Published." with a link to the item (and why it is not versioned, or that nothing
  changed), or the problem's detail with the draft and its session kept, and Discard offered when the draft is
  already published.

## Toolkit: readable detail, name and order (AGH-271)

- **AC-271.7** Given a step that starts with its declared type (`` `gate` **Plan**: … ``), when the structure is read,
  then the step carries that type, its bold title and the plain rest of its first line as its summary; a step that
  declares a type other than gate is never tagged a gate from its words.
- **AC-271.8** Given an item's detail, when it renders, then a lean header says how to use it, its state and its
  health; a reading column shows Steps and Text first; an About rail shows the source, `hub.lock`, tools, context
  cost and relations; a frontmatter fold is collapsed; diagnostics show only when there are findings.
- **AC-271.9** Given the sidebar, the page head, the breadcrumbs, the Studio and the project index, when they name the
  page, then it is "Toolkit"; its tabs stay Skills, Agents and Hooks.
- **AC-271.10** Given the Toolkit, when it lists kinds (tabs, tiles, the Create menu, the index columns), then agents
  come before skills and hooks.

## Item history (AGH-295)

As built in AGH-297. A Toolkit item's detail ends its main column with a **History** panel, and a hub workflow's
page has the same panel under its document; a built-in workflow's page has none. The panel is folded ("Show history")
and reads `GET .../versions` only when opened. It lists the versions agent-hub recorded of the item's unit (a skill's
folder, an agent's file, a hook's whole file, a workflow's file), newest first, 50 at a time with "Load more".

```
History                                                                   [Hide history]
Versions of .claude/settings.json · Shared by 3 hooks · (lock) Managed by hub.lock
(!) Not versioned: secret  The item on disk holds a secret match, so agent-hub does not store it. ...
+----+------------------------------+----------------+-----------+----------+-----------+
| [] | Origin                       | Author         | When      | Hash     |           |
| [x]| (undo) Restored from 1a2b3c4d| Example Owner  | 5 min ago | 9f8e7d6c | [Restore] |
| [] | (pen)  Published             | Example Owner  | 1 h ago   | 5e4d3c2b | [Restore] |
| [] | (pencil) Changed outside the app | Outside the app | 2 h ago | 7a6b5c4d | [Restore] |
| [x]| (flag) First seen            | Outside the app| 2 d ago   | 1a2b3c4d | [Restore] |
+----+------------------------------+----------------+-----------+----------+-----------+
[Compare]  2 versions selected.
```

- **Rows.** Origin in words beside an icon: "Published", "Restored from <8-character hash of the source>" ("Restored
  from an older version" when the source is not loaded), "Changed outside the app", and "First seen" for a unit's
  first version. The author's name, or "Outside the app" for an external version (D11). The time is relative, the
  absolute one in its tooltip. The hash is 8 hex characters, the full `sha256:` value in its tooltip.
- **Unit line.** "Versions of <unit path>", "Shared by <n> hooks" when one file holds several hooks, and the quiet
  badge "Managed by hub.lock".
- **State.** When the disk's content could not be stored, a warning notice (text and icon, never color alone) above
  the list: "Not versioned: secret" or "Not versioned: cannot read it" (Restore is off on every row), "Not
  versioned: too large" (Restore stays on). Earlier versions stay listed and comparable.
- **States.** Loading: skeleton lines (status "Loading the history"). No versions: "No versions yet" (the next read
  records the first). An item with no unit (a link out of the hub): "No history for this item". A failed read:
  "Could not load the history" with "Try again".
- **Compare.** Each row has a checkbox "Select <hash> (<origin>) to compare"; the last two picked stay selected, any
  two (not only adjacent ones). "Compare" turns on with two and shows, under the list, "From <older hash> to <newer
  hash>": the older against the newer as a unified diff, rendered by the Studio's `DiffText`. A folder shows one
  diff per changed file, each headed "Added", "Removed" or "Changed" with its path, and "Executable bit: off → on"
  (or on → off) for a changed bit; a binary file says its bytes differ. Equal versions say "These two versions hold
  the same content."; two versions whose hashes differ with no change the web can see (a binary file of the same
  size) say "These versions differ in bytes the app cannot show" and name the binary files; when other files changed
  too, the changes end with "They may also differ in bytes the app cannot show, in <binary files>". The diffs share one
  budget of 2,000 rendered lines (`COMPARE_MAX_LINES`), headers included: the file that crosses it ends with "<n>
  more lines — too large to show here", and each file after it keeps its heading with "Diff not shown — too large
  to show here.". The diffs are computed once per pair of versions. Opening Compare moves focus to its heading;
  "Close compare" folds it and puts focus back on Compare.
- **Restore dialog.** "Restore" on a row opens a confirm dialog (nothing is sent before its verb), titled
  "Restore <hash>?":
  - a file: "Writes this version back into <unit path>."; a hook: "Restores the whole file <unit path>: every hook
    in it (<n> hooks today)." (AC-295.23);
  - consequences: "The current content is recorded first when it changed, so it stays restorable." and "git is not
    run: the change shows in the hub's working tree.";
  - a managed unit: the warning "This file is managed by hub.lock: the next hub sync rewrites it. Restore anyway?"
    and the verb "Restore anyway", which alone sends `confirm_managed: true`; a project-owned unit has no warning
    and the verb "Restore". When the server answers `managed_confirmation_required` (hub.lock changed since the
    list), the dialog shows the warning and "Restore anyway".
  - Cancel, Escape, the X and the scrim send nothing. A refusal stays in the dialog in words: `hub_read_only` (the
    hub folder is read-only here, always in the container), `no_author` (with the server's reason),
    `link_in_path`, `unit_unreadable`, `secret_unversioned`, a 500 `write_failed`, a 503 `version_race` or
    `written_not_recorded`, and a 401 (open the link hub web printed, ending `?token=…`).
- **Result.** The dialog closes and a notice under the unit line says "Restored <hash>: a new version records it.",
  "The item already holds <hash>: nothing was written." (both neutral notices) or, as a warning, "Restored <hash>, but not versioned:
  secret" (or "too large"). A 503 `written_not_recorded` also closes the dialog, with the warning "Wrote <hash>, but
  its version was not recorded." and the server's advice to reload the history. Every read of the project's Toolkit
  (the item, its bundled files, the hooks sharing its file, the catalog), or the workflows list and the workflow,
  reads again. A history refresh that fails shows "Could not refresh the history" with "Try again" above the list
  it keeps.

### Accessibility

The panel is a region named "History"; its fold button carries `aria-expanded`. The list is a table with the
caption "Versions of <name>". Checkboxes and Restore buttons are reached with Tab and work with Space and Enter;
the selection count is a polite live line. The dialog is an alert dialog with focus on Cancel; Tab reaches "Restore"
(or "Restore anyway"). Each diff is a focusable, labelled `pre` ("Changes to <path>"), so it scrolls from the
keyboard. axe reports no serious or critical violation in the panel, Compare or the dialog (AC-295.31).

## Toolkit tabs, sidebar Portfolio and hub config (AGH-382)

**Toolkit › Workflows tab (commit 10494597)**

- **AC-382.1** Given a project's Toolkit, when it opens, then Workflows is a fourth tab beside Agents, Skills and
  Hooks, and its panel says "Jobs the hub runs from start to finish without you…" and lists the project's workflows,
  the hub's own before the built-ins, with the files that do not load.
- **AC-382.2** Given the Toolkit's Create with Claude menu, when it opens, then its last row is "New workflow" —
  "Steps the hub runs by itself, chaining agents and commands"; when picked, it opens
  `/projects/:project/skills/workflows/new`.
- **AC-382.3** Given a workflow row on the Workflows tab, when its name is clicked, then its page opens at
  `/projects/:project/skills/workflows/:name`.
- **AC-382.4** Given a workflow's page, when it shows, then its breadcrumbs read Portfolio › project › Toolkit ›
  Workflows › name.
- **AC-382.5** Given `/projects/:project/skills/workflows/new`, when opened, then the New workflow page shows; when a
  workflow is created, then "See its steps" links to its page under the Toolkit.
- **AC-382.6** Given an older link `/workflows`, when opened with All projects in scope, then it redirects to the
  Toolkit project picker (`/knowledge/skills`); with a project in scope, to that project's Toolkit on its Workflows
  tab.
- **AC-382.7** Given an older link `/workflows/:project/:name`, when opened, then it redirects to
  `/projects/:project/skills/workflows/:name`.
- **AC-382.8** Given the sidebar, when it shows, then it has no Workflows item.
- **AC-382.9** Given no workflow has run, when the sidebar shows, then Workflow runs is hidden; once a workflow run
  exists, Workflow runs shows and links to `/runs`.
  A workflow run here is a run of kind `workflow` (`GET /workflow-runs?kind=workflow&limit=1`): a hub with only
  scenario runs does not show Workflow runs (AGH-364).

**Toolkit catalog (commit 3d459347)**

- **AC-382.10** Given a project's Toolkit, when it opens with no tab named, then it opens on Agents, shows one kind
  per tab (Agents, Skills, Hooks, Workflows, the shared Tabs) and counts each tab.
- **AC-382.11** Given the Toolkit, when another tab is chosen, then the tab is kept in `?tab=` with a push, so Back
  returns to the previous tab; the tab is never treated as a filter (no Clear filters, no count status).
- **AC-382.12** Given an older `?kind=` or `?view=` link, when opened, then the tab it names is selected.
- **AC-382.13** Given a URL with filters and no tab, when opened, then the first tab with matches is selected.
- **AC-382.14** Given a search, when typed, then the tab's items filter by name or description ignoring case, and the
  status says "1 of 2 skills"; the other tabs' counts follow the search.
- **AC-382.15** Given search and facets set, when Clear filters is pressed, then they clear and the tab is kept.
- **AC-382.16** Given the filter toolbar, when it shows, then its facets are menus (Origin, Invocation, Diagnostics);
  Invocation shows on Skills only (with Hidden for neither), and an Invocation filter does not empty the Agents tab.
- **AC-382.17** Given a tab with no match, when the filters exclude everything, then it says "No hooks match these
  filters." and offers the other tabs with matches (e.g. "Skills (1)").
- **AC-382.18** Given the sort control, when Most used is chosen, then the sort is kept in the URL (`sort=used`).
- **AC-382.19** Given the open tab, when it shows, then its kind is explained once, under the toolbar.
- **AC-382.20** Given drafts left open in the Studio, when the Toolkit opens, then a "Your drafts" card lists them
  apart from the filters, each with its verb ("New skill", "Editing agent"), says "Kept in this browser only", shows
  the first three, and "Show all 4 drafts" shows the rest.
- **AC-382.21** Given an edit draft of an item, when its card (or hook row) shows, then it offers "Continue draft"
  ("Continue your draft of <name> in the Studio").
- **AC-382.22** Given a card, when it shows, then it does not repeat the kind (no "subagent" line, no kind label) and
  takes one Tab stop (origin and mode are plain text); usage says "(2 by you)".
- **AC-382.23** Given the Toolkit, when checked with axe, then it has no serious or critical violation and states the
  count as text.

**Sidebar Portfolio (commit 89e95b3c)**

- **AC-382.24** Given a project in scope, when the sidebar shows, then Portfolio becomes "Overview · <project>"
  linking to `/projects/<project>`.
- **AC-382.25** Given a project's page open, when the sidebar shows, then the overview names that project, and it is
  marked as the page only on the project's own overview.
- **AC-382.26** Given All projects in scope, when the sidebar shows, then Portfolio stays at `/`.

**Hub config (commit f0115691)**

- **AC-382.27** Given the hub config, when it opens, then there is one view of the values agents use: no
  Effective/Team/Mine (Layer) switch, whatever an old `?layer=` link says, and Models is listed.
- **AC-382.28** Given a value, when shown, then who set it is said in plain words: "Set by you", "Set by the team" or
  "Built-in".
- **AC-382.29** Given my value overrides the team's, when its row shows, then it says "Overrides the team's <value>".
- **AC-382.30** Given the hub config, when it opens, then a "Where values come from" card explains the order once
  ("You set 2 values on this machine"); Hide hides it and remembers it (`ah.config.explainer` = hidden), and "Show
  where values come from" brings it back.
- **AC-382.31** Given a row I may set, when shown, then it has "Change for me" (lists: "Add for me"), which opens
  "Change my settings"; team-only rows (guard paths, tracker labels, models) have none.
- **AC-382.32** Given the settings dialog, when saved, then the button says "Save my settings" and the confirmation
  "Saved your settings".
- **AC-382.33** Given a row's Ask button, when the row is hovered or focused, then it shows; once attached it stays,
  saying "In next message".
- **AC-382.34** Given hub.json sets only some model tiers, when Models shows, then the others are "Built-in" and the
  set one "Set by the team".
- **AC-382.35** Given hub.json sets only a tracker state, when Tracker shows, then Labels read "Built-in" and States
  "Set by the team".
- **AC-382.36** Given hub.json, when the config read model is built, then `model_tiers_set` names the tiers hub.json
  sets and `tracker.team_set` names the labels and states it sets (empty when none).
- **AC-382.37** Given an unreadable hub.local.json, when the config opens, then it says it "has a problem, so only the
  team's values apply" with the line, and offers Ask Claude to fix it.
