# 0016. Per-developer identity: `hub.local.json`, then `hub.json`, then git config

- Status: accepted
- Date: 2026-10-03
- Deciders: José Henrique Roquette

## Context and Problem Statement

`hub.json` is committed and shared by everyone who uses a hub, yet three of its required keys belong to one developer:
`project.branch_prefix`, `project.author_name` and `project.author_email`
([ADR 0010](0010-hub-json-config-contract.md)). A teammate on the owner's hub gets the owner's branch prefix in
`hub worktree`, `hub run` and the guard's branch hint, the owner's name in the rendered `AGENTS.md` rule and the
marketplace owner, and, through the cloud module, the owner's name written into their global git config. Where does
each developer's identity come from, in the CLI and in the hooks, without making rendered files differ per developer and
without breaking hubs that keep the identity in `hub.json`?

## Considered Options

- **Keep the keys required in `hub.json`.** A team forks the hub or each developer edits it locally.
- **Order `hub.local.json`, then git config, then `hub.json`** (the row in `docs/SPEC.md` before this decision).
- **Order `hub.local.json`, then `hub.json`, then git config**, the prefix derived from the effective email.
- **Environment variables only** (`HUB_AUTHOR_NAME`, `HUB_BRANCH_PREFIX`, ...).
- **Render per developer**: `hub sync` writes each developer's identity into `AGENTS.md`.

## Decision Outcome

Chosen option: **`hub.local.json`, then `hub.json`, then git config**. A single-developer hub keeps working untouched,
and a team hub omits the keys. Git config comes last because a cloud container starts with the agent's identity in git
config, which must never override a hub that sets its own. The first option makes the committed file wrong for
everyone but one developer. The second lets a container's git identity win over a single-developer `hub.json`.
Environment variables do not reach the hooks reliably, since Claude Code starts them with its own environment. Rendering
per developer makes every `hub sync` diff.

- **Precedence, per key.** `project.author_name`, `project.author_email` and `project.branch_prefix` each take the first
  of: the gitignored `hub.local.json`, `hub.json`, then the hub repo's `git config user.name`/`user.email` (as
  `git config --get` resolves them in the hub's main checkout, with `GIT_DIR`, `GIT_WORK_TREE` and `GIT_COMMON_DIR`
  dropped). A git value loses one trailing newline and must then match `hub.json`'s pattern and be valid UTF-8, else it
  counts as unset. `branch_prefix` has no git key. When no file sets it, it is
  derived as the local part of the effective `author_email` plus `/`. A derived value that fails the `branch_prefix`
  pattern counts as no prefix; it is never normalized. Git is read only for a key no file sets, and only when a
  consumer needs it.
- **`hub.local.json`.** It lives at the root of the hub's main checkout, never beside a `$HUB_CONFIG` file and never in a
  hub worktree; hooks loaded from the plugin cache with `$HUB_CONFIG` read no local file and no git. It has `hub.json`'s nesting and accepts only the three identity keys and `tracker.transport`, with
  `hub.json`'s patterns, plus `_` comment keys. It is at most 64 KiB. The CLI rejects anything else (one line per
  problem, `hub.local.json: <json path>: <message>`). The hooks' stdlib reader never raises: it ignores an unreadable or
  non-object file as a whole, and a bad key on its own. Nothing in it can add or remove a guard path, host, protected
  branch or repo.
- **Rendering reads `hub.json` only.** `hub init`, `hub sync` and `render_hub` never read `hub.local.json` or git
  config for identity. With the keys in `hub.json`, `AGENTS.md` and `marketplace.json` are byte-identical to before.
  Without them, `AGENTS.md` says commits are authored by the developer running the session and how the prefix is
  found, and the marketplace owner is the project name.
- **Commands.** `hub worktree` (create and `--remove`) and `hub run` refuse with a usage error, before any git write,
  when no source yields a prefix or `hub.local.json` is invalid. The message names the three sources. Hooks fall back to an empty prefix in the branch hint. `hub doctor` reports a derived
  prefix as an info finding (`config.identity`, which can be disabled but never retuned, so every developer's run
  exits alike) and a bad `hub.local.json` as a `config.schema` error. Doctor's file
  rules keep using `hub.json` values only, so their findings are the same for every developer.
- **Cloud setup.** With the author in `hub.json`, nothing changes. Otherwise the module script writes
  `HUB_AUTHOR_NAME`/`HUB_AUTHOR_EMAIL` (set per developer in their cloud environment) to the repo-local git config of
  the hub and each repo, never the global one. Without them it warns and writes nothing.
- **Versioning.** Making required keys optional is additive under `schema_version: 1` (ADR 0010, Versioning).

### Consequences

- Good, because one hub serves a team: each developer's branches, commits and guard hints carry their own identity.
- Good, because single-developer hubs need no change and keep their rendered bytes, worktrees and guard reasons.
- Good, because committed files stay deterministic: `hub sync` never diffs between developers.
- Bad, because there are now two readers of a second file (the CLI's model and the hooks' stdlib reader). A shared case
  table, run against both, keeps them equal.
- Bad, because `.gitignore` is seeded: an existing hub must add the `hub.local.json` line by hand (README).
- Neutral, because `hub init` still fills the identity from flags or git into `hub.json`. A team mode for `hub init`
  belongs to `hub setup` (AGH-71).

## More Information

- Spec, research and plan: the hub's feature record `per-developer-identity` (AGH-65).
- Contract: [docs/design/developer-identity.md](../design/developer-identity.md); fields in
  [docs/design/project-config.md](../design/project-config.md); `docs/SPEC.md` § Team use and per-repo config.
- Builds on [ADR 0010](0010-hub-json-config-contract.md) (the `hub.json` contract), which stays accepted.
