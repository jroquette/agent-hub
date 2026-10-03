import copy
import json

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.built_json import (
    HOOK_EVENTS,
    base_hooks_block,
    managed_settings,
    marketplace,
    marketplace_project,
    project_manifest,
    project_settings,
)
from agent_hub.generator.json_merge import MergeError, merge_json


def a_config_named(name: str) -> HubConfig:
    document = a_hub_document()
    document["project"]["name"] = name
    return HubConfig.model_validate(document)


@pytest.mark.parametrize("project_name", ["demo", "acme-tools"])
def test_returns_empty_object_when_project_settings_built(project_name: str) -> None:
    # Spec D2/D5: the project's own settings start empty; AGH-14 merges them into settings.json.
    assert project_settings(a_config_named(project_name)) == {}


@pytest.mark.parametrize("project_name", ["demo", "acme-tools"])
def test_names_project_when_project_manifest_built(project_name: str) -> None:
    # Spec Q-10: the project's name, a first version and a generic description; nothing else.
    assert project_manifest(a_config_named(project_name)) == {
        "name": project_name,
        "version": "0.1.0",
        "description": "Project agents, skills and guard extension of this hub.",
    }


@pytest.mark.parametrize("project_name", ["demo", "acme-tools"])
def test_builds_marketplace_from_project_when_rendered(project_name: str) -> None:
    # AGH-17 D4: the name and owner from `project.*`; the base plugin, then the project's own.
    config = a_config_named(project_name)

    assert marketplace(config) == {
        "name": project_name,
        "owner": {"name": config.project.author_name, "email": config.project.author_email},
        "plugins": [
            {"name": "hub-workflow", "source": "./plugin/hub-workflow"},
            {"name": project_name, "source": f"./plugin/{project_name}"},
        ],
    }


@pytest.mark.parametrize("project_name", ["demo", "acme-tools"])
def test_seeds_empty_marketplace_sibling_when_rendered(project_name: str) -> None:
    # AGH-17 D4: the project adds its third-party pins to the seeded sibling.
    assert marketplace_project(a_config_named(project_name)) == {}


# Spec AC-4.7 (Q-5 keeps this hub's timeouts): event, matcher (``None``: no matcher key), the hook
# file the command runs, timeout in seconds.
HOOK_ROWS = (
    ("SessionStart", "startup|resume|clear|compact", "session_start.py", 20),
    (
        "PreToolUse",
        "Bash|Read|Grep|Glob|Edit|Write|MultiEdit|NotebookEdit|WebFetch",
        "guard.py",
        10,
    ),
    ("PostToolUse", "Edit|Write|MultiEdit", "post_edit.py", 60),
    ("Stop", None, "stop_gate.py", 180),
    ("PreCompact", None, "pre_compact.py", 20),
    ("SessionEnd", None, "session_end.py", 10),
)


def test_lists_six_hook_events_when_settings_built(demo_config: HubConfig) -> None:
    settings = managed_settings(demo_config)
    assert isinstance(settings, dict)

    expected = {}
    for event, matcher, file, timeout in HOOK_ROWS:
        group: dict[str, object] = {
            "hooks": [
                {
                    "type": "command",
                    "command": f'python3 "$CLAUDE_PROJECT_DIR/plugin/hub-workflow/hooks/{file}"',
                    "timeout": timeout,
                }
            ]
        }
        if matcher is not None:
            group["matcher"] = matcher
        expected[event] = [group]
    assert settings["hooks"] == expected


def test_renders_additional_directories_when_repos_listed(
    demo_config: HubConfig, variant_config: HubConfig
) -> None:
    demo = managed_settings(demo_config)
    variant = managed_settings(variant_config)
    assert isinstance(demo, dict)
    assert isinstance(variant, dict)
    assert isinstance(demo["permissions"], dict)
    assert isinstance(variant["permissions"], dict)

    # Spec D5: `../<dir>` for each repo, in `hub.json` order; no project name is written.
    assert demo["permissions"]["additionalDirectories"] == ["../demo-api"]
    assert variant["permissions"]["additionalDirectories"] == ["../demo-api", "../demo-web"]


def test_renders_repos_in_config_order_when_repos_reordered() -> None:
    document = a_hub_document()
    document["repos"] = [
        {"dir": repo_dir, "github": f"acme/{repo_dir}", "check_fast": "make a", "check": "make b"}
        for repo_dir in ("zeta", "alpha")
    ]
    document["guard"] = {}
    settings = managed_settings(HubConfig.model_validate(document))
    assert isinstance(settings, dict)
    assert isinstance(settings["permissions"], dict)

    assert settings["permissions"]["additionalDirectories"] == ["../zeta", "../alpha"]


