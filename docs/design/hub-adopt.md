# Hub adopt: hub sync --adopt, --accept and the link migration

## Purpose

Phase 1 contract for `hub sync --adopt [--accept PATH]… [--check]`: how a hub made by hand, or one that lost its
`hub.lock`, joins the lock without overwriting what the project changed. The lock, plain sync, the read, the write
path and the conflict wording: [hub-sync.md](hub-sync.md). What is rendered and who owns it:
[hub-generator.md](hub-generator.md).

## Contract

### Load and read

Root, `hub.json` (pin, `schema_version`, model) and the one tree read are plain sync's, with the same exit-1 lines.
`hub.lock` may be absent; then no path has an entry. A lock that is a link, folder or other non-regular file, or is
malformed, exits 1 with sync's `hub.lock: …` lines, the last one `hub.lock: restore it from git, or delete it and re-run
hub sync --adopt`. Nothing is written before the plan (core `plan_adopt`) is whole. Before adopting, the owner edits
`hub.json` by hand: adds `schema_version`, `platform` and, if used, `modules`; guard paths rooted at a repo stay,
and one rooted at the hub's directory name becomes `@hub/…` (adopt rewrites no path).

### Per path

- **A path with a lock entry** follows plain sync's rule, rendered or not.
- **A rendered path with no entry:** managed and equal to its render (bytes and executable bit, or link target) →
  `recorded`; managed and absent → written, `created`; seeded and absent → written, `created` (an empty
  `plugin/<project>/` gets its `.gitkeep`); seeded and a regular file, whatever its bytes → `recorded`.
- **Listed:** a managed path with no entry, in its rendered place and of its rendered type, whose bytes, executable bit
  or link target differ. It stays as it is and out of the new lock.
- **Conflict:** any other path sync would refuse: a type misfit, a symlinked ancestor that is not a migration, a link
  resolving outside the hub, a name in both plugins, or sync's rule failing on a locked path. A conflict wins: a path
  that both differs and clashes is a conflict, never listed.

### Migration

A migration is a directory link on disk with no lock entry whose rendered descendants are all direct-child links (in
practice `.claude/agents` and `.claude/skills` from an older hand-made layout). It is listed once; the rendered paths
under it get no verdict and no lock entry, and its target is never opened or listed (only resolved, to tell whether it
leaves the hub). Resolving outside the hub, it is the conflict `resolves outside the hub`. Any other directory link,
or one under another linked ancestor, keeps sync's `symlinked ancestor A` per path; one with a lock entry follows
sync. A migration with a conflict under it (e.g. a name in both plugins) is not listed: it is listed only once that
conflict is fixed and adopt is re-run.

### Project guards

Where each project guard of the Loki hub goes on adoption. "Extension file" is the seeded
`plugin/<project>/hooks/project_guard.py` ([hub-generator.md](hub-generator.md), Hooks).

| Guard today | Covered by |
|---|---|
| Exchange-host denylist | `guard.deny_hosts` |
| `app_db` destructive-SQL check | extension file (needs command parsing specific to the project) |
| Docker / service check | extension file; the base guard keeps its generic docker-volume rule |
| `_archive/` denial | `guard.deny_paths` |
| `tests/invariants/` ask-before-edit | `guard.ask_before_edit` |
| Brain write roles (curator vs implementer) | extension file (role logic is project policy) |

### --accept

`--accept PATH` (repeatable) takes the render at a path this run lists, written exactly as listed (relative POSIX, no
`./`, no trailing `/`). A difference is overwritten with the template, `updated`. A migration's link is deleted (never
its target) and remade as a real folder holding one managed link per agent or skill entry of both plugins: `migrated`
for the link, `created` for each link under it. An accepted path leaves the listing and joins the lock.

Every other value refuses the whole run before anything is planned for writing: stderr gets one line per refused path,
in path order, `--accept <path>: <reason>`, with nothing written and exit 2. The reasons: `not listed by this run`
(including a path outside the render); `a conflict; --accept takes only listed differences and migrations`;
`not listed by this run: a conflict under it (<paths>)` for a migration a conflict holds back. Without `--adopt`,
`--accept` is a usage error (`needs --adopt`), exit 2, before anything is read.

### Apply and lock

Conflicts and listings do not stop the run: every settled path is applied, through sync's writer and in its order
(leftovers, deletes including a migrated link, folders, files, links), `hub.lock` last. The new lock is
`build_hub_lock` of the render minus every listed, conflicting or under-migration path, each of those keeping its
previous entry when it had one. It is written when there was no lock or its bytes differ. A run stopped by an I/O error
keeps the old `hub.lock` (absent or its prior bytes); a plain `--adopt` then ends where an uninterrupted run would (an
`--accept` of a link already migrated is refused, as it is no longer listed).

### Output and exit codes

- **stdout:** the change lines, sorted by path: sync's verbs plus `recorded P` and `migrated P`, then
  `removed N leftover temporary files`, then `updated hub.lock` last (also when there was no lock). With nothing to
  write, it is `up to date` only when the run is settled (nothing listed, nothing conflicting), and empty otherwise.
- **stderr**, when not settled: each listed path, sorted, one line with no digests:
  - text: `P: +a -b lines` (counted as sync's diff counts them), then
    `, executable bit differs (on disk +x, render -x)` when the bit differs too;
  - executable bit only: `P: +0 -0 lines, executable bit differs (on disk +x, render -x)`;
  - binary (not UTF-8, or a NUL): `P: binary content differs`, plus the same bit clause when it differs too;
  - link: `P: link target differs (on disk -> X, render -> Y)`;
  - migration: `P: migration: directory link -> T, rendered as N links`.

  Then each conflict as plain sync prints it (diff, binary line with digests, or cause), then one way out. Listings
  only: `take the template with --accept <path>, or move the change to an extension file, then re-run`. Any conflict:
  `move the change to an extension file (hub.json, a *.project.* file, Makefile.project), restore or delete the
  conflicting file, or take the template of a listed path with --accept <path>, then re-run hub sync --adopt`.
- **`--check`** writes nothing and prints the same lines with `would ` (`would record P`, `would migrate P`); with
  `--accept`, it previews the accepted writes.
- **Exits:** 0 settled (written or up to date); 1 error (config, lock, extension inputs, I/O), as sync; 2 usage or a
  refused `--accept`; 3 anything listed or conflicting (the settled paths applied unless `--check`); 4 `--check`,
  settled, with writes pending.

### In the hub's CI

Every hub's rendered `.github/workflows/ci.yml` (`init` and sync render the same file) has one job, `check`, run on
pull requests to (opened, synchronize, reopened, and edited, so a changed title or body is checked again) and pushes on
the default branch with read-only `contents`; each action is pinned by commit SHA, its release in a comment
(`# vX.Y.Z`). Steps: checkout (the whole history, credentials not kept), authorship (pull requests only), setup-uv,
credential, repos, golden, `make check`.

