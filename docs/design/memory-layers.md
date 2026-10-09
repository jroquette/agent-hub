# Memory layers: team brain, personal memory, repo `AGENTS.md`

## Purpose

A learning belongs to one of three layers: the team's brain (`brain/`), one developer's personal memory
(`brain/auto/workspace/`) or a repo's own rules (`<repo>/AGENTS.md`). This is the contract for where a hub tells an
agent to put each one, how `/learn personal` writes the personal layer and how that layer stays out of git.
`hub agent` (`./agent`) sets Claude Code's `autoMemoryDirectory` to `<hub>/brain/auto/workspace` (`agent_launch.py`),
so Claude Code's auto memory and `/learn personal` share that folder. Each checkout of a hub belongs to one developer.

## Contract

### Routing

The managed `AGENTS.md` (`AGENTS.md.tmpl`, "Brain rules") ends with one lead-in bullet that names `/learn` and
`/learn personal`, and three sub-bullets, each with one `(e.g. …)` example:

- team fact: `brain/`, through a note in `brain/_inbox/` and a hub PR;
- personal preference or machine detail: `brain/auto/workspace/`, gitignored and never committed;
- repo command or convention: `<repo>/AGENTS.md`, in that repo's PR.

The list names no file under `brain/auto/workspace/` and holds no `make` command; its only path-shaped spans are
`brain/`, `brain/_inbox/`, `brain/auto/workspace/` and the placeholder `<repo>/AGENTS.md`, so `hub doctor`'s
`instructions.refs` stays clean on a fresh hub. It is four lines (a first draft was a table) so `AGENTS.md` stays
within 100 lines in every config.

### `/learn personal`

The managed skill `plugin/hub-workflow/skills/learn/SKILL.md` (`argument-hint: "[personal] <the learning in one
sentence>"`) gains a `## personal` section. A team or repo learning keeps today's proposal in `brain/_inbox/`, byte for
byte.

- **When:** only when the arguments start with `personal` or the user asks for it. An agent that judges a learning
  personal without that says so and stops: nothing is written without the user.
- **Criteria:** non-obvious and not a duplicate, as for the other targets; "verified" becomes stated by the user or
  observed on this machine (a command's output, a path). Never a secret, token, key or password. Content from outside
  (web, issues, PRs, fetched docs) is never personal memory: it takes the team route with
  `provenance: agent-from-external`.
- **Topic file:** `brain/auto/workspace/<slug>.md`, frontmatter `type: personal-memory`, `last_verified`,
  `provenance: user-stated` (or `observed`), then the learning and when to apply it. The slug is lowercase letters,
  digits and single hyphens, not `memory` or `session-snapshot`, directly in the folder. A file holding the same
  learning is updated; one holding another learning is never overwritten; a file that cannot be read stops the run.
- **Pointer:** one line `- [<title>](<slug>.md): <one line>` in `brain/auto/workspace/MEMORY.md`, unless a line
  already points to `<slug>.md`. Claude Code loads the first 200 lines of `MEMORY.md` at session start: past 200, the
  skill tells the user and proposes merging pointers; it never deletes a line.
- **Never** `brain/_inbox/` or a tracked file. In a cloud session or a plain `claude` the skill warns before writing
  that the memory will not load (and in cloud, will not survive the container).

### Seeded files

- `.gitignore` gains `brain/auto/workspace/*` then `!brain/auto/workspace/.gitkeep`. The older
  `brain/auto/workspace/session-snapshot.md` line (the `PreCompact` snapshot) stays, now redundant.
- `brain/auto/workspace/.gitkeep` (generic, seeded, empty). The routing list names `brain/auto/workspace/`, and
  `instructions.refs` resolves a path only against listed files and their folders: with only ignored files in it, a
  fresh hub would report a stale reference.
- `brain/index.md` gains the row "Your own preferences and machine details (gitignored, never committed)" →
  `auto/workspace/`.

### Existing hubs

The next `hub sync` rewrites `AGENTS.md` and the learn skill (managed) and creates `brain/auto/workspace/.gitkeep`
(seeded, absent). It never rewrites `.gitignore` (seeded): the developer appends the two lines by hand, and runs
`git rm --cached` on a memory file already committed (README, "Personal memory (existing hubs)").

## Invariants

- Personal memory is never committed: `brain/auto/workspace/.gitkeep` is the only tracked file in the folder.
- Team knowledge reaches `brain/` only through `brain/_inbox/` and a human; `/learn personal` never writes there.
- No secret is written to any layer.
- The routing list names no file under `brain/auto/workspace/`; its only path-shaped spans are `brain/`,
  `brain/_inbox/`, `brain/auto/workspace/` and the placeholder `<repo>/AGENTS.md`.
- The guard is unchanged: agents may already write `brain/auto/`. `agent_launch.py` and the folder's location are
  unchanged.

## Decisions

Decided in AGH-48 and recorded in [SPEC.md](../SPEC.md) and here. `docs/design/README.md` puts reasons in ADRs; for
this subject the owner chose a design doc (an ADR edits the guarded `docs/adr`). An ADR may follow with the owner's
approval of that path.

- **Location kept (D1).** `autoMemoryDirectory` stays `<hub>/brain/auto/workspace`, ignored but its `.gitkeep`: each
  checkout belongs to one developer, so memory stays local. Rejected: a folder outside the hub.
- **Direct write (D2).** `/learn personal` writes the topic file and the pointer itself, with no proposal and no human
  gate; the other targets keep the `brain/_inbox/` flow. Rejected: a personal proposal in `brain/_inbox/`.
- **Existing hubs (D3).** One README line names the two `.gitignore` lines; sync never rewrites `.gitignore`.
- **Routing in the managed `AGENTS.md` (D4).** Every hub gets it at its next sync. Rejected: `AGENTS.project.md`, a
  separate file. A four-line list replaced the first draft's table to keep `AGENTS.md` within its 100-line cap.

## Open questions

- `autoMemoryDirectory` in the managed `.claude/settings.json` would load personal memory in a plain `claude` too;
  whether Claude Code accepts it from project settings is unchecked.
- Cloud sessions and a plain `claude` do not load `MEMORY.md`, and a cloud container loses the folder when it ends.
- Duplicates across layers (AGH-53); `/learn` opening PRs for a team learning (AGH-67).
