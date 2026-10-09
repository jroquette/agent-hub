"""The JSON files the generator builds from the config (spec D5, Q-9, Q-10, Q-11).

Each builder returns a JSON value; ``render_hub`` writes it in the JSON byte form
(``json_form.dump_json``). A builder reads only the config: the same config builds the same value.
"""

from typing import Final, NamedTuple

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.generator.json_form import JsonValue

# The base plugin's folder, the same in every hub; the project plugin's is `plugin/<project>`.
_BASE_PLUGIN: Final = "hub-workflow"
_PROJECT_MANIFEST_VERSION = "0.1.0"
_PROJECT_MANIFEST_DESCRIPTION = "Project agents, skills and guard extension of this hub."

_SETTINGS_SCHEMA: Final = "https://json.schemastore.org/claude-code-settings.json"
# Spec Q-11: read-only git commands run without a prompt; secret files are never read. AGH-16 D2
# (E14, inventory rows S4a-S4j and S6a) adds the base denies and sandbox. The guard hook is the
# primary check; these rules are defense in depth. A project adds its own lists and hosts through
# `settings.project.json`.
_ALLOWED_COMMANDS: Final = (
    "Bash(git status *)",
    "Bash(git diff *)",
    "Bash(git log *)",
    "Bash(git show *)",
)
# AGH-114: a headless `/onboard propose` (the onboard skill's steps 1 to 4) runs with no one to
# ask, so each read-only command it names gets an exact allow: the right-hand sides of
# `git show origin/<default>:hub.json | sha256sum` (or `| shasum -a 256`; the left one is
# `git show *` above), the `./hub doctor` baseline, and per repo the checkout and default-branch
# reads (`_onboard_repo_reads`). It writes only the proposal and, before replacing an applied one,
# a Write of its dated archive copy beside it (no `mv`); Claude Code checks Write and Edit against
# `Edit(path)` rules only, and `/` anchors at the hub. The guard asks before an edit of the `hub`
# or `agent` launcher. `apply` stays interactive: nothing it writes, pushes or runs is allowed here.
_ONBOARD_PROPOSE_COMMANDS: Final = ("Bash(sha256sum)", "Bash(shasum -a 256)", "Bash(./hub doctor)")
_ONBOARD_PROPOSAL_EDIT: Final = "Edit(/brain/_inbox/onboard-proposal*.md)"
_DENIED_READS: Final = ("Read(**/*.pem)", "Read(**/*.key)")
_DENIED_FORCE_PUSHES: Final = ("Bash(git push --force*)", "Bash(git push -f *)")
# Claude Code matches each subcommand of `|`, `&&`, `;` on its own, so a shell fed by a pipe is
# denied as the bare `sh` or `bash` subcommand (`Bash(* | sh)` would never match).
_DENIED_COMMANDS: Final = (
    "Bash(terraform *)",
    "Bash(aws *)",
    "Bash(security *)",
    "Bash(ssh *)",
    "Bash(sh)",
    "Bash(bash)",
)
# The guard's own protected branches besides the config's default branches (`hubhooks.py`).
_ALWAYS_PROTECTED: Final = ("main", "master")
# Commands that reach the network or the host's credentials run outside the sandbox; the hosts are
# the package registries and GitHub, the same in every hub.
_SANDBOX_EXCLUDED: Final = (
    "docker *",
    "gh *",
    "git push *",
    "git fetch *",
    "git pull *",
    "git clone *",
    "git ls-remote *",
)
_SANDBOX_HOSTS: Final = (
    "localhost",
    "127.0.0.1",
    "[::1]",
    "pypi.org",
    "files.pythonhosted.org",
    "registry.npmjs.org",
    "*.npmjs.org",
    "github.com",
    "*.github.com",
    "*.githubusercontent.com",
)
# The base plugin's hooks, from the hub root: cloud sessions do not install repo plugins, so the
# managed settings wire the hooks themselves (docs/design/hub-generator.md § Hooks and plugin
# wiring).
_HOOKS_FOLDER: Final = "$CLAUDE_PROJECT_DIR/plugin/hub-workflow/hooks"


class HookEvent(NamedTuple):
    """One hook the managed settings wire: the event, its matcher (``None``: every tool or
    source), the base plugin hook file it runs and its timeout in seconds.
    """

    event: str
    matcher: str | None
    file: str
    timeout: int


# Spec AC-4.7 (Q-5): the base plugin's six hooks, with this hub's timeouts; `hooks.json` wires the
# same six for a plugin install.
HOOK_EVENTS: Final = (
    HookEvent("SessionStart", "startup|resume|clear|compact", "session_start.py", 20),
    HookEvent(
        "PreToolUse",
        "Bash|Read|Grep|Glob|Edit|Write|MultiEdit|NotebookEdit|WebFetch",
        "guard.py",
        10,
    ),
    HookEvent("PostToolUse", "Edit|Write|MultiEdit", "post_edit.py", 60),
    HookEvent("Stop", None, "stop_gate.py", 180),
    HookEvent("PreCompact", None, "pre_compact.py", 20),
    HookEvent("SessionEnd", None, "session_end.py", 10),
)