- **Authorship step** (`Authorship`, AGENTS.md rule 1, AGH-4): fails when the pull request's title, body or one of its
  commit messages (`base..head` of the event) carries AI attribution (the guard's `AI_ATTRIBUTION`), or, when an author
  email is known (`AUTHOR_EMAIL` in the step's env, else `hub.json`'s `project.author_email`), when one of its commits
  is authored or committed with another email; GitHub's own committer (`noreply@github.com`, a web edit or "Update
  branch") is let through. The title and body are read from the event file (`$GITHUB_EVENT_PATH`), never through an
  expression in the run block, and only commit SHAs and emails are printed. The platform's own `ci.yml` runs the same
  step, byte for byte, in its `authorship` job.

- **Credential step** (`Platform read credential`): reads `AGENT_HUB_READ_TOKEN`, a secret of the hub repository
  (Settings → Secrets and variables → Actions): a fine-grained personal access token or a GitHub App token with
  read-only Contents on the platform repository only. It reaches this step through `env`; the repos step reads its
  own secret, `HUB_REPOS_READ_TOKEN` (AGH-801), and those two are the only `secrets.` expressions in the file. Empty
  or unset, the step does nothing: a public platform needs no secret. On a private
  platform the shim then cannot fetch the pin, the golden step exits 1 and the job fails; so do fork pull requests and
  Dependabot pull requests, which get no Actions secrets (Dependabot needs the same name under Dependabot secrets).
  A token holding anything outside `[A-Za-z0-9_]` exits 1 with `AGENT_HUB_READ_TOKEN: unexpected characters`, before
  anything is written. Otherwise it appends `GIT_CONFIG_COUNT=2` and two `GIT_CONFIG_KEY_n`/`GIT_CONFIG_VALUE_n` pairs
  to `$GITHUB_ENV`, so every later step of the job has them: an `insteadOf` that rewrites the platform repository's URL
  to one carrying the token, and the hub's own GitHub URL mapped to itself (`insteadOf` takes the longest matching
  prefix, so the hub's own fetches never carry the token). The token is never written to a file in the repo: not in a
  URL, `hub.json` or `hub.lock`.
- **Repos step** (`Repos beside the hub`, AGH-699 A-13, AGH-801): clones each repo of `hub.json` (`repos[]`, read when
  the step runs) at its default branch (`repos[].default_branch`, else `project.default_branch`), depth 1, into
  `../<dir>` beside the hub, where `hub doctor`'s repo rules (`brain.leak`, `instructions.read_cap`, `links.dead`,
  `repos.agents`, `repos.ui_paths`) read it; without a checkout those rules report an `info` and `make check` passes.
  It reads its own secret, `HUB_REPOS_READ_TOKEN`, with read-only Contents on the hub's repos; in an organisation, the
  recommended source is a GitHub App installation token (`actions/create-github-app-token`, Contents read-only on the
  hub's repos) rather than a personal token. It never uses `AGENT_HUB_READ_TOKEN`: it drops the `GIT_CONFIG_*` the
  credential step put in the job's environment before cloning. With `HUB_REPOS_READ_TOKEN` set, each clone's
  `https://github.com/<owner>/<name>` maps to a URL carrying the token through `GIT_CONFIG_*` in the step's own
  environment (one repo at a time; never an argument, a file or `$GITHUB_ENV`, so no other step, the pinned release
  and `make check`'s hooks included, can read it), and a repo it cannot clone fails the step (`cannot clone
  <owner/name> (<branch>) into ../<dir>; HUB_REPOS_READ_TOKEN needs read access to it`): a configured credential that
  cannot read a repo is a misconfiguration. Unset or empty, the clones are anonymous: a repo they cannot read (a
  private one) is skipped with one notice (`skipped <owner/name> (<branch>): cannot clone it without
  HUB_REPOS_READ_TOKEN, so its repo rules run locally only`), the step passes and doctor reports that repo as not
  checked out. It also fails, nothing echoed but the repo's `owner/name`, branch and folder, on a token outside
  `[A-Za-z0-9_]` (`HUB_REPOS_READ_TOKEN: unexpected characters`) and on a `repos` entry whose `dir`, `github` or
  branch does not have the model's shape (`repos[<i>] in hub.json needs a dir, an owner/name github and a branch`,
  before any clone).
- **Golden step** (`Golden (hub sync --check)`): `./hub sync --check` through the pinned shim, before `make check`;
  it writes nothing, and any non-zero exit fails the job before `make check`. Exits (`--check`'s) and their fixes:
  - 0 up to date: the job goes on.
  - 4 changes pending (e.g. a commit missed `hub sync`, as after a pin bump): run `hub sync` locally and commit.
  - 3 a conflict (e.g. a managed file edited in the change, or a name in both plugins): take sync's way out
    ([hub-sync.md](hub-sync.md#output-and-exit-codes)): move the change to an extension file, or restore or delete
    the file, then re-run.
  - 1 a load error (e.g. `hub.json`, a missing or malformed `hub.lock`, extension inputs, I/O, or a pin the shim
    cannot fetch): fix the named input; for an unfetchable pin, check `AGENT_HUB_READ_TOKEN`.

## Invariants

- Adopt plans every path, and decides every `--accept`, before its first write; it never writes `hub.json`, never
  runs `git` or commits, and never reads or touches an entry neither rendered nor in the lock (sync's read), bar
  removing leftover temporary files in listed folders and listing the project's agent and skill entries.
- A listed or conflicting path is left byte-, mode- and target-identical; only `--accept` replaces it.
- Same `hub.json`, release, extension inputs and tree, same output, tree and `hub.lock` bytes. After a settled adopt
  the lock is `build_hub_lock` of the render, and the next `hub sync` or `--adopt` prints `up to date`.
- The planner is pure core code beside `plan_sync`; the generator's adapter reads and writes; `cli` composes.

## Decisions

- [ADR 0009](../adr/0009-hub-sync-by-file-ownership.md): adopt joins by ownership; a difference is listed, never merged.
- [ADR 0011](../adr/0011-templates-as-package-data.md): the planner in core, the file adapter in the generator, no port.
- [ADR 0013](../adr/0013-release-by-git-tags.md): a CLI other than the pin refuses, as for sync.
- Unlike plain sync, a conflict does not stop the settled writes: adopt is run on hubs that are known to differ, and
  each re-run narrows what is left. No new ADR: the ownership rule is unchanged.

## Open questions

- None.
