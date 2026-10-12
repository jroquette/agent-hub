# 0024. Learning actions from the app open hub pull requests through a `hub_git` adapter

- Status: accepted
- Date: 2026-10-12
- Deciders: José Henrique Roquette (D2; design delegated to the lead for AGH-201)

## Context and Problem Statement

Learnings are notes under a hub's `brain/_inbox/`. The owner wants to read them and accept or reject them from
`hub web`. The brain rules say only the user restructures `brain/`, nothing lands on the default branch without a PR
he merges, and commits carry his identity with no agent attribution. Phase 2 kept the API read-only except hub
registration and hook posts, and `api` must not import `cli` (ADR 0017), where today's git and `gh` code lives. How
does the app act on a hub safely, and where does that code go?

## Considered Options

1. Record `learning.accepted`/`.rejected` events only; the user moves the note by hand (no write, but the owner still
   has to go to git, which is the complaint).
2. Write the move into the user's hub checkout (changes his working tree and index; races with his own work).
3. Open a pull request in the hub repo from a temporary clone, through a core port and a new adapter package that only
   `api` wires.
4. Reuse `cli`'s `pr_steps` (breaks the import contracts: `api` never imports `cli`).

## Decision Outcome

Option 3.

- **Port.** `BrainChangeRequests` (`agent_hub.core.learnings.brain_change_requests`): `availability(hub_path)` (why
  actions are unavailable, or None), `accept(change)`, `reject(change)`; a `BrainChange` names the hub folder, its
  GitHub repo and default branch, the action, the inbox note, its destination, the frontmatter to set, the author, the
  branch, title, body and commit message. Core's `DecideLearning` checks, in order, the learning's state, the hub's
  availability and the destination rules, builds the change (title, body and reason redacted with `r1`; title at most
  72 characters, reason 300), calls the port, then stores one `learning.accepted` or `learning.rejected` event from the
  new source `control_plane` (session `control-plane`, agent `you`, `source_id` `learning:<id>:<accepted|rejected>`;
  keys `proposal`, `brain_path`, `reason`, `pr_url`, `branch`, `state`, `author`). A refusal or a failed port call
  stores nothing. One action runs per hub at a time; a second one meanwhile is refused, not queued.
- **Adapter.** A new package `packages/hub_git` (`agent-hub-hub-git` 0.1.0, outside the CLI's lockstep,
  `agent_hub.hub_git`) implements it with `git` and `gh` as child processes: argv lists, no shell, an empty stdin, no
  terminal prompt, git's location variables removed, stderr discarded, stdout read only to parse, and one 60 s
  deadline for the whole action that kills a child's process group. It refuses a hub whose `origin` is not the
  `project.hub_repo` of `hub.json`. It clones the hub's `origin` into a temporary folder, borrowing the local objects
  (`--reference-if-able`, `--no-checkout`, `--single-branch`), so the user's checkout, its index, its refs and its
  worktree list are never touched; checks that the note is a regular UTF-8 file of at most 256 KiB on
  `origin/<default_branch>`, and that the destination and the branch are free; builds one commit with plumbing (no
  checkout, no hook) that moves the note and sets its frontmatter (accept: `status: accepted`, `last_verified`;
  reject: `status: rejected`, `rejected_reason`, `rejected_at`, into `brain/_inbox/_archive/`), authored and committed
  as the hub's effective identity (ADR 0016) with no trailer; pushes one new branch
  `<branch_prefix>learning-<accept|reject>-<note slug>` with `--no-verify`; opens the PR with `gh pr create`, whose
  printed URL must be `https://github.com/<hub_repo>/pull/<n>`; and always removes the temporary folder. A push guard
  refuses, before git runs, the default branch or any `refs/` name, a `+` or `:` refspec, any option such as `--force`
  or `-f`, an invalid ref name, and any branch outside `<branch_prefix>learning-`. If `gh` fails after the push, the
  adapter deletes the branch it just pushed (a 15 s budget of its own), so a retry starts clean. No git or `gh` output
  is logged, kept or put in an error.
- **Import rules.** `hub_git` imports only `core` and sits in the adapters' layer beside `storage`, `collector`,
  `generator` and `tracker_linear`; `api` (composition root) wires it; `core` must not import it.
- **HTTP.** `POST /api/v1/learnings/{learning_id}/accept` (`{"target"}`, 1 to 200 characters: a brain folder or a
  `.md` path) and `/reject` (`{"reason"}`, 1 to 300 once stripped), 201 with `{state, pr_url, branch}`. Beyond the
  existing `Host` check, these two routes require an `Origin` equal to the server's own, refuse a `Sec-Fetch-Site`
  other than `same-origin`, and accept only `application/json` (415 otherwise). Conflicts (already decided, another
  action running, target taken or not allowed, note not on the default branch, a refused push, hub read-only) are 409
  with a `code` and a `reason`; a failed git or `gh` step is 502 "Could not open the pull request" naming the `step`;
  the deadline is 504.
- **Read-only hubs.** When the server runs in the container image (`AGENT_HUB_IN_CONTAINER=1`), the hub folder is
  missing or not writable, `git` is missing, the folder is not a git checkout's root, `origin` is not on GitHub, `gh`
  is missing or not signed in, or the hub has no author, learnings carry `actions_unavailable` with that reason and
  the POSTs answer 409. The composition caches a hub's availability for 10 s; the action checks it again, uncached.
- **States.** A decided learning is `accepted_pr_open` or `rejected_pr_open` until the note is found at its
  destination in the hub checkout, which makes it `in_brain` or `archived`; GitHub is never asked whether the PR merged.

### Consequences

- Good: the owner decides from the app; every change is still a PR he reviews and merges, authored as him.
- Good: the user's checkout is provably untouched (tests compare `HEAD`, `git status` and `git for-each-ref`).
- Bad: the server now reaches the network on an explicit action (`origin` and GitHub, with the user's own
  credentials), a single, documented exception to "local only".
- Bad: states stop at "PR open" until the user pulls; "in brain" and "archived" are inferred from the hub checkout.
- Bad: one more package to register in the gates (mypy, import-linter, coverage, PR scopes).

## More Information

Control-plane clarity spec (AGH-201) D2, S5 to S7, L5, L6, L8 to L13, AC-201.20 to AC-201.31;
[ADR 0016](0016-per-developer-identity.md) (identity), [ADR 0017](0017-api-second-composition-root.md) (api as a
composition root), [API.md](../API.md) "Local security" and "Learning decisions".
