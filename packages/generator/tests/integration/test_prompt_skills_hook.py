"""The UserPromptSubmit hook ``prompt_skills.py`` (AGH-838, ADR 0062): a skill the user names
anywhere in a message runs as if typed first.

Each prompt runs through the rendered hook as Claude Code runs it: the file on ``hook_python``
with the event on stdin, in an environment built from scratch, in a rendered demo hub (its
``.claude/skills/`` links included). The hook prints one ``additionalContext`` naming each skill
the prompt invokes, in order, or nothing.
"""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document

HOOK = "plugin/hub-workflow/hooks/prompt_skills.py"
SESSION = "5e55a0b1-0000-4000-8000-000000000002"
LEAD = "[hub] The user invoked these skills by name in this message."

type Completed = subprocess.CompletedProcess[bytes]
type RunHook = Callable[..., Completed]
type Run = Callable[..., Completed]


@pytest.fixture
def hub(rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig) -> Path:
    """``ws/demo-hub`` with its ``hub.json`` (``hub init`` writes it, ``render_hub`` does not)."""
    hub = rendered_hub(demo_config).resolve()
    (hub / "hub.json").write_text(json.dumps(a_hub_document()), encoding="utf-8")
    return hub


def prompt_event(hub: Path, prompt: str) -> bytes:
    return json.dumps(
        {
            "session_id": SESSION,
            "transcript_path": f"/home/u/.claude/projects/x/{SESSION}.jsonl",
            "cwd": str(hub),
            "hook_event_name": "UserPromptSubmit",
            "permission_mode": "default",
            "prompt": prompt,
        }
    ).encode("utf-8")


@pytest.fixture
def run(run_hook_file: RunHook, hook_python: str, hub: Path) -> Run:
    """Run the hook on ``hook_python`` in ``hub`` with ``stdin``; it must exit 0."""

    def run_it(stdin: bytes, env: dict[str, str] | None = None) -> Completed:
        completed = run_hook_file(hook_python, hub / HOOK, stdin=stdin, cwd=hub, env=env)
        assert completed.returncode == 0, completed.stderr
        return completed

    return run_it


