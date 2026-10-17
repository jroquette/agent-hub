# 0038. Declared environments, services and blocked words in `hub.json` and `hub.local.json`

- Status: proposed
- Date: 2026-10-17
- Deciders: José Henrique Roquette
- Partially supersedes: [ADR 0010](0010-hub-json-config-contract.md), for who writes `hub.json` (0010 is not
  edited); [ADR 0016](0016-per-developer-identity.md), for the keys `hub.local.json` accepts, its one writer and how
  the hooks treat an unusable file (0016 is not edited)

## Context and Problem Statement

Multi-repo projects run services (APIs, databases, queues, web portals) across several environments: a local stack, a
replica one developer owns, a shared test environment, production. Agents do not know which services exist, where they
run or where they may operate, and the only guard against production is `guard.infra.prod_markers` and
`guard.deny_hosts`, which cover infra commands only: `psql -h demo-prod-db`, a `curl` to a production API or reading a
production config file passes. `hub.local.json` accepts only identity keys and `tracker.transport`, so a developer
cannot declare their own replica. Where are environments declared, who may change them, how do agents see them, and
what does the guard enforce?

## Considered Options

1. Declare environments and services in `hub.json` (and the developer's own in `hub.local.json`), render the committed
   ones into `AGENTS.md`, show both files in the SessionStart brief, and let the guard enforce a user-chosen list of
   blocked words; `access` (`read`, `write`, `ask`) is an instruction only.
2. Option 1 with the guard also enforcing `access`.
3. A separate environments file (`environments.json`) with its own model and reader.
4. Render local environments into a gitignored `CLAUDE.local.md`.

## Decision Outcome

Chosen option: 1.

- `hub.json` (additive under `schema_version: 1`) gains `environments` (an object keyed by name: `access` required,
  `production`, `description`, `credentials` as an AWS profile name and variable names only), `repos[].services`
  (keyed by name: `kind`, `description`, `endpoints` per declared environment, each a `url` without user info, query
  or fragment, or a `resource`), and `guard.blocked_words`, `guard.blocked_words_files` and `guard.blocked_words_env`.
  Secret-looking values are rejected with doctor's secret shapes, which move to a neutral core module. No behaviour
  comes from a name: `production: true` is a flag, and an environment named `production` without it is ordinary.
- `hub.local.json` also accepts the developer's own environments (new names only), endpoints on them for `hub.json`'s
  repos, a stricter `access` on a committed environment (`write` → `ask` → `read`; nothing else on that entry), and
  the three blocked lists, which add to the team's. Every other `guard` key stays hub.json-only. The CLI and doctor
  reject a local file that would add to or loosen a committed environment or endpoint.
- **Writers.** `hub init` and `hub env` (without `--local`) write `hub.json`; `hub setup` (identity, new file only),
  `hub env --local` and setup's environments step write `hub.local.json`. `hub env` validates the result before
  writing, keeps the key order, and refuses when the file changed since it was read.
- **Rendering reads `hub.json` only** (as ADR 0016): `AGENTS.md` gets an "Environments and services" section only when
  `hub.json` declares `environments`; a hub without it renders byte for byte as before. Local environments reach the
  developer's agent through `hub brief` (and the hooks' fallback brief), never a rendered file.
- **The guard.** A blocked word (case-insensitive, bounded by anything that is not an ASCII letter, digits included,
  so `prod` matches `my-prod-db` and `prod2` but not `product`) denies a Bash command (three views of its text: raw,
  backslash-newlines joined, quotes and backslashes removed), every Bash call while a scanned session variable holds
  one, a file tool whose path holds one, and a read of a `.env*` or listed file whose contents hold one. The scanned
  variables are values only, of a fixed set of selector and connection names, every declared `credentials.env` name
  and every `guard.blocked_words_env` name (a trailing `*` is a prefix).
- **One rule order.** The blocked-word rule runs first on every surface and wins over any declared access and over a
  `guard.infra.allow` match; a deny is final, so the project extension does not run. It never opens a file the
  secret-file rule treats as secret: that file keeps the secret-file reason, unless its path or the command text holds
  a word.
- **Bounds.** 1 MiB per command text or file, 64 files and 4 MiB per call, 300 ms for the views, the variables and the
  files together; over a bound, or on a file that is not regular, the guard asks.
- **Layers.** The CLI, doctor and the brief union `hub.json` and `hub.local.json`; the hooks also add a `hub.json`
  named by `$HUB_CONFIG` (a hooks-only layer, since no command reads it). No layer removes an entry.
- **Unusable `hub.local.json`** (not JSON, not an object, not a regular file, over 64 KiB) makes the guard ask on
  every Bash and file-tool call until it is fixed, since the developer's own words would otherwise stop applying
  silently. An absent file changes nothing. (ADR 0016 had the hooks ignore such a file.)
- `access` is not enforced by the guard: it cannot tell a read from a write in `psql`, `curl`, `aws` or an SDK script.
  It is rendered as an instruction; `write` covers data, never a deploy, and production deploys stay forbidden by the
  cross-repo rules.
- Doctor gains `environments.production`, an ordinary `doctor.rules` entry (it can be disabled or retuned): a warning
  per production environment with `write` or `ask`, an info with `read`. Sync, setup and `hub env` print one line per
  production environment whatever doctor's settings.

### Consequences

- Good: agents know which environments and services exist and how to reach them, without credentials in any file.
- Good: a blocked word stops the commands, files and sessions that name it, across tools, with the word, layer and
  surface named in the reason and recorded with `rule: blocked_word`, never the value.
- Good: a developer's own replica and stricter rules live in their own file and never change the team's.
- Good: "nothing in `hub.local.json` relaxes a guard" still holds: it adds words and tightens access only.
- Bad: false positives are accepted (a word in a harmless command denies it, `prod2` included); the list is the
  user's to tune.
- Bad: `access` is advisory; an agent that ignores its instructions is held only by blocked words and the existing
  guards.
- Bad: two more writers of config files that were write-once; `hub env` guards against concurrent edits but a writer
  between its check and its replace can still be overwritten (a narrow window, documented).
- Bad: blind spots: variables a SessionStart hook exports through `$CLAUDE_ENV_FILE` reach Bash but not the guard
  hook; `hub run`'s implement sessions run without the hub's hooks (an older gap, tracked separately); plugin-cache
  mode with `$HUB_CONFIG` reads no `hub.local.json`; tool output, obfuscated names, Grep's search regex and edit
  contents are not checked.

## More Information

- AGH-277 (spec, plan and tickets).
- Contract: [docs/design/environments.md](../design/environments.md); keys in
  [project-config.md](../design/project-config.md) and [developer-identity.md](../design/developer-identity.md).
- Option 2 was rejected because a read/write classifier over arbitrary commands would be wrong often enough to give
  false safety; option 3 because it would need a third reader and schema for one contract; option 4 because a rendered
  file would read `hub.local.json` (against ADR 0016), sit outside `hub.lock` and go stale without `hub sync`.
