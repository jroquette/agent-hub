"""The flow catalog: one row per built-in workflow, derived from the packs and the skill
templates, never typed by hand (AGH-495).

TESTING.md: synthetic packs and skills written under ``tmp_path``, and the built-ins on disk.
"""

from pathlib import Path

import pytest

from agent_hub.generator.flow_catalog import (
    FLOW_FOOTER,
    Flow,
    builtin_flows,
    flow_table,
    missing_use_when,
)
from agent_hub.generator.workflow_discovery import discover_builtins

HEADER = "| Flow | Use when | Start | Your gates | Skills and agents inside |"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _workflow(root: Path, pack: str, name: str, *, nodes: str = "", description: str = "") -> None:
    head = f"version: 1\nname: {name}\nrevision: 1\n"
    if description:
        head += f"description: {description}\n"
    _write(root / pack / f"{name}.yaml", f"{head}nodes:\n{nodes or _SHELL}")


_SHELL = "  - id: a\n    type: shell\n    command: [x]\n"
_LONG = "Use when a bug has no reproduction yet. Finds evidence."


def _flows(tmp_path: Path) -> dict[str, Flow]:
    flows = builtin_flows(tmp_path / "builtin", tmp_path / "skills")
    return {flow.name: flow for flow in flows}


def _flow(**changes: object) -> Flow:
    values: dict[str, object] = {
        "name": "x",
        "pack": "p",
        "use_when": "Use when it rains on the hub.",
        "starts": ("`/x`",),
        "gates": (),
        "inside": (),
    } | changes
    return Flow(**values)  # type: ignore[arg-type]


def test_takes_first_sentence_as_use_when_when_catalog_built(tmp_path: Path) -> None:
    _workflow(tmp_path / "builtin", "ops", "incident", description=_LONG)
    _workflow(tmp_path / "builtin", "ops", "single", description="One sentence, no stop")

    flows = _flows(tmp_path)

    assert flows["incident"].use_when == "Use when a bug has no reproduction yet."
    assert flows["single"].use_when == "One sentence, no stop"


def test_reports_flow_without_use_when_when_catalog_built(tmp_path: Path) -> None:
    _workflow(tmp_path / "builtin", "ops", "bare")
    _workflow(tmp_path / "builtin", "ops", "terse", description="Ships it.")
    _workflow(tmp_path / "builtin", "ops", "told", description=_LONG)

    flows = _flows(tmp_path)

    assert flows["bare"].use_when is None
    assert missing_use_when(flows.values()) == ("bare", "terse")
    assert missing_use_when([_flow(use_when="   ")]) == ("x",)


@pytest.mark.parametrize(
    "case",
    [
        ("issue-to-pr", "./hub workflow run other", "`./hub run <issue>`"),
        ("spike", "Run `./hub workflow run spike --live`.", "`/s`"),
        ("child", "", "inside `parent`"),
        ("lone", "", "`./hub workflow run lone`"),
    ],
    ids=["tracker", "skill", "include", "command"],
)
def test_derives_start_from_skill_tracker_include_or_command_when_catalog_built(
    tmp_path: Path, case: tuple[str, str, str]
) -> None:
    name, skill, start = case
    builtin = tmp_path / "builtin"
    _workflow(builtin, "p", name, description=_LONG)
    if name == "child":
        _workflow(
            builtin, "p", "parent", nodes="  - id: c\n    type: include\n    include: child\n"
        )
    _write(tmp_path / "skills" / "s" / "SKILL.md.tmpl", f"---\nname: s\n---\n{skill}\n")

    assert _flows(tmp_path)[name].starts == (start,)


def test_lists_approval_and_attention_gates_once_when_catalog_built(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    gates = (
        "  - id: ok\n    type: approval\n    description: The owner approves the plan.\n"
        "    message: Approve?\n"
        "  - id: bare-ok\n    type: approval\n    message: Approve?\n    depends_on: [ok]\n"
        "  - id: look\n    type: wait\n    description: Someone reads the log.\n"
        "    attention: Read the log.\n    depends_on: [bare-ok]\n"
        "  - id: nap\n    type: wait\n    duration: 1s\n    depends_on: [look]\n"
    )
    _workflow(builtin, "p", "gated", nodes=gates)
    _workflow(
        builtin,
        "p",
        "twice",
        nodes="  - id: one\n    type: include\n    include: gated\n"
        "  - id: two\n    type: include\n    include: gated\n    depends_on: [one]\n",
    )
    _workflow(builtin, "p", "open")

    flows = _flows(tmp_path)

    expected = ("The owner approves the plan.", "bare-ok", "Someone reads the log.")
    assert flows["gated"].gates == expected
    assert flows["twice"].gates == expected
    assert flows["open"].gates == ()


def test_names_skills_and_agents_from_prompts_when_catalog_built(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    _write(
        builtin / "p" / "prompts" / "dig.md",
        "Read and follow `.claude/skills/recall/SKILL.md` first.\n",
    )
    nodes = (
        "  - id: dig\n    type: agent\n    prompt_file: dig.md\n"
        "  - id: ask\n    type: agent\n    prompt: Act as `.claude/agents/researcher.md` says.\n"
    )
    _workflow(builtin, "p", "reuses", nodes=nodes)
    _workflow(builtin, "p", "plain", nodes="  - id: a\n    type: agent\n    prompt: Do it.\n")

    flows = _flows(tmp_path)

    assert flows["reuses"].inside == ("`/recall`", "`researcher` agent")
    assert flows["plain"].inside == ()


def test_escapes_pipes_and_newlines_when_catalog_table_rendered() -> None:
    flow = _flow(
        use_when="Use when a | b\nholds.",
        gates=("one", "two"),
        inside=("`/recall`",),
    )
    bare = _flow(name="y", use_when=None, starts=("inside `x`",))

    table = flow_table([flow, bare])

    lines = table.splitlines()
    assert lines[0] == HEADER
    assert lines[1] == "|---|---|---|---|---|"
    assert lines[2] == "| `x` (`p` pack) | Use when a \\| b holds. | `/x` | one; two | `/recall` |"
    assert lines[3] == "| `y` (`p` pack) |  | inside `x` | none | own prompts |"
    assert lines[4:] == ["", FLOW_FOOTER]
    assert table.endswith("\n")


# AC-3: every built-in workflow on disk has a "use when" line, the first sentence of its
# description; a new pack's workflow is covered as soon as its file lands.
def test_finds_use_when_for_every_builtin_flow_when_catalog_built() -> None:
    flows = builtin_flows()

    assert missing_use_when(flows) == ()
    assert {flow.name for flow in flows} == {w.name for w in discover_builtins().workflows}
