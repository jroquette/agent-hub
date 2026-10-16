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
  `origin/main`; to `HEAD`. It refuses a dirty tree (exit 2: commit the step first), so the export is exactly a
  commit range. An empty range exits 0 with "nothing to export".
- **Output.** `.playground/exports/<UTC stamp>/` in the checkout, ignored by git:
  - `export.json`: `{base, head, created_at, groups: [{name, commits, files, screens, requests}]}`.
  - `brief.md`: the owner's requests (the title of each driven session of the `agent-hub` project created from
    an hour before the range's first commit to its last, read from the conductor's `/api/v1/agent-sessions`),
    then per group its commits (subject and body), files and screens.
  - `reference.patch`: `git diff base..HEAD`, the validated code.
  - `screens/<group>/<route slug>.png`: each route of the group, rendered by the `HEAD` code with synthetic data.
- **Groups.** A changed file belongs to the first matching area: `apps/web/src/screens/<name>/` is the screen
  `<name>`; `apps/web/src/shell/`, `apps/web/src/components/` and `apps/web/src/lib/` are `shell`;
  `packages/<pkg>/` is `<pkg>`; anything else is `repo`. A commit joins every group its files touch.
- **Screens.** A web group's routes come from `SCREEN_ROUTES` in the script (screen folder to the routes of
  `apps/web/src/routes.tsx` that show it, with the demo data's ids); `shell` takes the Portfolio, Sessions and a
  session chat. The script starts `hub web` from `HEAD` on a free port with a temporary database, loads
  `scripts/seed_demo.py` into it, and has Playwright capture each route at 1440 by 900, dark theme, the clock frozen
  and relative times masked. Without Chromium it writes everything but the screens and says so.
- **Mark.** On success it tags `HEAD` `playground-export/<UTC stamp>` (a local tag, never pushed) and prints the
  folder.

### Delivering an export

A delivery per group goes through the normal task workflow (`/feature` or the `sdlc` pack's `deliver`), on a branch
from `main`, with the export folder as its input:

1. The spec's acceptance criteria are written from `brief.md` and `reference.patch`, one per behavior the owner
   used; the owner reviews them once (they already validated the behavior on screen).
2. `reference.patch` is the target: the delivery may restructure, name and test the code, never change what a
   screen shows or what an action does.
3. Each captured screen becomes a visual test (`apps/web/e2e/visual/<group>.spec.ts`, Playwright
   `toHaveScreenshot`) with the export's PNG as its baseline, on the same synthetic data, viewport, theme and clock;
   a diff fails the delivery's check. Behaviors get unit or integration tests at the repo's levels.
4. The CHANGELOG entry and, for a scope or architecture change, the SPEC or an ADR come with it.

## Invariants

- An export never changes the playground's files or branch; its only write outside `.playground/` is the local tag.
- Nothing from `~/.claude` or the owner's real data reaches a screen: screens use `seed_demo` data only.
- `brief.md` holds the owner's own words and stays in the ignored folder; a delivery commits criteria and tests
  derived from it, never the brief or a transcript (AGENTS.md rule 4).
- The same range exported twice yields the same `export.json` groups, patch and screens.

## Decisions

- One export, many deliveries: groups keep a delivery to one screen or package, so a PR stays reviewable.
- Screens from synthetic data, not from the playground's own database: only those can be a test baseline.
- A tag marks the export, so the next one starts where this one ended without a state file.

## Open questions

- Light theme and narrower viewports as extra baselines, once a delivery needs them.
- Whether `hub` (not only agent-hub's own repo) should offer the export to other projects' playgrounds.