def test_equals_managed_hooks_when_base_block_read(demo_config: HubConfig) -> None:
    # Spec AC-11.12 (Q-14): hub doctor's settings.weakening compares against this block: the value
    # the managed settings embed; reading it renders nothing.
    settings = managed_settings(demo_config)
    assert isinstance(settings, dict)
    expected = copy.deepcopy(settings["hooks"])

    block = base_hooks_block()

    assert block == expected
    assert list(block) == [hook.event for hook in HOOK_EVENTS]
    assert len(block) == 6
    # Each call builds a new value: a caller that edits one, at the top or deeper, cannot change
    # the next.
    block["Stop"] = []
    groups = block["PreToolUse"]
    assert isinstance(groups, list)
    assert isinstance(groups[0], dict)
    hooks = groups[0]["hooks"]
    assert isinstance(hooks, list)
    hooks.clear()
    assert base_hooks_block() == expected
    assert base_hooks_block()["Stop"][0] is not base_hooks_block()["Stop"][0]


BASE_HOSTS = [
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
]
PROJECT_HOSTS = ["linear.app", "*.linear.app", "docs.python.org"]


def test_keeps_project_sandbox_hosts_when_sibling_merged(demo_config: HubConfig) -> None:
    # AGH-16 D2 (E14): the base sandbox is managed; inventory row S6b's tracker and project hosts
    # come from the sibling and merge after the base hosts, a repeated base host kept once.
    template = managed_settings(demo_config)
    sibling = {"sandbox": {"network": {"allowedDomains": ["github.com", *PROJECT_HOSTS]}}}

    merged = json.loads(
        merge_json(
            template, json.dumps(sibling).encode("utf-8"), path=".claude/settings.project.json"
        )
    )

    assert merged["sandbox"]["network"]["allowedDomains"] == BASE_HOSTS + PROJECT_HOSTS
    assert merged["sandbox"]["network"]["allowLocalBinding"] is True
    assert merged["sandbox"]["enabled"] is True
    assert merged["sandbox"]["allowUnsandboxedCommands"] is False
    assert merged["permissions"] == template["permissions"]  # type: ignore[index]


@pytest.mark.parametrize(
    ("sibling", "key_path"),
    [
        ({"disableAllHooks": True}, "disableAllHooks"),
        ({"permissions": {"defaultMode": "bypassPermissions"}}, "permissions.defaultMode"),
    ],
)
def test_refuses_weakening_key_when_sibling_merged_over_base(
    sibling: dict[str, object], key_path: str, demo_config: HubConfig
) -> None:
    # The base denies and sandbox do not change the refusals: the sibling still cannot weaken.
    with pytest.raises(MergeError) as caught:
        merge_json(
            managed_settings(demo_config),
            json.dumps(sibling).encode("utf-8"),
            path=".claude/settings.project.json",
        )

    assert caught.value.key_path == key_path


def test_denies_push_to_each_protected_branch_when_default_branch_not_main(
    variant_config: HubConfig,
) -> None:
    # The guard's protected set (`main`, `master`, the project's `trunk`), sorted; piped shells
    # are denied as the subcommand Claude Code matches on its own.
    settings = managed_settings(variant_config)
    assert isinstance(settings, dict)
    assert isinstance(settings["permissions"], dict)

    assert settings["permissions"]["deny"] == [
        "Read(**/*.pem)",
        "Read(**/*.key)",
        "Bash(git push --force*)",
        "Bash(git push -f *)",
        "Bash(git push * main)",
        "Bash(git push origin HEAD:main*)",
        "Bash(git push * master)",
        "Bash(git push origin HEAD:master*)",
        "Bash(git push * trunk)",
        "Bash(git push origin HEAD:trunk*)",
        "Bash(terraform *)",
        "Bash(aws *)",
        "Bash(security *)",
        "Bash(ssh *)",
        "Bash(sh)",
        "Bash(bash)",
    ]


def test_denies_push_to_repo_branch_when_repo_sets_default_branch() -> None:
    document = a_hub_document()
    document["repos"][0]["default_branch"] = "develop"
    settings = managed_settings(HubConfig.model_validate(document))
    assert isinstance(settings, dict)
    assert isinstance(settings["permissions"], dict)

    pushes = [rule for rule in settings["permissions"]["deny"] if " * " in str(rule)]
    assert pushes == [
        "Bash(git push * develop)",
        "Bash(git push * main)",
        "Bash(git push * master)",
    ]


def test_keeps_sibling_sandbox_scalar_when_sibling_disables_sandbox(
    demo_config: HubConfig,
) -> None:
    # Owner decision (AGH-16 task 2.5 review): on scalars the project wins, so a sibling may turn
    # the base sandbox off; only managed or CLI settings could enforce it.
    sibling = {"sandbox": {"enabled": False}}

    merged = json.loads(
        merge_json(
            managed_settings(demo_config),
            json.dumps(sibling).encode("utf-8"),
            path=".claude/settings.project.json",
        )
    )

    assert merged["sandbox"]["enabled"] is False
    assert merged["sandbox"]["allowUnsandboxedCommands"] is False
    assert merged["sandbox"]["network"]["allowedDomains"] == BASE_HOSTS
