# 0007. Git and change flow

- Status: accepted
- Date: 2026-09-27
- Deciders: José Henrique Roquette

## Context and Problem Statement

Agents open most branches and PRs; the owner reviews and merges them. The history must say what changed in which
package, so that per-package changelogs and versions can be generated later, and it must never carry AI attribution. How
do changes flow from a branch to `main`, and what format does the history follow?

## Considered Options

- **Conventional Commits on the PR title, squash merge**, protected `main`.
- **Free-form commits**: no format, changelogs written by hand.
- **Merge commits or rebase merge**: keep every branch commit in `main`.
- **Per-commit lint**: every commit on the branch must be a Conventional Commit.

The last three were considered during planning; no alternative was named when the decision was made.

## Decision Outcome

Chosen option: **Conventional Commits on the PR title, squash merge**, because the squash commit takes the PR title, so
linting one line per PR yields a clean, typed history without policing work-in-progress commits.

- CI lints the PR title as `type(scope): subject` with `scripts/check_pr_title.py`: known type and scope, a title of at most
  72 characters, no trailing period, `!` before the colon for a breaking change. The allowed types and scopes are
  in [CONTRIBUTING.md](../CONTRIBUTING.md).
- Squash merge only; the squash commit message is the PR title.
- `main` is protected: changes land only through a PR, the CI `check` job and the PR-title job are required, history is
  linear. No push to `main`, no force-push.
- Per-package changelogs and semantic versions are generated from the history; the tool comes in a follow-up chore.
- Branches: `roquettejh/agh-<n>-<desc>` (the Linear issue id, then a short description); never `claude/…`.
- Authorship: commits and PRs are authored by the owner. No AI co-author trailer, no "Generated with" line, no robot
  emoji, no agent mention in commits, PRs, comments or branch names.

### Consequences

- Good: `main` reads as one typed commit per PR, which a release tool can turn into changelogs and versions.
- Good: branch commits can stay small and messy (WIP commits) without breaking the history.
- Bad: the commits inside a PR are lost from `main`; the PR page keeps them.
- Bad: branch protection and the squash setting live in GitHub settings, outside the repo, so they are a manual step.

## More Information

- [CONTRIBUTING.md](../CONTRIBUTING.md): the task workflow, the title format and the manual repository settings.
