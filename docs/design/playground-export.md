# Playground export

## Purpose

The playground ([ADR 0035](../adr/0035-live-playground-and-auto-mode.md)) is where the owner validates a change to
the web app or the API by using it: sessions edit the checkout in small committed steps, and what stays on screen is
what the owner approved. An export turns that validated state into the input of a production delivery: what was
asked, what changed, the code as it stands and the screens as they look, so the delivery reproduces them with specs,
tests and the repo's conventions instead of reinterpreting them.

## Contract

`make playground-export [SINCE=<ref>]`, run in the playground checkout (`scripts/playground_export.py`).

- **Range.** From `SINCE`, else the newest tag `playground-export/*` reachable from `HEAD`, else the merge base with
  `origin/main`; to `HEAD`, plus the uncommitted changes. A commit `origin/main` already has (by sha, or as the same
  change, `git cherry`) is shipped: left out and listed. A commit another pushed branch has stays in the export,
  marked with that branch, since an open PR may not land. Nothing else is left out. An empty range with a clean tree
  exits 0 with "nothing to export".
- **Requests.** The unit of the export and of a delivery. Each driven session of the `agent-hub` project active
  since an hour before the range's first commit, or that made one of its commits, read from the conductor
  (`/api/v1/agent-sessions` and each session's `/events`); titled sessions with the same title and folder are one
  request (a continued or twin conversation). A request keeps:
  - its **turns**: each owner message in their own words (whether a screenshot came with it), the answers they gave
    to Claude's questions while it worked (the validation), and the commits that turn made. A commit is the
    session's when its subject ends a line of one of the session's `git commit` commands, so sessions running at
    the same time are told apart;
  - its commits, their files, the screens those files show and the routes `HEAD` no longer has;
  - its hub files (those its Write and Edit calls wrote, or a Studio publish reply listed as `PUBLISHED <path>`)
    and its uncommitted files (those its Write and Edit calls wrote).
  What no session made (commits, hub files, uncommitted files) is a last request, *Not made by a playground
  session*. A request that made nothing is kept, marked: discussed, abandoned or made in another request.
- **Conductor.** Its token is read from `make playground`'s log, `$TMPDIR/agent-hub-conductor.log` (on macOS also
  the user's own temp folder, which a sandbox may hide behind another `$TMPDIR`; `--conductor-log` names it). When
  the conductor cannot be read, the export fails and writes nothing: the owner's words are its input.
- **Output.** `.playground/exports/<UTC stamp>/` in the checkout, ignored by git:
  - `brief.md`: the requests in the order the owner asked them, each with its turns, commits (subject and body),
    files, screens, hub files, uncommitted files and patch; then the shipped commits. An incomplete export says what
    is missing at the top.
  - `export.json`: `{base, head, created_at, requests: [{title, folder, started_at, sessions, turns: [{at, message,
    screenshot, answers, commits}], commits, files, screens, removed_screens, hub_files, in_progress, also_on,
    patch}], shipped, hub: {path, files}, in_progress, screens_skipped, complete}`.
  - `requests/<n>-<slug>.patch`: the request's commits as mail patches (`git format-patch`), oldest first.
  - `reference.patch`: every exported commit the same way.
  - `in-progress.patch`: the uncommitted changes, new files included (the index is not touched).
  - Generated files (`linguist-generated` in `.gitattributes`: `web_dist`, `openapi.json`, `schema.d.ts`…) stay out
    of every patch: a delivery regenerates them. Personal `*.local.*` files are never listed.
  - `screens/<area>/<route slug>.png`: each screen a request touches, captured once.
  - `hub/<path>`: a copy of each hub file.
- **Areas and screens.** A changed file belongs to the first matching area: `apps/web/src/screens/<name>/` is the
  screen `<name>`; `apps/web/src/shell/`, `apps/web/src/components/` and `apps/web/src/lib/` are `shell`;
  `packages/<pkg>/` is `<pkg>`; anything else is `repo`. A web area's routes come from `SCREEN_ROUTES` in the script
  (screen folder to the routes of `apps/web/src/routes.tsx` that show it, with the demo data's ids); `shell` takes
  the Portfolio, Sessions and Features. A route `HEAD`'s `routes.tsx` no longer declares goes to `removed_screens` and
  is not captured. The script checks `HEAD` out in a temporary worktree (sharing the checkout's `node_modules`, its
  packages ahead of the editable installs), builds the web app there, starts its `hub web` on a free port with a
  temporary database, loads `scripts/seed_demo.py` into it, and has Playwright capture each route at 1440 by 900,
  dark theme, the clock frozen and relative times masked.
- **Hub.** The project's hub (`--hub`, default `agent-hub-hub` next to the main checkout, as `make playground` makes
  it) is where Studio sessions write skills, agents and hooks, outside this checkout's git. Its files are those its
  git sees as new or changed (ignored files left out) that `hub sync` did not write as they are (`hub.lock`), and
  those of its commits since an hour before the range's first commit.
- **Mark.** Only a complete export (requests read, every screen captured) tags `HEAD`
  `playground-export/<UTC stamp>` (a local tag, never pushed), so the next one starts there. An incomplete one, or
  one run with `--no-screens`, is written but not marked: the next export covers the same range again, so nothing it
  missed is skipped for good.

### Delivering an export

A delivery per request (or per turn, when a long conversation asked for several things) goes through the normal task
workflow (`/feature` or the `sdlc` pack's `deliver`), on a branch from `main`, with the export folder as its input:

1. The spec's acceptance criteria are written from the request's turns, one per behavior the owner asked for or
   validated in an answer; the owner reviews them once (they already validated the behavior on screen). A hub file
   is delivered as the platform's own skill, agent or hook, or as the project's.
2. The request's patch is the target: the delivery may restructure, name and test the code, never change what a
   screen shows or what an action does. Requests touching the same file build on each other: a request's patch
   applies after the earlier requests' commits (`reference.patch` applies in order). A commit marked with another
   branch is delivered by that branch's PR when it lands first; the delivery then rebases on it.
3. Each captured screen becomes a visual test (`apps/web/e2e/visual/<area>.spec.ts`, Playwright
   `toHaveScreenshot`) with the export's PNG as its baseline, on the same synthetic data, viewport, theme and clock;
   a diff fails the delivery's check. Behaviors get unit or integration tests at the repo's levels.
4. The CHANGELOG entry and, for a scope or architecture change, the SPEC or an ADR come with it.

## Invariants

- Nothing the owner asked, answered or validated in the range is dropped: every commit not in `origin/main` is in a
  request (the last one if no session made it), every uncommitted and hub file too, and every turn of every session
  is kept.
- An export never changes the playground's files, index, branch or hub; its only write outside `.playground/` is the
  local tag (the temporary worktree is removed).
- Nothing from `~/.claude` or the owner's real data reaches a screen: screens use `seed_demo` data only.
- `brief.md` holds the owner's own words and stays in the ignored folder; a delivery commits criteria and tests
  derived from it, never the brief or a transcript (AGENTS.md rule 4).
- The same range exported twice yields the same requests, patches and screens, as long as no session and no branch
  moved in between.

## Decisions

- The request, not the folder, is the unit: a request's change crosses screens and packages (an API field and the
  screen that shows it), and only the whole of it can be delivered and tested.
- The owner's validation is in their later turns and answers, not in the first prompt: every turn is kept.
- Shipped means in `origin/main`. Another pushed branch is a PR that may still change or close, so its commits stay,
  marked, rather than vanish from the export.
- Screens from synthetic data, not from the playground's own database: only those can be a test baseline.
- A tag marks a complete export, so the next one starts where it ended without a state file.
- A request is tied to its commits by the session's own log, not by time: sessions run in parallel.
- A dirty tree is exported as `in-progress.patch`, not refused: the capture renders `HEAD` from a worktree, so edits
  in progress cannot leak into a baseline.
- The screenshots the owner sent are not exported: the server keeps no image bytes (the browser does); a turn only
  says one came with it.

## Open questions

- Light theme and narrower viewports as extra baselines, once a delivery needs them.
- Whether `hub` (not only agent-hub's own repo) should offer the export to other projects' playgrounds.
