"""The values ``@@`` templates substitute, built from a validated ``HubConfig`` (AC-3.9).

Keys are the Rendered values of docs/design/project-config.md, whose patterns make them safe
unquoted in shell, Make and Markdown text; in YAML a template double-quotes them, because a valid
value such as ``on``, ``NO`` or ``1.0`` would otherwise parse as another type (brain frontmatter
lists repo dirs unquoted; its readers load it without type resolution). Plus the platform
repository, the Makefile's module include lines, the module files ``AGENTS.md`` names and the
``contract-sync`` source and target repo dirs (empty while the module is unselected), so its
script never reads ``hub.json``.
``project.author_name``, ``repos[].check_fast``, ``repos[].check`` and ``platform.version`` are
never keys: shims read them at run time, and the author name needs format quoting.
"""

import textwrap
from typing import Final

from agent_hub.core.doctor.snapshot import module_makefiles
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.rendered_file import Ownership
from agent_hub.generator.registry import REGISTRY

# The platform's git source, unpinned: shims append ``@v<platform.version>`` read from hub.json
# at run time, then ``#subdirectory=packages/agent-hub`` (ADR 0013). A test ties it to core's
# ``PINNED_RELEASE_COMMAND``.
PLATFORM_REPOSITORY: Final = "git+https://github.com/jroquette/agent-hub"
_LIST_SEPARATOR = ", "
# ``AGENTS.md`` names every module makefile by this one pattern (AGH-17 D5).
MODULE_MAKEFILE_PATTERN: Final = "mk/<id>.mk"
_MARKDOWN_WIDTH: Final = 120
_MARKDOWN_INDENT: Final = "  "


def substitution_mapping(config: HubConfig) -> dict[str, str]:
    """Map each placeholder name to its text; lists keep ``hub.json`` order, joined by ``, ``."""
    project = config.project
    return {
        "project_name": project.name,
        "project_hub_repo": project.hub_repo,
        "project_branch_prefix": project.branch_prefix,
        "project_default_branch": project.default_branch,
        "project_author_email": project.author_email,
        "tracker_team": config.tracker.team,
        "repo_dirs": _LIST_SEPARATOR.join(repo.dir for repo in config.repos),
        "repo_githubs": _LIST_SEPARATOR.join(repo.github for repo in config.repos),
        "guard_deny_hosts": _LIST_SEPARATOR.join(config.guard.deny_hosts),
        "platform_repository": PLATFORM_REPOSITORY,
        "module_includes": _module_includes(config),
        **_module_files(config),
        **_contract_sync_repos(config),
    }


def _contract_sync_repos(config: HubConfig) -> dict[str, str]:
    """The validated ``contract-sync`` repo dirs, rendered into its script; empty when unselected.

    ``HubConfig`` checked both against ``repos[].dir`` (a safe segment), so the script uses them
    as written instead of reading ``hub.json``, which the stdlib readers do not validate.
    """
    settings = config.modules.contract_sync
    if settings is None:
        return {"contract_sync_source": "", "contract_sync_target": ""}
    return {"contract_sync_source": settings.source, "contract_sync_target": settings.target}


def _module_includes(config: HubConfig) -> str:
    """One ``include mk/<id>.mk`` line per selected module, sorted; empty with no module.

    The paths are the ones ``hub doctor`` reads as managed makefiles, so the two cannot drift;
    the ids are the closed JSON ids (``contract-sync``), never free text.
    """
    return "".join(f"include {path}\n" for path in module_makefiles(config))


def _module_files(config: HubConfig) -> dict[str, str]:
    """The selected modules' files, as clauses of ``AGENTS.md``'s managed and seeded lists.

    Empty with no module, so a hub names only files it holds (``instructions.refs`` would report
    an unselected module's path as stale). The makefiles are named by ``mk/<id>.mk``.
    """
    selected = config.modules.model_dump(exclude_none=True).keys()
    entries = [entry for entry in REGISTRY if entry.module in selected]
    if not entries:
        return {"module_files": "", "module_seeded_files": ""}
    managed = [
        entry.path
        for entry in entries
        if entry.ownership is Ownership.MANAGED and not entry.path.startswith("mk/")
    ]
    clause = textwrap.fill(
        "and each selected module's files ("
        + _LIST_SEPARATOR.join(f"`{path}`" for path in (MODULE_MAKEFILE_PATTERN, *managed))
        + ")",
        width=_MARKDOWN_WIDTH,
        initial_indent=_MARKDOWN_INDENT,
        subsequent_indent=_MARKDOWN_INDENT,
        break_long_words=False,
        break_on_hyphens=False,
    )
    seeded = [entry.path for entry in entries if entry.ownership is Ownership.SEEDED]
    return {
        "module_files": f",\n{clause}",
        "module_seeded_files": "".join(f",\n{_MARKDOWN_INDENT}`{path}`" for path in seeded),
    }
