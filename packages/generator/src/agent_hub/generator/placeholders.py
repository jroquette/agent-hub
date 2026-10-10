"""The values ``@@`` templates substitute, built from a validated ``HubConfig`` (AC-3.9).

Keys are the Rendered values of docs/design/project-config.md, whose patterns make them safe
unquoted in shell, Make and Markdown text; in YAML a template double-quotes them, because a valid
value such as ``on``, ``NO`` or ``1.0`` would otherwise parse as another type (brain frontmatter
lists repo dirs unquoted; its readers load it without type resolution). Plus the platform's default
repository and core's pattern and form for ``platform.repository``, the Makefile's module include
lines, the module files ``AGENTS.md`` names and the ``contract-sync`` source and target repo dirs
(empty while the module is unselected), so its script never reads ``hub.json``, and ``AGENTS.md``'s
worktree base and protected branches. ``project.author_name``, ``repos[].check_fast``,
``repos[].check``, ``platform.version`` and ``platform.repository`` are never keys: shims read them
at run time, and the author name needs format quoting. A hub that
leaves the identity to each developer (no ``project.branch_prefix``, or no author) renders
``<prefix>`` and ``AGENTS.md``'s rule names the developer's sources instead (AGH-65); a hub that
sets them keeps the bytes it had. A hub with several tracker teams names them all where
``AGENTS.md`` and the plugin name the team; a one-team hub keeps its bytes (AGH-56). A hub that
sets ``project.conventions`` or a ``repos[].conventions`` shows its branch shape in rule 1 and
kickoff and gets a Conventions block in ``AGENTS.md``; an unconfigured hub keeps its bytes
(AGH-57).
"""

import re
import textwrap
from typing import Final

from agent_hub.core.doctor.snapshot import module_makefiles
from agent_hub.core.hub_config.model import PREFIX_PLACEHOLDER, HubConfig
from agent_hub.core.hub_config.platform_repository import (
    DEFAULT_PLATFORM_REPOSITORY,
    PLATFORM_REPOSITORY_FORM,
    PLATFORM_REPOSITORY_PATTERN,
)
from agent_hub.core.hub_config.workspace_repos import workspace_repos
from agent_hub.core.hub_files.rendered_file import Ownership
from agent_hub.core.workspace.shown_conventions import (
    ShownConventions,
    shown_conventions,
    shown_prefix,
)
from agent_hub.generator.registry import REGISTRY

# The platform's default git source, unpinned: shims append ``@v<platform.version>`` read from
# hub.json at run time, then ``#subdirectory=packages/agent-hub`` (ADR 0013). Core holds it; the
# runtime readers take ``platform.repository`` from hub.json instead when it is set, so it is never
# rendered (AGH-49).
PLATFORM_REPOSITORY: Final = DEFAULT_PLATFORM_REPOSITORY
_LIST_SEPARATOR = ", "
# ``AGENTS.md`` names every module makefile by this one pattern (AGH-17 D5).
MODULE_MAKEFILE_PATTERN: Final = "mk/<id>.mk"
_MARKDOWN_WIDTH: Final = 120
_MARKDOWN_INDENT: Final = "  "
# ``AGENTS.md``'s worktree base once a repo sets its own branch; each repo's follows (AGH-46).
_PER_REPO_BASE: Final = "`origin/<the repo's default branch>`"
# ``AGENTS.md`` rule 1's author: hub.json's, or each developer's (AGH-65). Line breaks keep the
# rendered lines within 120 characters.
_USER_AUTHOR: Final = "the user (`hub.json` → `project.author_name`, `project.author_email`)"
_DEVELOPER_AUTHOR: Final = (
    "the developer running the session (`hub.local.json` → `project.author_name`,\n"
    "   `project.author_email`, else their `git config user.name`, `user.email`)"
)
# The address kickoff checks the session's git email against: hub.json's, or the developer's own
# (AGH-65). The line break keeps the rendered kickoff step within 120 characters.
_USER_EMAIL: Final = "`hub.json` → `project.author_email`"
_DEVELOPER_EMAIL: Final = (
    "your author email (`hub.local.json` →\n"
    "   `project.author_email`, else your own address, not an agent's or the container's)"
)
# Appended to rule 1's branch line when each developer has their own prefix. It starts on its
# own line, so a long tracker team key cannot push the branch line past 120 characters.
_PREFIX_NOTE: Final = (
    f"\n   `{PREFIX_PLACEHOLDER}` is `hub.local.json` → `project.branch_prefix`, else the local"
    " part of your author email plus `/`."
)

