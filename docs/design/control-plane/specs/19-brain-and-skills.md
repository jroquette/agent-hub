# Knowledge › Brain and Skills: project index, page head and Brain tree

**Phase:** P2 (read-only, as built AGH-201, AGH-164, AGH-270, AGH-393) · **Routes:** `/knowledge/brain`,
`/knowledge/skills` (All projects), `/projects/:project/brain/*?q=` (`?q=` written with `replace`, the note path with
`push`), `/projects/:project/skills` · **Answers:** "What does each project's hub
know and what can its agents do, and where do I start reading?"

The owner validated this in the playground (AGH-270). It refines the pickers that `01-navigation.md` describes
("lists the registered projects as Brain's picker does") and the Brain screen of AGH-201; anything not named here
stays as those specify.

## Purpose and primary user

Owner and developer choosing which project's brain or skills to open, then finding a note in a brain they did not
write. With All projects in scope the picker is an index that says what is inside each project before it is opened;
inside a project the page says where it is and what it reads.

## Project index (All projects)

Changed by AGH-427 (the owner validated it in the playground): the index is a grid of project cards, not a table.
Toolkit, Brain and Hub config (and Environments, when it lands) share it.

```
Toolkit
What each project's agents can do: the agents, skills and hooks its hub installs. Open a project to browse them.

Projects                                      [folder] To come straight here, choose a project in the top bar.
+------------------------------------------------+ +------------------------------------------------+
| agent-hub  AGH        [Sync pending] [Healthy] >| | demo                           [Not checked] > |
| acme/agent-hub-hub · 3 repos · platform 0.19.0  | | acme/demo-hub · 1 repo · platform 0.19.0       |
| Agents   Skills   Hooks   Used · 30 d           | | Agents   Skills   Hooks   Used · 30 d          |
| 12       34       5       18                    | | —        —        —        —                    |
| (!) 4 items with problems                       | | (!) Could not read this catalog: Boom.  [Retry]|
+------------------------------------------------+ +------------------------------------------------+
```