def managed_settings(config: HubConfig) -> JsonValue:
    """The managed ``.claude/settings.json``: the rules base every hub shares (spec D5).

    The schema, the authorship rule (empty attribution, no co-author line), the hooks block, the
    read-only git allows and those a headless ``/onboard propose`` needs (AGH-114), the base
    denies (secret reads, force pushes and pushes to a protected branch, infra tools, ``ssh``, a
    bare ``sh`` or ``bash``), the repos as additional directories (``../<dir>``, in ``hub.json``
    order) and the base sandbox (AGH-16 D2, E14). Project settings
    (marketplace, plugins, extra sandbox hosts, ``env``, skill overrides) come from the seeded
    ``settings.project.json``, which may also override the sandbox's scalars.
    """
    return {
        "$schema": _SETTINGS_SCHEMA,
        "attribution": {"commit": "", "pr": ""},
        "includeCoAuthoredBy": False,
        "hooks": base_hooks_block(),
        "permissions": {
            "allow": [
                *_ALLOWED_COMMANDS,
                *_ONBOARD_PROPOSE_COMMANDS,
                *_onboard_repo_reads(config),
                _ONBOARD_PROPOSAL_EDIT,
            ],
            "deny": [
                *_DENIED_READS,
                *_DENIED_FORCE_PUSHES,
                *_denied_pushes(config),
                *_DENIED_COMMANDS,
            ],
            "additionalDirectories": [f"../{repo.dir}" for repo in config.repos],
        },
        "sandbox": {
            "enabled": True,
            "allowUnsandboxedCommands": False,
            "excludedCommands": list(_SANDBOX_EXCLUDED),
            "network": {"allowLocalBinding": True, "allowedDomains": list(_SANDBOX_HOSTS)},
        },
    }


def _onboard_repo_reads(config: HubConfig) -> list[str]:
    """Two exact allows per repo, in ``hub.json`` order: the onboard skill's checkout test and its
    default-branch read, each with the repo's own ``git -C ../<dir>`` (no wildcard to widen)."""
    return [
        rule
        for repo in config.repos
        for rule in (
            f"Bash(git -C ../{repo.dir} rev-parse --show-toplevel)",
            f"Bash(git -C ../{repo.dir} symbolic-ref refs/remotes/origin/HEAD)",
        )
    ]


def _denied_pushes(config: HubConfig) -> list[str]:
    """Two push denies per branch the guard protects (``main``, ``master``, the project's and each
    repo's default branch), sorted, each once."""
    branches = sorted(
        {
            *_ALWAYS_PROTECTED,
            config.project.default_branch,
            *(config.default_branch_for(repo.dir) for repo in config.repos),
        }
    )
    return [
        rule
        for branch in branches
        for rule in (f"Bash(git push * {branch})", f"Bash(git push origin HEAD:{branch}*)")
    ]


def base_hooks_block() -> dict[str, JsonValue]:
    """The ``hooks`` value of the managed settings: one group per event, in ``HOOK_EVENTS`` order.

    hub doctor's ``settings.weakening`` rule checks ``settings.json`` against it without a render
    (spec Q-14). Each call builds a new value.
    """
    return {hook.event: [_hook_group(hook)] for hook in HOOK_EVENTS}


def _hook_group(hook: HookEvent) -> JsonValue:
    command: JsonValue = {
        "type": "command",
        "command": f'python3 "{_HOOKS_FOLDER}/{hook.file}"',
        "timeout": hook.timeout,
    }
    if hook.matcher is None:
        return {"hooks": [command]}
    return {"matcher": hook.matcher, "hooks": [command]}


def project_settings(config: HubConfig) -> JsonValue:
    """The seeded ``.claude/settings.project.json``: empty; the project adds its own settings."""
    return {}


def project_manifest(config: HubConfig) -> JsonValue:
    """The seeded project plugin manifest: the project's name, a first version, a description."""
    return {
        "name": config.project.name,
        "version": _PROJECT_MANIFEST_VERSION,
        "description": _PROJECT_MANIFEST_DESCRIPTION,
    }


def marketplace(config: HubConfig) -> JsonValue:
    """The managed ``.claude-plugin/marketplace.json`` of module ``marketplace`` (AGH-17 D4).

    Named after the project and owned by its author, or by the project on a hub that leaves the
    author to each developer (no email then: AGH-65); it lists the base plugin, then the project's
    own. Third-party pins go in the seeded ``marketplace.project.json``, merged after them.
    """
    project = config.project
    owner: dict[str, JsonValue] = {"name": project.author_name or project.name}
    if project.author_email is not None:
        owner["email"] = project.author_email
    return {
        "name": project.name,
        "owner": owner,
        "plugins": [
            {"name": _BASE_PLUGIN, "source": f"./plugin/{_BASE_PLUGIN}"},
            {"name": project.name, "source": f"./plugin/{project.name}"},
        ],
    }


def marketplace_project(config: HubConfig) -> JsonValue:
    """The seeded ``.claude-plugin/marketplace.project.json``: empty; the project adds its pins."""
    return {}
