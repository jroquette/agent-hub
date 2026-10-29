# 0054. Pin the platform release by commit

- Status: proposed (accepted at merge)
- Date: 2026-10-29
- Deciders: José Henrique Roquette

## Context and Problem Statement

Every `./hub` call runs the pinned release through `uvx --from <repository>@v<platform.version>`
([ADR 0013](0013-release-by-git-tags.md)). A tag is a git ref, so uv asks the remote what the tag points to on each
run, and the shim makes two uvx calls (`hub --version` to resolve, then the real call). That costs about 4.9 s on a
warm cache, on a path a person waits on. [ADR 0053](0053-interactive-path-latency-budgets.md) says no network call
with no cache may run on an interactive path.

A tag is never moved ([ADR 0013](0013-release-by-git-tags.md), [ADR 0047](0047-release-tag-by-workflow-dispatch.md)),
so the commit it names can be looked up once and reused. Where should that commit live, who looks it up, who checks
it, and when may the shim trust it?

Decision drivers:

- No network on the interactive path (ADR 0053).
- A tag never moves, so one lookup per version is enough.
- `hub sync` must keep working offline.
- Older hubs whose lock has no commit keep working.
- Private repositories, forks and mirrors in `platform.repository` work as today.
- A hand-edited lock must not quietly run other code.

## Considered Options

Where the commit lives:

- **A1. Two flat optional fields in `hub.lock`**, `platform_commit` and `platform_repository`, `lock_version` stays 1.
  Small change, the stdlib shim reader parses two flat keys, no migration. An older CLI refuses a lock that has them.
- **A2. A nested `platform: {version, commit, repository}` object in `hub.lock`**, `lock_version` 2. Cleaner shape,
  but it moves `platform_version`, so every reader changes and v1 locks need a migration.
- **A3. `platform.commit` in `hub.json`.** An upgrade becomes two hand edits that must agree, and no tool may write
  the seeded file ([ADR 0009](0009-hub-sync-by-file-ownership.md)); a typo runs other code.
- **A4. Both files.** A second source of truth and a mismatch case for every reader, for no gain over A1.

How the commit is found:

- **B1. `git ls-remote` of the tag at `hub sync`**, peeled `^{}` entry for an annotated tag, else the tag's own entry
  (lightweight). Uses the credential uv already uses, on any host. Needs the network once per pin change.
- **B2. The release workflow writes it.** Works only for the platform's own hubs; a value written into the generated
  lock by hand is the risk we want to avoid.
- **B3. The running CLI reads its own commit from uv's install metadata** (`direct_url.json`). No network ever, but
  not verified that uvx writes it, and absent for dev installs.
- **B4. The GitHub API.** github.com only, a new token path, rate limits. No gain over B1.

What `hub doctor` checks:

- **C1. Check the lock commit against the tag from the CLI.** Catches a forged or stale commit wherever doctor runs
  with network; costs one `ls-remote`.
- **C2. The same, only with a flag.** Doctor stays offline by default, but nothing runs the check unless asked.
- **C3. Always check, an unreachable remote is a warning.** Every offline run reports a warning it cannot fix.

Whether the shim trusts the lock commit:

- **D1. Trust it after offline checks, else use the tag.** No network, one uvx call.
- **D2. Check it against the remote on every run.** Strongest, but a network call on every `./hub`, against ADR 0053.
- **D3. Trust it and check in the background.** Extra moving parts for a check C1 already makes.

## Decision Outcome

Chosen options: **A1, B1, C1 and D1**, because the interactive path never reads the network, sync and doctor
(which are not interactive) do the one read each, a tag that never moves makes "look up once, check later" safe, and
older hubs and forks keep today's tag path.

- **The lock.** `hub.lock` gets two optional flat header fields: `platform_commit` (40 lowercase hex characters) and
  `platform_repository` (the repository the commit was read from). Both are set or neither is. `lock_version` stays
  1. A lock without them is byte for byte what the previous release wrote.
- **Who looks it up.** Only `hub sync`, and only on a pin change: when the lock's `platform_version` or
  `platform_repository` differs from `hub.json`. It runs `git ls-remote <repository> refs/tags/vX.Y.Z
  refs/tags/vX.Y.Z^{}`, with a timeout and a read cap, and takes the peeled entry when there is one. `hub init`,
  `hub sync --adopt` and a re-sync with an unchanged pin write or keep the commit with no network call. Sync never
  re-checks a commit it already holds.
- **Offline lookup.** When the lookup fails (no network, sandbox, no credential), sync writes the lock without a
  commit, prints one warning line naming the way back (restore `hub.lock` from git, then `hub sync` with network),
  and exits 0. The shim then uses the tag, as today.
- **`hub sync --check`** never uses the network. A lock that holds a commit is not a pending change, and neither is
  a missing commit.
- **Doctor.** `hub doctor` checks the commit against the tag only when the lock has a commit and `lock.drift` is
  selected, from the CLI only (the API never probes), with a 5 s timeout. A different commit, or a tag that no longer
  exists, is a `lock.drift` error with the fix "run hub sync". An unreachable remote gives one stderr note and no
  finding. A lock with no commit gives no finding.
- **The shim.** The shim (and SessionStart and cloud setup) uses `<repository>@<commit>` only when the lock's
  `platform_version` equals `platform.version`, the lock's `platform_repository` equals the repository in use, and
  the commit is 40 lowercase hex. Then it makes one uvx call. In every other case it uses `@v<version>` as today.

### What this supersedes

- [ADR 0009](0009-hub-sync-by-file-ownership.md), in part: the output was "a function of three inputs only". The
  release commit read at sync is now a fourth input to the lock. The rest of ADR 0009 stands.
- [ADR 0013](0013-release-by-git-tags.md), in part: the shim's `--from` source and its resolve step. With a matching
  commit in the lock, the source is the commit and there is one call; otherwise the tag source and the two calls stay.
  The rest of ADR 0013 stands.
- Both ADRs stay unedited, as accepted ADRs are never edited.

### Consequences

- Good: a `./hub` call with a commit in the lock makes no network call to resolve the release.
- Good: the lock states the exact code the hub runs, and that shows in PR diffs.
- Good: forks and mirrors stay safe: a change of repository makes sync look the commit up again and the shim fall
  back to the tag.
- Bad: the first sync after a pin change needs the network. Offline, the hub keeps the tag path until a sync with
  network.
- Bad: a release older than this one refuses a lock with the new fields. A downgrade needs `hub.lock` restored from
  git or `hub sync --adopt`. Accepted: it is rare and already needs a sync.
- Bad: doctor does one `ls-remote` when the lock has a commit, and hubs run doctor in pre-commit: about 0.3-1 s per
  commit, 5 s at worst.
- Neutral: a hub made by `hub init` uses the tag until its first pin change.
- Trust model: the shim trusts the lock commit after offline checks only. GitHub serves any commit of a fork network
  through the parent's URL, so a hand-edited commit could name code that is on no branch of the platform. The
  defences are the guard's ask before editing `hub.lock` ([ADR 0012](0012-cli-subsumes-hub-scripts.md)), PR review,
  and doctor's tag check, not the shim.

## More Information

- [SPEC](../SPEC.md): `hub.lock` and the pinned release.
- [design/hub-sync.md](../design/hub-sync.md): the lock and the sync plan.
- Follow-up: let the running CLI read its own commit from uv's `direct_url.json`, once verified, so a pin change needs
  no network either.
