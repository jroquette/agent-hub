# 0013. Release the hub CLI by git tags

- Status: proposed
- Date: 2026-09-28
- Deciders: José Henrique Roquette

## Context and Problem Statement

With the hub logic and the templates in the `hub` CLI ([ADR 0011](0011-templates-as-package-data.md),
[ADR 0012](0012-cli-subsumes-hub-scripts.md)), a hub is only reproducible if it names the exact CLI release it was
generated with, and every machine that works in it (the owner's, CI, cloud sessions) installs that same release. The
agent-hub repository is private. Cloud sessions reach the repositories attached to them through an authenticated git
proxy, without a token of their own. How is the CLI released, pinned and installed?

## Considered Options

- **Semver git tags on agent-hub, installed with `uv tool install git+…`.**
- **PyPI**: publish the distributions to the public index.
- **A private package index**: host the wheels on a private index.
- **A wheel vendored in each hub**: commit the built wheel into the hub and install it from there.

## Decision Outcome

Chosen option: **semver git tags on agent-hub**, because git is already the one channel every environment can reach,
including cloud sessions through the proxy, and a tag gives an exact, immutable version with no extra infrastructure.

- A release is a semver tag `vX.Y.Z` on `main`, created by the owner. There is no PyPI release and no private index.
- The tag equals the version of the `agent-hub` meta-package, and `hub --version` prints that version. The component
  distributions keep their own versions, as [ADR 0007](0007-git-and-change-flow.md) plans per-package versions.
- Install command (the root `pyproject.toml` is a virtual workspace, so the meta-package subdirectory must be named):
  `uv tool install git+https://github.com/jroquette/agent-hub@vX.Y.Z#subdirectory=packages/agent-hub`. uv resolves the
  other workspace members from the same checkout.
- `hub.json` pins the release in `platform.version` ([ADR 0010](0010-hub-json-config-contract.md)), and `hub.lock`
  records the version the managed files were generated with ([ADR 0009](0009-hub-sync-by-file-ownership.md)).
- The cloud setup script of a generated hub reads `platform.version` and runs the install command above before it
  fetches the repositories.
- Mismatch: when the installed CLI differs from `platform.version`, `hub sync` writes nothing and exits 1 with the
  install command, and `hub doctor` reports it as an error. Upgrading a hub is: edit `platform.version`, install that
  release, run `hub sync`.

### Consequences

- Good: a hub states exactly which CLI generated it, and the same tag installs everywhere.
- Good: no publishing credentials and no package index to run; the private repository stays private.
- Bad: installing from git builds the wheels on each machine, which is slower than downloading them.
- Bad: tags are created by hand until the release tool from ADR 0007 exists; a wrong tag is fixed by a new tag, never by
  moving one.
- Neutral: PyPI was rejected because the repository and its templates are private; a private index was rejected as
  infrastructure and credentials to maintain, which cloud sessions could not reach without a token; a vendored wheel
  was rejected because it puts build artifacts in every hub and a new binary in every upgrade diff.

## More Information

- [design/hub-generator.md](../design/hub-generator.md): the Distribution part (pin, cloud install, mismatch).
- [design/project-config.md](../design/project-config.md): the `platform.version` field.
