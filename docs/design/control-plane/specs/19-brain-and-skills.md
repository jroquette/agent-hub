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
- **AC-271.6** Given an approved edit, when Publish is confirmed, then Claude writes the draft's files over the
  item's (a hook replaces only itself in its file), deletes the draft and commits nothing; the Studio settles on
  Claude's PUBLISHED line as for a new item.