One shared component, `KnowledgeProjectIndex` (`screens/knowledge-index/`), renders every picker: a "Projects"
section title (one project: "Project") with the screen's tip at its right beside the scope switcher's
`folder-kanban` icon, then a list (named by the screen's caption) of `.ah-pcard` cards in a grid that fills the
content width (`repeat(auto-fill, minmax(min(360px, 100%), 1fr))`: 3 columns at 1440, one or two projects keep a
card's width). A card is, top to bottom:

1. the head of the Portfolio card (`ProjectCardHead`, extracted from `ProjectCard` in `components/domain.tsx`, which
   still renders it): the name as an `h3` holding the link, the tracker team, `hub · n repos · platform v` with the
   repo names in a tooltip, Sync pending and the health badge, and a `chevron-right` cue;
2. an optional lead line (Brain: "Current focus: …"; Hub config: the repo names joined by " · ", else "No repos
   declared yet"), one line with an ellipsis;
3. the screen's figures as `CardStat`s (exported from `components/domain.tsx`) whose values are `CountCell`s;
4. an optional foot line: a link to what needs a look, a quiet line when nothing does, or the read error with a
   Retry that refetches only that project's source.

Each figure or foot reads the project's tree or catalog through the query the project page already uses, so the
request is shared and the cards show at once. Per screen:

| Screen | Figures | Lead | Foot |
|---|---|---|---|
| Toolkit | Agents, Skills, Hooks, "Used · 30 d" | none | "<n> items with problems" (to `?diag=1`), "No problems found", or the error + Retry |
| Brain | Notes, Features, Decisions, Learnings | "Current focus: <first line>" "+n more", else "No current focus recorded" | "<n> to triage in Learnings", "Inbox empty", or the error + Retry |
| Hub config | none | the repo names | none |

The whole-list error is a `ProblemError` "Could not load projects". The head shows the hub repo, so Toolkit has no
Hub repo figure. Not built (left open by the design): opening the only project directly, a find field for many
projects, and figures or a problems foot for Hub config.

## Acceptance criteria

- **AC-270.1** (changed by AGH-427) Given All projects in scope, when Knowledge › Brain opens, then it shows the
  project cards "Projects and their brains", one per project: the lead "Current focus: <the first focus line of
  `now.md`>" and "+n more", else "No current focus recorded", then Notes, Features (folders under
  `brain/features/`), Decisions and Learnings, and the Inbox in the foot.
- **AC-270.2** (changed by AGH-427) Given a project whose `brain/_inbox/` holds notes, when the Brain index shows it,
  then its foot is a link "<n> to triage in Learnings" (named "<n> to triage in Learnings for <project>") to
  Learnings in that project's scope; with none it reads "Inbox empty".
- **AC-270.3** (changed by AGH-427) Given All projects in scope, when the Toolkit picker opens, then it shows the
  project cards "Projects and their agents, skills and hooks": Agents, Skills, Hooks, "Used · 30 d" (skills and
  agents used at least once in the last 30 days; hooks are not counted), and a foot "<n> items with problems" linking
  to the catalog filtered on diagnostics, else "No problems found".
- **AC-270.4** (changed by AGH-427) Given a count whose source is loading, failed or over its bounds, when the index
  shows it, then the figure is a skeleton, "—" with the reason in a tooltip, or the number followed by "+" with the
  reason in a tooltip; a failed source also puts its reason in the card's foot with a Retry.
- **AC-270.5** (changed by AGH-427) Given the index, when a card is clicked or its name activated, then the project's
  Brain (or Toolkit) opens; with no project registered the index shows "No projects yet." and a link to register a
  hub in Settings.
- **AC-427.12** Given a picker card, when it shows, then its head is the Portfolio card's head (name as the card's
  only opening link, team, `hub · n repos · platform v`, Sync pending, health) followed by a chevron.
- **AC-427.13** Given a project whose catalog or tree cannot be read, when its card shows, then the foot says "Could
  not read this catalog: <title>." (or "this brain") with a Retry that refetches only that project's source, and the
  other cards are unaffected.
- **AC-427.14** Given the picker, when `j` or `k` is pressed, then focus moves to the next or previous card's name;
  `o` opens the focused card.
- **AC-427.15** Given the picker, when it loads, then three skeleton cards show in the grid (`aria-busy`); when the
  list fails, then "Could not load projects" shows with Retry.
- **AC-427.16** Given the Hub config picker, when it shows, then each card's lead lists the project's repos joined by
  " · ", else "No repos declared yet".
- **AC-427.17** Given any picker, when it shows, then the tip "To come straight here, choose a project in the top
  bar." sits at the right of the "Projects" title, and the page has no serious or critical axe violation.
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
- **AC-270.10** (changed by AGH-393) Given the Brain tree, when the user types in "Search notes and repo docs" (or
  presses `/` to focus it), then the tree gives way to two lists: "Paths matching "<text>" · <n>", the notes whose
  path contains the text, each with its folder, the first 8 then "Show all <n> path matches" (AM-1); and "Text
  matching "<text>"", the knowledge index's matches (see the AGH-393 section below). With no match in either it says
  "Nothing matches "<text>"." with "Clear search", and `Esc` clears the field and brings the tree back.
- **AC-270.11** Given a hub with no `brain/` notes, when its Brain opens, then the tree shows "No brain in this hub"
  with the command `./hub sync`.

## Accessibility

Folder rows and note links are at least 24 px high. A picker card is an `article` labelled by its name, which is
the one link that opens it (the card's click is a mouse convenience); the foot link and Retry are their own Tab
stops and do not open the card. The tree's groups are sections labelled by their headings; the
search field has the accessible name "Search brain notes and repo docs" (AGH-393). Count cells are tabular numbers.

## UX principles applied

| Choice | Principle |
|---|---|
| Counts before opening a project | H6 recognition over recall; information scent |
| Inbox apart, called unreviewed | Product principle 4 (provenance); the inbox is not authoritative |
| Breadcrumb and purpose line | H1 visibility of where you are; five-second test |
| Scope switcher follows the page | H4 consistency (`01-navigation.md`: changing scope on a project route opens that project's page of the same kind) |
| Filter with `/` and `Esc` | Keyboard map (`01-navigation.md`) |
| One field for paths and text, `/` focuses it (AGH-393) | Spec 01 keyboard map ("the page's search or filter field"); H4 consistency |
| Paths first, text second (AGH-393) | No layout shift under what the user reads (22 loading rules); H1 |
| Results beside the open note, the query in `?q=` (AGH-393) | H6 recognition over recall; context kept |
| Path list capped at 8 (AGH-393) | H8 minimalist design; progressive disclosure |
| Repo docs listed but not linked, the reason in words (AGH-393) | H1 honest status; WCAG 1.4.13 |
| `inbox · unreviewed`, `ExternalLabel` on a result (AGH-393) | Product principle 4 (provenance) |
| Snippet as plain text, no colour on kind or status (AGH-393) | Principle 3 (show only what the record shows); AC-271.1 |
| Body first, the two note sections after it, one-step jumps in the header (AGH-393) | Progressive disclosure (H8); the five-second test for a note is reading it |
| Fields the note sections show leave the chips (AGH-393) | H8 (no duplicate); Learning detail already drops `provenance` from its chips |
| No count, no effect wording in "Where this note came from" (AGH-393) | Q16 (`32-decisions.md`) |
| Search, each note section and the note load and fail on their own (AGH-393) | 22 "Region independence"; H9 |

## Search, Linked from and Where this note came from (AGH-393)

The owner approved these designs with the spec (AGH-393 AM-1). They add a text search over the knowledge index (the
one `hub search` uses) to a project's Brain, and two sections after the note: where it came from and which documents
link to it. All of it is read-only; the Brain screen is the only one that shows the two sections (Feature detail's
tabs render the same `NoteView` without them).

```
+------------------------------------+  +-------------------------------------------------------------+
| [search] worktrees                 |  | [file] brain/learnings/web-gates.md  Where it came from     |
|                                    |  |        Linked from · 2                          [Discuss]   |
| PATHS MATCHING "worktrees" · 1     |  | type: learning  repos: agent-hub  (no provenance, sources)  |
|  0001-worktrees.md  decisions/     |  | # Web gates need the a11y run                               |
| TEXT MATCHING "worktrees" · 3      |  | ...note body (80 ch)...                                     |
| (i) demo-web: not checked out; its |  |-------------------------------------------------------------|
|     docs are not searched          |  | Where this note came from                                   |
| [file] Worktrees from origin       |  | Provenance  [agent]                                         |
|        brain/decisions/0001-w…md   |  | Sources     AGH-272 review notes                            |
|        decision · accepted         |  | Learnings   [bulb] Run the a11y tests before the PR  In brain|
|        …every task runs in its own |  |             Accepted 4 Oct 2026 by José · session 5091b986  |
| [book] Repo guide                  |  |-------------------------------------------------------------|
|        demo-api/docs/guide.md      |  | Linked from · 2                                             |
|        doc · repo doc, not opened  |  | [file] Cleanup after merge  brain/playbooks/cleanup.md      |
| 2 files were not searched. [Show which]  | [book] Repo guide  demo-api/docs/guide.md · repo doc      |
+------------------------------------+  +-------------------------------------------------------------+
```

**Search panel.** One field, "Search notes and repo docs" (accessible name "Search brain notes and repo docs",
`type="search"`, at most 500 characters, the route's bound), sits over the tree. With an empty field the panel is the
tree, as before. Typing shows, in place of the tree:

- **Paths matching "<text>" · <n>**, at once: the AC-270.10 path filter, the first 8 with "Show all <n> path matches"
  (then "Show the first 8"; the button carries `aria-expanded`); hidden when no path matches.
- **Text matching "<query>" · <n>**, 120 ms after the last key (`Enter` sends it at once): the results of
  `GET /projects/{project}/knowledge/search?q=` (no `limit`, so the route's 50) in the index's rank order, one knowledge
  row each. At 50 the heading reads "· 50 best" and a footnote says "Showing the 50 best matches. Add a word to narrow
  the search." Each `warnings` line ("demo-web: not checked out; its docs are not searched") is an info `Banner`, not
  live, above the rows. When the answer skipped files: "<n> files were not searched (a secret rule matched, too
  large, or unreadable)." with "Show which", which lists each "<path> · <reason>".

The query is kept in `?q=` with `replace`; every link inside the Brain (tree, results, the note's own links, Linked
from) keeps it, so Back and forward restore the list and the note together. A query with no letter or digit is not
sent.

**Knowledge row** (a screen-local pattern, `KnowledgeRow.tsx`, shared by the results and Linked from): an icon and
the **title** (one line, the whole title on hover), the **path** (`PathText`, mono, middle-truncated to 34
characters, folder dimmed, the full path on hover), the **kind** and status (`decision · accepted`; kind `inbox`
reads `inbox · unreviewed`; provenance `agent-from-external` adds `ExternalLabel`; neither is coloured), and in search
the **snippet** as plain text, clamped to 3 lines (2 below 900 px) by CSS so a screen reader reads it all.

- A result under `brain/` that the note route serves is one link to its note (keeping `?q=`), named by its title, the
  rest its description; the open note's row carries `aria-current="page"`.
- A result under `<dir>/docs/` is text, not a link: `book` icon, the kind line ends "· repo doc, not opened here", and
  the tooltip says "Repo docs are not opened in the app".
- A `brain/` path the note route would refuse (AM-8: not a `.md` file, a hidden or empty segment, under `brain/auto/`,
  over 16 segments or 512 characters, or a control character or backslash) is text too, `file-text` icon: the kind
  line ends "· not opened here", the same words as a repo doc, and the tooltip gives the reason, "The app does not
  open notes at this path (not a .md file, a hidden name, under auto/, too long or deep, or with an empty part or
  characters the app does not serve)". The row is not in the Tab order: its visible words "not opened here" carry the
  reason for keyboard and touch users, and the tooltip, which also describes the row for a screen reader, adds the
  detail on hover.
- Only a row that opens a note highlights on hover; a text row (repo doc or refused note) does not.

**Note column.** The header row holds the path, two quiet in-page buttons, **"Where it came from"** and **"Linked from
· <n>"** ("Linked from" until the count is known), and Discuss. Each button scrolls to its section (smooth only
without reduced motion) and focuses the section's heading; the URL is untouched. Their accessible names are their
visible text (WCAG 2.5.3 label in name), not a longer "Go to …" name. The frontmatter chips leave out `provenance` and
`sources`, and `session` while the section below shows it as a link; every other field stays a chip. After the body,
each behind a `border` hairline and 80 ch wide:

- **Where this note came from** (`h2`), a definition list with a 120 px label column; a row shows only when it has
  something:
  - **Provenance:** the frontmatter value; `human`, `agent`, `agent-from-code` and `agent-from-external` render as
    `ProvenanceBadge` (the last adds `ExternalLabel`), any other value as text.
  - **Sources:** the frontmatter `sources` as text, never resolved, fetched or linked, one per line; the first 5,
    then "Show all <n> sources" (then "Show the first 5").
  - **Learnings:** the accepted learnings whose note this is, from
    `GET /learnings?project=&brain_path=&status=accepted&limit=10`, in the list's order (newest proposal first, AM-7):
    `lightbulb`, the title (without "Proposal:") linking to `/knowledge/learnings/<id>`, its `LearningStateBadge`
    ("In brain", "Accepted · PR open"), then "Accepted <4 Oct 2026> by <person>" (the date in the top bar's time zone,
    the time on hover; without a decider "Accepted <date>", without a date "Accepted") · "session <short id>" linking
    to `/sessions/<id>` (name "Session <full id>", the full id on hover) or "no source session recorded". With a next
    page: "More learnings name this note; the 10 newest are shown."
  - **Session:** only once the learnings are read and none names a session, and the frontmatter `session:` matches
    `^[A-Za-z0-9_-]{1,128}$`: "session <short id>" linking to `/sessions/<value>` (tooltip "Opens the session if this
    app collected it."), then "From the note's frontmatter." Any other value stays a chip.
  - None of these: "No provenance recorded for this note."

  No count of sessions and no "since", "fixed", "improved", "effect" or "impact" wording (Q16).
- **Linked from · <total>** (`h2`): the documents whose Markdown links point to this note, from
  `GET /projects/{project}/brain/backlinks?path=` (the route syncs the index first), sorted by path, as knowledge rows
  without a snippet; a `brain/` source opens its note and moves the focus to its path line. Over 100: "and <n> more"
  (text). None: "No note links here."

The note, its backlinks and its learnings are asked for together when the note opens, and each section renders when
its own answer arrives; a note that does not load (404, 413, an error) shows neither section nor the jump buttons.

**States.**

| State | Search panel | Where this note came from | Linked from |
|---|---|---|---|
| Loading | Path list at once; 3 skeleton rows under "Text matching" after 300 ms, held at least 300 ms (`aria-busy`); a screen reader hears "Searching notes" after 1 s | Provenance and sources at once (they come with the note); the Learnings row a 2-line skeleton | 2 skeleton rows (`aria-busy`) |
| Slow first read (after 2 s) | "Reading the hub's notes for this search. A first search after an update can take a few seconds." | — | "Reading the hub's notes to find the links. A first read after an update can take a few seconds." |
| Empty | "Nothing matches "<text>"." with "No note path or text contains it." (several words: "Every word must appear: try fewer words.") and "Clear search" | "No provenance recorded for this note." | "No note links here." |
| No word in the query (`!!!`, or the route answers 400) | "Type a letter or a digit to search the text of notes." (path matches still show) | — | — |
| Failed | `ProblemError` (compact) in the text section only: the problem's title and detail (e.g. 502 "Could not read the hub's files" with AGH-391's line), "Try again" | Learnings row: `ProblemError` "Could not load the learnings for this note." with "Try again"; the rest shows | `ProblemError` (compact) with the problem's title and detail, "Try again"; the note still shows |
| Server not responding | "The app's server is not responding" / "Check that hub web is still running, then try again." | as Failed | "The app's server is not responding" / the same detail |

**Keyboard.** `/` focuses the field; `Esc` in it clears it; `Enter` searches at once; `↓` moves to the first result
(path matches first). In the results `↓`/`↑` and `j`/`k` move between rows (repo-doc rows included, so the list reads
in rank order; they are not Tab stops), `↑` on the first row returns to the field, `Enter` opens a brain row, and
`Esc` returns to the field without clearing it. Opening a result keeps the focus on that row; below 900 px, with the panel
stacked above the note, the focus moves to the note's path line.

**Accessibility.** The two lists and the two note sections are `section`s labelled by their `h2`. One visually hidden
`role="status"` line announces the counts once per settled query ("1 path and 3 text matches for "worktrees"." /
"Nothing matches "zebra"."). Rows are at least 24 px with the focus ring on the whole row.

- **AC-393.3** Given the Brain screen with the search route mocked, when the user presses `/`, types `worktrees` and
  the debounce passes, then "Text matching" lists each result's path, kind, title and snippet, the URL holds
  `?q=worktrees`, the decision opens its note (the URL keeps `?q=`), a repo doc is text with the tooltip "Repo docs are
  not opened in the app", and the path list still narrows. Test: `screens/brain/index.test.tsx` "search: …" tests.
- **AC-393.13** Given the note with the backlinks route mocked, when it answers two items, then "Linked from" lists
  both, the `brain/` one a link; none → "No note links here."; `total: 130` with 100 items → "and 30 more"; a failure
  → the problem with "Try again", the note still shown. Test: `screens/brain/LinkedFrom.test.tsx` "linked from: …".
- **AC-393.16** Given a note with `provenance: agent`, `sources: [a, b]` and an accepted learning from session `s1`,
  when it renders, then "Where this note came from" shows the provenance and sources as text, the learning's title
  linking to `/knowledge/learnings/<id>` and "session s1" to `/sessions/s1`; with no learning and `session: s-123`
  that session links; `"bad id!"` shows no session; none → "No provenance recorded for this note."; no effect words
  or session counts in any case. Test: `screens/brain/NoteOrigin.test.tsx` "came from: …".
- **AC-393.18** (this screen) axe reports no serious or critical violation with the search results, no match and a
  failure, and with both note sections. Tests: `index.test.tsx` "search panel … (a11y)", `LinkedFrom.test.tsx` and
  `NoteOrigin.test.tsx` "(a11y)".

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

## Workflow page and Toolkit workflow cards (AGH-427)

**Route** `/projects/:project/skills/workflows/:name` · **Answers:** "What does this workflow do, step by step, and what
do I give it to run it?" The reader is the hub owner deciding whether to run a workflow or change it; the one action
stays **Run this workflow** (or "Starts from `hub run`", AC-PG-13.3). The owner validated this in the playground.
Before it, the page had no width cap and a 320 px aside that did not stick, steps were loose rows with their condition
in a `title`, commands were faint inline code and the rounds box said "stopping as soon as they pass" for any rule.

```
Portfolio › agent-hub › Toolkit › Workflows › deliver
deliver  [Built-in]                                    [Discuss] [▶ Run this workflow]
One issue to a PR, implemented and reviewed in rounds until the check and both reviewers pass.
6 steps · Claude does 3 · repeats in up to 3 rounds · runs without you
┌─ Step by step ──────────── 3 AI agents  3 commands  rounds ─┐ ┌ What you give it ────────┐
│ (1)  Make (or keep) the issue's worktree from a fresh fetch  │ │ issue                    │
│  │   >_ Command · worktree                                   │ │ The tracker issue        │
│  │   [$ hub step worktree --issue $INPUTS.issue        [⧉]] │ ├ Where it lives ──────────┤
│ (2)  Implement, check, review, again until the verdict passes│ │ Built into agent-hub. …  │
│  │   ⟳ Rounds, up to 3 · rounds                              │ │ Revision   r1            │
│  │   ┌ well ─────────────────────────────────────────────┐   │ │ Runs of this workflow    │
│  │   │ ⚑ Stops when $review.output.verdict == 'PASS'      │   │ └──────────────────────────┘
│  │   │ If round 3 ends without stopping, this step fails. │   │   ^ sticky
│  │   │ (2.1) The implementing session …                   │   │
│  │   │       AI agent · implement · ▸ Read the prompt     │   │
│  │   │ (2.2) The repo's check on the round's work         │   │
│  │   │       ⑂ Only when $verdict.output.status != 'blocked'│ │
│  │   └────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
┌ ▸ Advanced: graph and document ─────────────────────────────────────────────────────────┐
  graph full width; a chosen node opens under it: its facts | a wide JSON of its document
```

- **Frame.** `.wf-detail` caps the page at 1280 px (`space-8` padding, `space-6` under 1360 px) and reuses the skill
  detail's `.ah-skill-layout`: a reading column and a 300 px sticky `.ah-skill-rail` (AC-271.8), which moves above
  the steps under 1200 px. Step text is at most 88ch; code blocks use the column's width.
- **Step row.** A timeline (`ol.wf-steps`): a 24 px node numbered `N` (or `N.k` inside rounds) with its border in the
  kind's event colour, a 1 px rail to the next node; the description is the title (the id in mono when there is
  none); a caption line says the kind (icon and label: "AI agent", "Command", "Approval by you", "Rounds, up to N"),
  the id and "Waits for" with one chip per step it waits on when that is not simply the step before. Colour is never
  the only channel.
- **Rounds** sit in a solid `surface-sunken` well (dashed means Derived) with their own timeline.
- **Rail.** "What you give it" (each input a fact: name in mono, "(optional)", its description or type; none: "Nothing:
  it runs as is.") and "Where it lives" (the two sentences, Revision `rN`, a "Runs of this workflow" link to
  `/runs?workflow=`).
- **Toolkit › Workflows tab.** Each workflow is a catalog card of the Toolkit's grid (`.ah-skills-grid`, the shape of
  the Agents and Skills tabs): name, description, then a foot with where it comes from, what you give it and its
  shape.

- **AC-427.1** Given a workflow's page, when it renders, then the page is capped at 1280 px with the steps in a
  reading column beside a sticky About rail holding "What you give it" and "Where it lives" (Revision `r1`, "Runs of
  this workflow" linking to `/runs?workflow=<name>`); under 1200 px the rail moves above the steps.
- **AC-427.2** Given a workflow's page, when its header shows, then a muted line under the description gives its
  shape in words, and a repeat reads "repeats in up to N rounds" (also on the Toolkit card); the step kind chips sit
  in the "Step by step" heading.
- **AC-427.3** Given a step, when it shows, then its description is its title (else its id in mono), a kind line
  says the kind with its icon, its id, and "Waits for" with a chip per step it waits on unless that is only the
  step before; an `.ah-sr` "Step N: " prefix names the number for screen readers.
- **AC-427.4** Given a step with a `when` condition, when it shows, then "Only when" and the expression are visible
  text, not a tooltip.
- **AC-427.5** Given a command step, when it shows, then its command is a wrapping `CodeBlock` labelled "Command of
  <id>" with Copy; an agent step's prompt is folded under "Read the prompt", scrolls from the keyboard and has "Copy
  prompt".
- **AC-427.6** Given a rounds step, when it shows, then it says "Rounds, up to N" and its real stop rule ("Stops when
  <until_when>", "Stops when <until_bash> passes", or "Runs all N rounds."), "If round N ends without stopping, this
  step fails." when there is a rule, whether the agents remember the previous round, and "Starts afresh each round"
  on a body agent with fresh context.
- **AC-427.7** Given the steps, when `j` or `k` is pressed, then focus moves to the next or previous step, round
  steps included.
- **AC-427.8** Given a workflow that is loading, when the page shows, then a skeleton of the final shape (header,
  steps card, rail) with "Loading <name>" shows; given a document with no steps, then the card says "This workflow
  has no steps."
- **AC-427.9** Given the Advanced fold with a node chosen, when it shows, then the node opens under the graph at
  full width, its facts (Type, Waits for, Description) beside a wide JSON of its document.
- **AC-427.10** Given the Toolkit's Workflows tab, when it lists workflows, then each is a catalog card like the other
  tabs: the name as its only link and Tab stop, the description, "Hub" or "Built-in", what you give it ("Takes no
  input") and its shape.
- **AC-427.11** Given the workflow page with rounds, a condition and an open prompt, when checked with axe, then it
  has no serious or critical violation.

## Workflow graph canvas (AGH-521)

The owner validated this in the playground (snapshot `20261023T210306Z`); where the section above says otherwise, this
wins. The shared canvas parts live in `components/Canvas` (grid, zoom toolbar with fit and layout switch, minimap,
arrowheads) with `lib/usePanZoom` and `lib/canvasView`; the ticket flow ([17-features.md](17-features.md)) reuses them.

- **AC-521.10.1 Graph first.** Given a workflow page, then it opens on a pan and zoom graph: steps as cards with their
  kind, rounds groups as frames holding their own steps, curved edges with arrowheads, zoom, fit and a minimap; the
  chosen step opens in a docked panel with what it waits for, what it leads to and what it does. Steps and Document
  are views beside the graph. Run detail draws the same canvas with each step's state.
- **AC-521.10.2 Top to bottom.** Given the graph, then it is laid out in topological order, each layer a centred row
  with the arrows pointing down; an edge that skips layers runs in a lane of its own beside the rows it passes
  (shortest first). The left-to-right wrapped rows are one click away in the canvas toolbar.
- **AC-521.10.3 Readable when it opens.** Given the first view, then the graph is fitted when it reads at 85% or more
  with its rounds frames open; otherwise the frames close and the graph is fitted if it then reads at 85% or more,
  else it opens at 100% from the top. It is placed only once the boxes belong to the current shape.
- **AC-521.10.4 Keyboard and small screens.** Given a focused rounds frame, then Right opens it and Left closes it; a
  step inside a round says it starts or ends the round; the minimap takes the world's shape; under 1280 px the wheel
  scrolls the page instead of zooming, and the inspector never clips.


## Code in colour (AGH-596)

The owner validated this in the playground (snapshot `3df1fa457`, on v0.26.0). The Toolkit shows its code coloured by
its language, through the app's one `HighlightedCode` component
([ADR 0051](../../../adr/0051-syntax-highlighting-across-the-app.md)). The text stays exactly the file's: only its
colours change, and a text over the highlighter's bounds or in a language it does not hold stays plain.

- **AC-596.5.21** Given a skill's Raw view, when it is shown, then the raw text is coloured as Markdown.
- **AC-596.5.20** Given a hook's detail, when its command is shown, then it is coloured as shell; it stays inert code
  with no button that runs it (AC-164.22).
- **AC-596.5.22** Given a Studio draft's file, when it is shown, then it is coloured by its language, from its path's
  extension. A skill's bundled files are coloured the same way.
