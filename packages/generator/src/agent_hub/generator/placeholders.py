"""The values ``@@`` templates substitute, built from a validated ``HubConfig`` (AC-3.9).

Keys are the Rendered values of docs/design/project-config.md, whose patterns make them safe
unquoted in shell, Make and Markdown text; in YAML a template double-quotes them, because a valid
value such as ``on``, ``NO`` or ``1.0`` would otherwise parse as another type. Plus the platform
repository and the Makefile's module include lines. ``project.author_name``,
``repos[].check_fast``, ``repos[].check`` and ``platform.version`` are never keys: shims read
them at run time, and the author name needs format quoting.
"""

from typing import Final

from agent_hub.core.hub_config.model import HubConfig

# The platform's git source, unpinned: shims append ``@v<platform.version>`` read from hub.json
# at run time, then ``#subdirectory=packages/agent-hub`` (ADR 0013). A test ties it to core's
# ``PINNED_RELEASE_COMMAND``.
PLATFORM_REPOSITORY: Final = "git+https://github.com/jroquette/agent-hub"
_LIST_SEPARATOR = ", "


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
    }


def _module_includes(config: HubConfig) -> str:
    """One ``include mk/<id>.mk`` line per selected module, sorted; empty with no module.

    Dumped by alias, so the ids are the closed JSON ids (``contract-sync``), never free text.
    """
    selected = sorted(config.modules.model_dump(exclude_none=True))
    return "".join(f"include mk/{module_id}.mk\n" for module_id in selected)
