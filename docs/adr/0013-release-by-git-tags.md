# 0013. Release the hub CLI by git tags

- Status: proposed
- Date: 2026-09-28
- Deciders: José Henrique Roquette

## Context and Problem Statement

With the hub logic and the templates in the `hub` CLI ([ADR 0011](0011-templates-as-package-data.md),
[ADR 0012](0012-cli-subsumes-hub-scripts.md)), a hub is only reproducible if it names the exact CLI release it was
generated with, and every machine that works in it (the owner's, CI, cloud sessions) runs that same release. One
machine may hold several hubs that pin different releases. The agent-hub repository is private. Cloud sessions reach
the repositories attached to them through an authenticated git proxy, without a token of their own. How is the CLI
released, pinned and run?

## Considered Options

- **Semver git tags on agent-hub, each hub running its pinned release through `uvx`**: uv builds and caches each
  version on first use.
- **Semver git tags, one global `uv tool install` per machine**: every hub on the machine uses the installed release.
- **PyPI**: publish the distributions to the public index.
- **A private package index**: host the wheels on a private index.
- **A wheel vendored in each hub**: commit the built wheel into the hub and install it from there.

## Decision Outcome

Chosen option: **semver git tags on agent-hub, each hub running its pinned release through `uvx`**, because git is
already the one channel every environment can reach, a tag gives an exact, immutable version with no extra
infrastructure, and a per-hub pin lets hubs on one machine upgrade independently.

- A release is a semver tag `vX.Y.Z` on `main`, created by the owner. There is no PyPI release and no private index.
- The tag equals the version of the `agent-hub` meta-package, and `hub --version` prints that version. A release check
  in CI runs on every `v*` tag and fails when the tag differs from the meta-package version. The component
  distributions keep their own versions, as [ADR 0007](0007-git-and-change-flow.md) plans per-package versions.
- `hub.json` pins the release in `platform.version` ([ADR 0010](0010-hub-json-config-contract.md)), and `hub.lock`
  records the version the managed files were generated with ([ADR 0009](0009-hub-sync-by-file-ownership.md)).
- Every shim of a generated hub (the launcher, the Makefile targets, the SessionStart brief call) runs the pinned
  release:
  `uvx --from git+https://github.com/jroquette/agent-hub@v<platform.version>#subdirectory=packages/agent-hub hub …`.
  The root `pyproject.toml` is a virtual workspace, so the meta-package subdirectory must be named; uv resolves the
  other workspace members from the same checkout and caches each version. No global install is required. Using `hub`
  outside a hub (for example `hub init`) takes the same `--from` source with `uvx` or `uv tool install`.
- Reading the private repository needs a credential wherever agent-hub is not attached: a read-only secret in each
  hub's CI, and the repository attached or a `GH_TOKEN` in cloud sessions of other projects. The `cloud` module's
  setup script checks that access and warms the uv cache with the pinned release before it fetches the repositories.
- Mismatch: a `hub` run directly whose version differs from `platform.version` refuses `hub sync` (exit 1, printing the
  pinned `uvx` command), and `hub doctor` reports it as an error. Upgrading a hub is: edit `platform.version`, run
  `hub sync` through a shim.

### Consequences

- Good: a hub states exactly which CLI generated it, and the same tag runs everywhere.
- Good: hubs on one machine pin different releases without interfering; no install step to forget.
- Good: no publishing credentials and no package index to run; the private repository stays private.
- Bad: the first run of each version builds the wheels from git, which is slower than a download; the SessionStart
  brief may time out on that run and fall back to the stdlib brief.
- Bad: every place that runs a shim needs uv and read access to agent-hub, so hub CI carries a read-only secret and
  cloud sessions of other projects need the repository attached or a token.
- Bad: tags are created by hand until the release tool from ADR 0007 exists; a wrong tag is fixed by a new tag, never by
  moving one.
- Neutral: one global install was rejected because it forces every hub on a machine to upgrade together; PyPI was
  rejected because the repository and its templates are private; a private index was rejected as infrastructure and
  credentials to maintain, which cloud sessions could not reach without a token; a vendored wheel was rejected because
  it puts build artifacts in every hub and a new binary in every upgrade diff.

## More Information

- [design/hub-generator.md](../design/hub-generator.md): the Distribution part (pin, shims, credentials, mismatch).
- [design/project-config.md](../design/project-config.md): the `platform.version` field.
