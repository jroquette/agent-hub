"""``repos.ui_paths``: each ``repos[].ui_paths`` glob matches a file of its checkout (AGH-474).

The UX lens runs when a review round's diff touches a repo's ``ui_paths`` (two-level flows
D-12), so a glob that matches nothing (a typo, a moved folder) silently turns the lens off.

- Only the checkout's listing is read, as for the other repo rules: with a ``.git`` it is git's,
  so a gitignored file does not count. A glob is matched as ``ui_paths.ui_path_pattern`` reads
  it, against the whole path from the checkout root; a folder alone is never a match.
- One warning per glob that matches no listed path, at ``hub.json``, in ``hub.json`` order. The
  glob is echoed cut (it may hold 200 characters).
- A repo without the key, a missing or unlistable checkout (the runner's to report) and a
  failed config give nothing. The shape of each glob is ``config.schema``'s.
"""

from collections.abc import Iterator
from typing import Final

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import ConfigFailure, DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import REPOS_UI_PATHS_RULE, RULE_MODULES, Severity
from agent_hub.core.hub_config.ui_paths import ui_path_pattern
from agent_hub.core.hub_config.versions import cut_echo

CONFIG_PATH: Final = "hub.json"
MESSAGE: Final = "repos[{index}].ui_paths[{glob_index}]: {glob} matches no file in ../{dir}"
FIX: Final = (
    "fix the glob or remove it; ui_paths globs match paths from the repo root"
    " (docs/design/project-config.md)"
)


def _repo_ui_paths(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    if isinstance(snapshot.config, ConfigFailure):
        return
    checkouts = {checkout.dir: checkout.files for checkout in snapshot.repos}
    for index, repo in enumerate(snapshot.config.repos):
        files = checkouts.get(repo.dir)
        if repo.ui_paths is None or files is None or files.problem is not None:
            continue
        for glob_index, ui_path in enumerate(repo.ui_paths):
            pattern = ui_path_pattern(ui_path)
            if any(pattern.fullmatch(path) for path in files.listed):
                continue
            message = MESSAGE.format(
                index=index, glob_index=glob_index, glob=cut_echo(ui_path), dir=repo.dir
            )
            yield REPOS_UI_PATHS.finding(path=CONFIG_PATH, message=message, fix=FIX)


REPOS_UI_PATHS: Final = Rule(
    id=REPOS_UI_PATHS_RULE,
    severity=Severity.WARNING,
    summary="each repos[].ui_paths glob matches a file of the repo's checkout",
    module=RULE_MODULES.get(REPOS_UI_PATHS_RULE),
    reads=frozenset({Read.REPOS}),
    check=_repo_ui_paths,
)
