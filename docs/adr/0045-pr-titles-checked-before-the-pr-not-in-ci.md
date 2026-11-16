# 0045. PR titles are checked before the PR is opened, not in CI

- Status: proposed
- Date: 2026-10-21
- Deciders: José Henrique Roquette (asked for it in AGH-409 on 2026-10-21)
- Supersedes, once accepted: [ADR 0007](0007-git-and-change-flow.md), only its CI lint of the PR title and the
  required PR-title job; the title format, squash merge and the rest of ADR 0007 are kept. ADR 0007 is not edited;
  only its status line changes when this ADR is accepted.

## Context and Problem Statement

[ADR 0007](0007-git-and-change-flow.md) has CI lint the PR title (`.github/workflows/pr-title.yml`, running
`scripts/check_pr_title.py`) and makes that job a required status check. Agents open most PRs: they write the title,
and a title CI rejects costs a red check, a rename and another run, while a title the owner dislikes is fixed in one
edit before the squash merge, since the owner merges every PR and reads the title then. AGH-409 trims CI to the checks
that guard the code, and makes the PR's gate one required job (`check`). Where should the title check live?

## Considered Options

- **Keep the CI job** (ADR 0007): a required `pr-title` status, rerun on every title edit.
- **Check before the PR**: `make pr-title TITLE="<title>"` (the same script) is part of the agent's steps before
  `gh pr create` and after a rename; CI does not check titles.
- **Fold the title into the `check` job**: the code gate would rerun, or fail, on a title edit.

## Decision Outcome

Chosen option: **Check before the PR**, because the one who writes the title can check it at no cost, and the owner,
who squash-merges, is the last check on the line that lands on `main`.

- `scripts/check_pr_title.py` and its lists stay as they are; `make pr-title TITLE="<title>"` runs it.
- `.github/workflows/pr-title.yml` is removed; the required status checks are the CI `check` job only.
- `AGENTS.md` and `docs/CONTRIBUTING.md` say to run `make pr-title` before opening a PR and after renaming it.

### Consequences

- Good: CI holds only the checks on the code; a title edit reruns nothing.
- Good: one required status (`check`), which already requires every other gate job.
- Bad: a title that skips the step reaches the owner unchecked; the squash merge is where it is caught.
- Bad: the branch protection change (drop `pr-title` from the required checks) is a manual step in GitHub settings.

## More Information

- [CONTRIBUTING.md](../CONTRIBUTING.md): the title format and the manual repository settings.
- [TESTING.md](../TESTING.md) "Gates": the CI jobs and the required `check` job.