# The template text right after each ``AGENTS.md`` team mention, so a wrapped list of several
# teams keeps its last line within 120 characters (AGH-56).
_MENTION_SUFFIX: Final = "). Update it when starting, finishing"
_RULE_SUFFIX: Final = " in lowercase."
_RULE_INDENT: Final = "   "
# The template text of rule 1's line before its branch rule, so a long configured branch shape
# wraps within 120 characters (AGH-57).
_BRANCH_RULE_LEAD: Final = "   after an agent (e.g. `claude/…`). "
# The conventions' block in ``AGENTS.md``: its lead paragraph and each key as a repo line names
# it; the shapes and examples come from ``shown_conventions`` (AGH-57, plan § Design 7, E32).
_CONVENTIONS_LEAD: Final = (
    "`hub.json` → `project.conventions`, overridden per repo by `repos[].conventions`;"
    " `hub worktree`, `hub run` and its\n"
    "session follow them. `{ISSUE}` is the issue id, `{issue_lower}` the same in lowercase,"
    " `{slug}` the worktree's `<desc>`."
)
# The Conventions block's names line: the repos it names, then what holds their keys (AGH-98).
_MAX_NAMED_REPOS: Final = 3
_OVERRIDE_TAIL: Final = (
    " some keys: `hub.json` → `repos[].conventions`; `hub worktree` and `hub run` apply them;"
    " a `pr_title` neither layer sets follows the repo's own `commit_title`."
)
# A code span, and the character that stands for each space inside one while wrapping (no
# pattern may hold a backtick or a control character, so spans pair up and the glue is free).
_CODE_SPAN: Final = re.compile(r"`[^`]*`")
_GLUE: Final = "\x00"
# The plugin texts' team parenthetical when a hub lists several tracker teams (AGH-56).
_SEVERAL_TEAMS_KEY: Final = (
    "the issue's team: a key of `tracker.teams` in `hub.json`, the first being the default"
)


def substitution_mapping(config: HubConfig) -> dict[str, str]:
    """Map each placeholder name to its text; lists keep ``hub.json`` order, joined by ``, ``."""
    project = config.project
    repos = workspace_repos(config)
    return {
        "project_name": project.name,
        "project_hub_repo": project.hub_repo,
        "project_branch_prefix": shown_prefix(config),
        "project_default_branch": project.default_branch,
        "tracker_team": config.tracker.default_team,
        "repo_dirs": _LIST_SEPARATOR.join(repo.dir for repo in repos),
        "repo_githubs": _LIST_SEPARATOR.join(repo.github for repo in repos),
        "guard_deny_hosts": _LIST_SEPARATOR.join(config.guard.deny_hosts),
        "platform_repository": PLATFORM_REPOSITORY,
        "platform_repository_pattern": PLATFORM_REPOSITORY_PATTERN,
        "platform_repository_form": PLATFORM_REPOSITORY_FORM,
        "module_includes": _module_includes(config),
        **_module_files(config),
        **_contract_sync_repos(config),
        **_branch_mentions(config),
        **_team_mentions(config),
        **_conventions_texts(config),
        "commit_author": (
            _USER_AUTHOR
            if project.author_name is not None and project.author_email is not None
            else _DEVELOPER_AUTHOR
        ),
        "prefix_note": "" if project.branch_prefix is not None else _PREFIX_NOTE,
        "identity_email": _USER_EMAIL if project.author_email is not None else _DEVELOPER_EMAIL,
    }


