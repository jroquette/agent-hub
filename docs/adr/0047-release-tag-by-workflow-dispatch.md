# 0047. The release tag is created by a dispatched workflow

- Status: accepted. Accepted by the owner, José Henrique Roquette, on 2026-10-22 (the owner decisions for AGH-455).
- Date: 2026-10-22
- Deciders: José Henrique Roquette
- Partially supersedes: [ADR 0013](0013-release-by-git-tags.md), only for who creates the release tag ("created by
  the owner"); semver tags on `main`, the per-hub `uvx` pin, the credentials and the mismatch rules of ADR 0013 stand.
  ADR 0013 is not edited.

## Context and Problem Statement

ADR 0013 makes a release a semver tag `vX.Y.Z` on `main`, created by the owner. In practice a release took many manual
steps: the owner bumped the versions through a PR, then created and pushed the annotated tag by hand. The v0.20.0 tag
went out lightweight, so the release check in `release.yml` failed, and since a tag is never moved, the only fix is a
new patch release. The `/release` skill already proposes the version, checks the exact commit and writes the notes; the
hand-made tag is the step that keeps going wrong. Who creates the tag, and how, so that an agent can run the whole
release without ever creating or pushing a tag itself?

## Considered Options

- **A `workflow_dispatch` job in `release.yml` creates the annotated tag**: the agent dispatches it with the version,
  the full SHA and the notes, after the owner confirmed version and SHA at the `/release` gate.
- **The owner keeps creating the tag by hand** (ADR 0013 as it is), with the skill printing the commands.
- **The agent session creates and pushes the tag** with a token that can write tags.
- **GitHub Releases** (the UI or `gh release create`) creates the tag.

## Decision Outcome

Chosen option: **a `workflow_dispatch` job in `release.yml` creates the annotated tag**, because the tag is then always
made the same way (annotated, the notes verbatim as its message, on the confirmed commit), its checks run before and
after it in one place, and the session only dispatches a workflow: by rule, the agent never creates or pushes a tag
itself; only the dispatched workflow does. A `v*` tag ruleset that lets only the workflow create tags would enforce
this rule; it is not set up yet (the owner's choice), so today the rule and the workflow's refusals hold it.

- `release.yml` gains a `workflow_dispatch` trigger with three inputs: `version` (`X.Y.Z`), `sha` (the full commit)
  and `notes` (the release notes, the tag message). The inputs reach the shell only through `env:`.
- Its `release-tag` job runs on a dispatch, with `contents: write`, and fails unless it comes from `main`. It refuses
  a malformed version or SHA, empty notes, a commit that is not on `main`, a commit whose declared versions differ
  from `version` (`scripts/check_release.py` on that commit's files, in a step without the token), and a tag that
  already exists on the remote, because a tag is never moved. Then it runs `git tag -a "v$VERSION" --cleanup=verbatim -F <notes> "$SHA"`
  and pushes that one tag, from the only step that holds the token.
- The run is named `release v<version> at <sha>` (`run-name`), so the `/release` skill finds the run it dispatched.
- The tagger is `github-actions[bot]`: the workflow makes the tag, so the tag says so, while commits and PRs stay the
  owner's. The owner's act is the confirmation at the gate and the dispatch it authorizes, not the tag object.
- A tag pushed with `GITHUB_TOKEN` starts no other workflow, so the existing `release-check` job runs after
  `release-tag` in the same run, with the same three checks as for a tag pushed by hand: annotated (the remote's peeled
  entry) with the cli and meta versions, on `main`, and the pinned `uvx` command prints the version.
- The `push: tags` trigger stays: a tag pushed by hand is still checked.
- The `/release` skill dispatches the workflow and watches its run; a red run stops the release with its URL. A
  platform repo without such a workflow falls back to the printed commands for the owner. The owner confirms version
  and SHA at the gate, merges the version PR and merges the hub pin PR; the agent does the rest.

### Consequences

- Good: no lightweight or hand-typed tag again; the tag message is the reviewed notes, verbatim.
- Good: the session never needs a tag-writing credential; the workflow's `GITHUB_TOKEN` pushes the tag, from the one
  step that holds it.
- Good: the refusal of an existing tag puts "a tag is never moved" in code, not only in the written rule.
- Bad: until a `v*` tag ruleset limits tag creation to the workflow, a session whose git credentials can push could
  still push a tag; only the rule stops it.
- Bad: anyone who can dispatch workflows on the repository can cut a release; the gate is the `/release` flow and the
  checks, not a GitHub environment approval.
- Neutral: by hand stays possible and checked; the GitHub Releases UI stays rejected, as it makes a lightweight tag.
  Pushing the tag from the session was rejected because it needs a write credential in every agent session.

## More Information

- [CONTRIBUTING.md](../CONTRIBUTING.md), "Releases": the flow, step by step.
- `tests/e2e/test_release_dispatch_tag.py` runs the tag step with real git against a local bare remote.
