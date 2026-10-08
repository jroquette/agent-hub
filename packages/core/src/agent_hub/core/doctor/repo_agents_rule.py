"""``repos.agents``: each checked-out repo has an ``AGENTS.md`` at its root (AGH-76).

``hub agent`` attaches every repo, and each one's root ``AGENTS.md`` is what its sessions load
for it, so a repo without one gets no instructions of its own.

- Only the checkout's listing is read (D2): the exact root path ``AGENTS.md``, a file or a link
  (not followed), empty or not. ``CLAUDE.md``, a nested or a differently cased name does not
  count. The content, size and references are never checked.
- As the repo rules list it (E5): with a ``.git`` the listing is git's, so a gitignored file, or
  a tracked one deleted from the work tree, is not listed and warns; a listed file that could
  not be read is still listed and passes.
- A missing checkout is skipped, and so is one that could not be listed: the runner reports
  each once, on the first selected repo rule by id (Q-9, E3).

The fix names the hub's seeded starter and the repo's ``check_fast`` and ``check`` from
``hub.json``, each escaped onto one line and then cut (E6): a valid command may hold U+2028 or
U+0085, which would split the report line.
"""

from collections.abc import Iterator
from typing import Final

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import ConfigFailure, DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import REPOS_AGENTS_RULE, RULE_MODULES, Severity
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.hub_config.versions import cut_echo

AGENTS_FILE: Final = "AGENTS.md"
STARTER_PATH: Final = "docs/app-repo-AGENTS.md"
MESSAGE: Final = "no AGENTS.md at the repo root (hub agent loads none for it)"
FIX: Final = (
    "copy {starter} to ../{dir}/AGENTS.md and fill it in; check_fast: {fast}, check: {full}"
)


def _repo_agents(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    if isinstance(snapshot.config, ConfigFailure):
        return
    repos = {repo.dir: repo for repo in snapshot.config.repos}
    for checkout in snapshot.repos:
        files = checkout.files
        # A missing or unlistable checkout is the runner's to report (Q-9, E36).
        if files is None or files.problem is not None or AGENTS_FILE in files.listed:
            continue
        repo = repos[checkout.dir]
        yield REPOS_AGENTS.finding(
            path=f"../{checkout.dir}",
            message=MESSAGE,
            fix=FIX.format(
                starter=STARTER_PATH,
                dir=checkout.dir,
                fast=_shown(repo.check_fast),
                full=_shown(repo.check),
            ),
        )


def _shown(command: str) -> str:
    """A command from ``hub.json`` as the fix shows it: escaped first, then cut (E6)."""
    return cut_echo(one_line(command))


REPOS_AGENTS: Final = Rule(
    id=REPOS_AGENTS_RULE,
    severity=Severity.WARNING,
    summary="each checked-out repo has an AGENTS.md at its root",
    module=RULE_MODULES.get(REPOS_AGENTS_RULE),
    reads=frozenset({Read.REPOS}),
    check=_repo_agents,
)