def _branch_mentions(config: HubConfig) -> dict[str, str]:
    """``AGENTS.md``'s worktree base and the branches its push rule names, as code spans.

    With no ``repos[].default_branch`` set, the project branch alone, so the file keeps the bytes
    it had before the key. Otherwise each repo's effective branch in ``hub.json`` order, and the
    guard's protected set (``main``, ``master``, the project's and each repo's), sorted, each once.
    """
    # The project branch: the whole mention without a repo key, and a protected branch.
    project_branch = config.project.default_branch
    if all(repo.default_branch is None for repo in config.repos):
        return {
            "worktree_base": f"`origin/{project_branch}`",
            "protected_branches": f"`{project_branch}`",
        }
    repo_branches = {repo.dir: config.default_branch_for(repo.dir) for repo in config.repos}
    per_repo = _LIST_SEPARATOR.join(f"{name}: `{branch}`" for name, branch in repo_branches.items())
    spans = [
        f"`{branch}`"
        for branch in sorted({"main", "master", project_branch, *repo_branches.values()})
    ]
    return {
        "worktree_base": f"{_PER_REPO_BASE} ({per_repo})",
        "protected_branches": f"{_LIST_SEPARATOR.join(spans[:-1])} or {spans[-1]}",
    }


def _team_mentions(config: HubConfig) -> dict[str, str]:
    """The tracker team as ``AGENTS.md`` and the plugin texts name it.

    One team: the template text it replaced, so the file keeps its bytes. Several: every key in
    ``hub.json`` order with the default first named; each ``AGENTS.md`` value starts on its own
    line and wraps, so the line before it only gets shorter and, for keys short enough to fit on a
    line, none passes 120 characters. The plugin texts' parenthetical has one value per site, as
    each site words the one key; several keys read the same everywhere.
    """
    keys = config.tracker.team_keys
    if len(keys) == 1:
        return {
            "tracker_team_mention": f" team {keys[0]}",
            "tracker_team_rule": f" the\n{_RULE_INDENT}tracker team {keys[0]}",
            "tracker_team_key": "`tracker.team` in `hub.json`",
            "tracker_team_key_named": "team `tracker.team` in `hub.json`",
            "tracker_team_key_assigned": "team = `tracker.team` in `hub.json`",
        }
    listed = _LIST_SEPARATOR.join(keys)
    return {
        "tracker_team_mention": _wrapped_line(
            f"team {listed} (default {keys[0]})", suffix=_MENTION_SUFFIX
        ),
        "tracker_team_rule": _wrapped_line(
            f"one of the tracker teams {listed}", suffix=_RULE_SUFFIX
        ),
        "tracker_team_key": _SEVERAL_TEAMS_KEY,
        "tracker_team_key_named": _SEVERAL_TEAMS_KEY,
        "tracker_team_key_assigned": _SEVERAL_TEAMS_KEY,
    }


def _conventions_texts(config: HubConfig) -> dict[str, str]:
    """Rule 1's branch, kickoff's branch and ``AGENTS.md``'s Conventions block.

    Unconfigured (no ``conventions`` key at any level): the template text they replaced and no
    block, so the files keep their bytes. Configured: the project's effective branch shape, with
    ``{prefix}`` shown as the rendered prefix and the other placeholders as written, and a block
    with each project shape and one example, then one line naming up to three repos that override
    any, how many more do, and where their keys are.
    """
    shown = shown_conventions(config)
    if shown is None:
        default_shape = f"`{shown_prefix(config)}<team>-<n>-<desc>`"
        team_rule = _team_mentions(config)["tracker_team_rule"]
        return {
            "branch_rule": (f"Branch: {default_shape}, where `<team>` is{team_rule}{_RULE_SUFFIX}"),
            "kickoff_branch": default_shape,
            "conventions_section": "",
        }
    shape = f"`{shown.branch.shape}`"
    own_branch = any("branch" in repo.overrides for repo in shown.repos.values())
    return {
        "branch_rule": _filled_after(
            f"Branch: {shape}"
            + (", or the repo's own (see Conventions above)." if own_branch else "."),
            lead=_BRANCH_RULE_LEAD,
        ),
        "kickoff_branch": shape
        + (" (or the repo's own, `hub.json` → `repos[].conventions`)" if own_branch else ""),
        "conventions_section": _conventions_section(shown),
    }


