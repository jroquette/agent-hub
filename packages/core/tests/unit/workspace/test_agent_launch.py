import json

from agent_hub.core.workspace.agent_launch import (
    context_text,
    launch_argv,
    missing_repo_warning,
    settings_json,
)


def test_heads_each_section_when_context_built() -> None:
    text = context_text([("a", b"# A\nrules\n"), ("b", b"no final newline")])

    assert text == (
        b"\n# Instructions for ../a (from a/AGENTS.md)\n\n# A\nrules\n"
        b"\n# Instructions for ../b (from b/AGENTS.md)\n\nno final newline"
    )


def test_builds_empty_context_when_no_section() -> None:
    assert context_text([]) == b""


def test_dumps_settings_when_hub_path_has_quote() -> None:
    hub = '/work/my "hub"'

    settings = settings_json(hub)

    assert json.loads(settings) == {"autoMemoryDirectory": '/work/my "hub"/brain/auto/workspace'}
    assert settings_json("/work/hub") == '{"autoMemoryDirectory": "/work/hub/brain/auto/workspace"}'


def test_orders_argv_when_launch_built() -> None:
    argv = launch_argv(
        attached=["/ws/a", "/ws/b"],
        context_file="/ws/hub/brain/auto/agent-context.md",
        settings='{"k": "v"}',
        extra=["--resume", "s", "-p", "x y"],
    )

    assert argv == [
        "claude",
        "--add-dir",
        "/ws/a",
        "--add-dir",
        "/ws/b",
        "--append-system-prompt-file",
        "/ws/hub/brain/auto/agent-context.md",
        "--settings",
        '{"k": "v"}',
        "--resume",
        "s",
        "-p",
        "x y",
    ]


def test_names_repo_when_warning_built() -> None:
    assert (
        missing_repo_warning("/ws/c")
        == "warning: /ws/c not found (listed in hub.json); not attached"
    )
