import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.built_json import managed_settings, project_manifest, project_settings


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