def context_of(completed: Completed) -> str:
    """The ``additionalContext`` the hook printed, or "" when it printed nothing."""
    if not completed.stdout.strip():
        return ""
    output = json.loads(completed.stdout)
    assert output["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    text = output["hookSpecificOutput"]["additionalContext"]
    assert isinstance(text, str)
    return text


def steps(text: str) -> list[str]:
    assert text.startswith(LEAD), text
    return text.splitlines()[1:]


def test_names_model_invocable_skill_when_named_mid_message(run: Run, hub: Path) -> None:
    prompt = "claude, olha o PR; vamos usar a /overengineering-review para fazer uma review"

    text = context_of(run(prompt_event(hub, prompt)))

    assert steps(text) == [
        "1. `/overengineering-review`: load it with the Skill tool"
        " (skill `overengineering-review`)."
    ]


def test_names_skill_file_when_user_only_skill_named(run: Run, hub: Path) -> None:
    prompt = "ok, depois faz o /deliver desse PR"

    text = context_of(run(prompt_event(hub, prompt)))

    skill_file = hub / ".claude" / "skills" / "deliver" / "SKILL.md"
    assert skill_file.is_file()
    assert steps(text) == [
        f"1. `/deliver`: a user-only skill, which the Skill tool refuses: Read `{skill_file}`"
        " and follow it."
    ]


def test_names_plugin_skill_when_prefixed_form_named(run: Run, hub: Path) -> None:
    prompt = "please run /hub-workflow:design-fit on this change"

    in_hub = context_of(run(prompt_event(hub, prompt)))
    env = {"CLAUDE_PLUGIN_ROOT": str(hub / "plugin" / "hub-workflow")}
    from_plugin = context_of(run(prompt_event(hub, prompt), env))

    # In the hub the session lists it by its bare name (`.claude/skills/`); from the plugin,
    # prefixed.
    assert steps(in_hub) == [
        "1. `/hub-workflow:design-fit`: load it with the Skill tool (skill `design-fit`)."
    ]
    assert steps(from_plugin) == [
        "1. `/hub-workflow:design-fit`: load it with the Skill tool"
        " (skill `hub-workflow:design-fit`)."
    ]


def test_names_plugin_skill_when_hook_runs_from_plugin(run: Run, hub: Path) -> None:
    # A session outside the hub loads the plugin (`hub web`'s plugin_dirs): Claude Code sets
    # CLAUDE_PLUGIN_ROOT, and the skill is listed with the plugin's prefix.
    prompt = "first look, then /premortem the choice"
    env = {"CLAUDE_PLUGIN_ROOT": str(hub / "plugin" / "hub-workflow")}

    text = context_of(run(prompt_event(hub, prompt), env))

    assert steps(text) == [
        "1. `/premortem`: load it with the Skill tool (skill `hub-workflow:premortem`)."
    ]


def test_names_every_skill_in_order_when_several_named(run: Run, hub: Path) -> None:
    prompt = "/kickoff then /design-fit, then /review. And /design-fit again; /nope too."

    text = context_of(run(prompt_event(hub, prompt)))

    # The leading /kickoff is the CLI's own command; /nope is no skill; each name once.
    review = hub / ".claude" / "skills" / "review" / "SKILL.md"
    assert steps(text) == [
        "1. `/design-fit`: load it with the Skill tool (skill `design-fit`).",
        f"2. `/review`: a user-only skill, which the Skill tool refuses: Read `{review}`"
        " and follow it.",
    ]


def test_names_leading_skill_when_space_before_it(run: Run, hub: Path) -> None:
    # The CLI expands only a command at position 0: with a space before it, it is plain text.
    text = context_of(run(prompt_event(hub, " /kickoff")))

    assert steps(text) == ["1. `/kickoff`: load it with the Skill tool (skill `kickoff`)."]


def test_names_project_plugin_skill_when_its_folder_exists(run: Run, hub: Path) -> None:
    skill = hub / "plugin" / "demo" / "skills" / "house-style"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: house-style\ndescription: x\ndisable-model-invocation: true\n---\nBody.\n",
        encoding="utf-8",
    )

    text = context_of(run(prompt_event(hub, "use /house-style")))

    assert steps(text) == [
        f"1. `/house-style`: a user-only skill, which the Skill tool refuses: Read"
        f" `{skill / 'SKILL.md'}` and follow it."
    ]


@pytest.mark.parametrize(
    "prompt",
    [
        "/change",  # the CLI's own leading command
        "/change the bug",
        "see /usr/bin/change and /tmp/review",
        "a/change b/review",
        "https://example.com/change and http://x/review",
        "run \"/change\" and '/review'",
        "the file /change.py and /review.md",
        "quoted `/change` and (/review)",
        "/unknown-skill and /nope:change and /other-plugin:review",
        "/hub-workflow:/change and //change",
        "no slash at all",
        "",
    ],
)
def test_adds_nothing_when_no_skill_named_as_token(run: Run, hub: Path, prompt: str) -> None:
    completed = run(prompt_event(hub, prompt))

    assert completed.stdout == b""
    assert completed.stderr == b""


@pytest.mark.parametrize("ending", [".", ",", ";", ":", "!", "?", ")", '"', "'", "\n", ""])
def test_names_skill_when_punctuation_ends_it(run: Run, hub: Path, ending: str) -> None:
    prompt = f"then /premortem{ending}"

    text = context_of(run(prompt_event(hub, prompt)))

    assert steps(text) == ["1. `/premortem`: load it with the Skill tool (skill `premortem`)."]


@pytest.mark.parametrize(
    "stdin",
    [
        b"",
        b"not json",
        b"\xff\xfe",
        b"[1, 2]",
        b'{"prompt": 7}',
        b'{"hook_event_name": "UserPromptSubmit"}',
        b"[" * 100_000,
    ],
)
def test_adds_nothing_and_exits_zero_when_event_unusable(run: Run, hub: Path, stdin: bytes) -> None:
    completed = run(stdin)

    assert completed.stdout == b""