def _conventions_section(shown: ShownConventions) -> str:
    """The Conventions block, from the blank lines before its heading to its last line.

    Its size does not depend on the repo count, and a line passes 120 characters only as one code
    span with its glued label or ``e.g.`` and punctuation (plan P-1, AGH-98).
    """
    shapes = (
        ("Branch", shown.branch),
        ("Commit title", shown.commit_title),
        ("PR title", shown.pr_title),
    )
    # AGH-98: the label stays on its shape's line and `e.g.` on its example's (glued spaces), so
    # each item takes two lines even at the longest pattern.
    items = [
        f"-{_GLUE}{label.replace(' ', _GLUE)}:{_GLUE}`{pattern.shape}`,"
        f" e.g.{_GLUE}`{pattern.example}`."
        for label, pattern in shapes
    ]
    # AGH-98: one line names the overriding repos (at most three, then how many more); their
    # patterns stay in hub.json, so the block keeps its size however many repos override.
    overriding = [f"`{repo_dir}`" for repo_dir, repo in shown.repos.items() if repo.overrides]
    if overriding:
        named = _LIST_SEPARATOR.join(overriding[:_MAX_NAMED_REPOS])
        rest = len(overriding) - _MAX_NAMED_REPOS
        if rest > 0:
            subject = f"{named} and {rest} more repo{'s' if rest > 1 else ''} override"
        else:
            subject = f"{named} {'overrides' if len(overriding) == 1 else 'override'}"
        # The article stays with its code span, so no line ends in a lone "a".
        items.append(f"- {subject}{_OVERRIDE_TAIL}".replace("; a `", f"; a{_GLUE}`"))
    bullets = "\n".join(_filled_after(item, lead="") for item in items)
    return f"\n\n## Conventions\n\n{_CONVENTIONS_LEAD}\n\n{bullets}"


def _filled_after(text: str, *, lead: str) -> str:
    """``text`` wrapped at 120 characters when it follows ``lead`` on its first line.

    Later lines are indented to sit under the list item. A code span is never broken: lines break
    only at spaces outside code spans, so each span keeps its text byte for byte (a run of spaces
    included), and a later line starts with a code span or with the fixed prose around them, none
    of whose words opens a Markdown block. A line whose code span is longer than the width goes
    past 120 characters (plan P-1).
    """
    indent = _RULE_INDENT if lead else _MARKDOWN_INDENT
    glued = _CODE_SPAN.sub(lambda span: span.group().replace(" ", _GLUE), text)
    lines = textwrap.wrap(
        glued,
        width=_MARKDOWN_WIDTH,
        initial_indent=lead,
        subsequent_indent=indent,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return "\n".join([lines[0][len(lead) :], *lines[1:]]).replace(_GLUE, " ")


def _wrapped_line(text: str, *, suffix: str) -> str:
    """``text`` on new lines indented under a rule item, leaving room for ``suffix`` after it."""
    return "\n" + textwrap.fill(
        text,
        width=_MARKDOWN_WIDTH - len(suffix),
        initial_indent=_RULE_INDENT,
        subsequent_indent=_RULE_INDENT,
        break_long_words=False,
        break_on_hyphens=False,
    )


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
