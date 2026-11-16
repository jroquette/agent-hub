# 0040. hub web keeps local settings, writes some hub files without committing, and runs recorded checks

- Status: proposed
- Date: 2026-10-18
- Deciders: José Henrique Roquette
- Relates to: [ADR 0024](0024-learning-actions-from-the-app.md) (the app's hub writes go through a pull request),
  [ADR 0025](0025-reading-the-tracker-from-the-app.md) (Linear is read with `LINEAR_API_KEY` from the server's
  environment), [ADR 0036](0036-live-playground-and-auto-mode.md) (the playground where these actions were validated),
  [ADR 0039](0039-item-versions-and-server-writes-to-the-hub.md) (the server writing into a hub's tree)

## Context and Problem Statement

In the playground of 2026-10-17/18 (AGH-314) the owner asked for actions the control plane could not take: connect Linear
without restarting `hub web` with a new environment, mark a feature's owner steps done, bring a hub to the running release,
fix the doctor findings that need no person, run an acceptance criterion's check, rename a feature for display, and edit
their own `hub.local.json`. Each of them makes `hub web` store something, write into a hub, or run a command. Until now it
did that only through a hub pull request (ADR 0024) or in a hub file the owner publishes (ADR 0039). Where does each of
these writes go, which ones may skip the pull request, and how are they gated?

## Considered Options

1. Per-machine values under the user's agent-hub config folder; hub writes that the hub's own CLI would make, left
   uncommitted in the hub's checkout for the owner's hub PR; checks run from what `features.json` records, never from the
   browser. Every new write route behind the local server's checks.
2. Everything through a hub pull request, as the learning decisions do (ADR 0024).
3. Leave these actions to the terminal (`hub sync`, `hub doctor --fix`, editing files by hand).

## Decision Outcome

Chosen option: 1, the behavior the owner validated on screen.

- **Per machine, never in a hub or a repo.** The Linear key saved from Settings is `linear-api-key` beside the hub
  registry (`~/.config/agent-hub`), mode 0600; it is checked with one `viewer` read before it is saved, never returned or
  logged, and `LINEAR_API_KEY` in the environment still wins (ADR 0025 keeps holding: the server reads Linear, the
  browser never does). Feature nicknames are `feature-names.json` in the same folder, keyed by `<project>/<slug>`; the
  slug stays the feature's identity.
- **Into the hub, uncommitted.** The owner sign-off writes a new eval note (`owner-signoff`, `-rN` when taken) with
  `provenance: owner`, created exclusively and never overwriting one; `POST /hubs/{id}/platform-sync` rewrites only the
  `platform.version` pin and runs the running release's `hub sync`, putting the old pin back when the sync fails;
  `POST /hubs/{id}/doctor-fix` runs `hub doctor --fix --json`, which writes only `brain/`. `PUT
  /projects/{project}/config/local` rewrites the keys the Hub config screen edits in the developer's `hub.local.json`,
  keeps the others, validates the result with the CLI's model first and never touches `hub.json`. None of them commits:
  the owner reviews the changed files and opens the hub PR, as after running the same CLI in a terminal.
- **Checks.** `POST /features/{project}/{slug}/acs/{ac}/check-runs` runs the command `features.json` records for that AC
  (the browser names the AC, never a command) with `/bin/sh -c` in the AC's repo checkout, without `LINEAR_API_KEY`, in
  its own process group killed after 600 s. Nothing is recorded: the evaluator's evidence stays the only proof.
- **Gates.** The run and the check are run writes (`local_security.RUN_WRITES`: session cookie, own `Origin`, JSON body);
  the platform sync, the doctor fix and `hub.local.json` are hub registry writes (own `Origin` required, a missing one
  too); the other writes keep the local server's checks (loopback `Host`, a cross-site `Origin` refused).

### Consequences

- Good: the owner does from the app what they did in the terminal, and reviews the same diffs before a hub PR.
- Good: no secret reaches a hub, a repo or the browser; a key in the environment keeps its old meaning.
- Bad: a hub's checkout can hold uncommitted changes made by the app; the result screens say so and name the files.
- Bad: a check run executes a command recorded in the hub. It is the same command `/evaluate` runs, but from a click; a
  hub whose `features.json` is not trusted should not be registered.

## More Information

Delivered in agent-hub by AGH-314 (one PR), from the playground export `20261018T113227Z`. The record of the delivery is
the hub's `brain/features/playground-20261018/`.
