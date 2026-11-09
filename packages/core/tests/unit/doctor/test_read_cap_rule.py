"""``instructions.read_cap``: an instruction file sends agents to a doc over the Read tool's cap.

The cap is about 25,000 tokens, read from the doc's size (``READ_CAP_BYTES``). Every text here is
synthetic (AGENTS.md rule 4).
"""

from collections.abc import Callable

from agent_hub.core.doctor.finding import Read
from agent_hub.core.doctor.read_cap_rule import FIX, INSTRUCTIONS_READ_CAP, READ_CAP_BYTES
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import RULE_IDS, Severity

type SnapshotFactory = Callable[..., DoctorSnapshot]

OVER = b"x" * (READ_CAP_BYTES + 1)
UNDER = b"x" * READ_CAP_BYTES


def findings(snapshot: DoctorSnapshot) -> list[tuple[str | None, int | None, str]]:
    return [(f.path, f.line, f.message) for f in INSTRUCTIONS_READ_CAP.check(snapshot)]


def over_message(doc: str, size: int) -> str:
    return (
        f"sends agents to {doc} ({size} bytes), over the Read tool's cap of about 25000"
        f" tokens ({READ_CAP_BYTES} bytes): one Read cannot hold it"
    )


def test_declares_design_fields_when_rule_read() -> None:
    assert INSTRUCTIONS_READ_CAP.id == "instructions.read_cap"
    assert INSTRUCTIONS_READ_CAP.severity is Severity.WARNING
    assert INSTRUCTIONS_READ_CAP.reads == frozenset(
        {Read.INSTRUCTION_FILES, Read.PLUGIN_FILES, Read.REPOS}
    )
    assert INSTRUCTIONS_READ_CAP.module is None
    assert READ_CAP_BYTES == 65_536
    assert "instructions.read_cap" in RULE_IDS


def test_finds_nothing_when_linked_doc_under_cap(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(
        files={"AGENTS.md": b"# Hub\n\nRead `docs/SPEC.md` first.\n", "docs/SPEC.md": UNDER}
    )

    assert findings(snapshot) == []


def test_warns_once_with_size_when_hub_doc_over_cap(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(
        files={
            "AGENTS.md": b"# Hub\n\nThe spec: [SPEC](docs/SPEC.md#rules).\nAgain `docs/SPEC.md`.\n",
            "docs/SPEC.md": OVER,
        }
    )

    found = list(INSTRUCTIONS_READ_CAP.check(snapshot))

    assert [(f.path, f.line, f.message, f.fix) for f in found] == [
        ("AGENTS.md", 3, over_message("docs/SPEC.md", len(OVER)), FIX.format(doc="docs/SPEC.md"))
    ]
    assert found[0].severity is Severity.WARNING


def test_resolves_from_file_folder_when_skill_names_sibling(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(
        files={
            "plugin/demo/skills/plan/SKILL.md": b"Read `guide.md` before you plan.\n",
            "plugin/demo/skills/plan/guide.md": OVER,
        }
    )

    assert findings(snapshot) == [
        (
            "plugin/demo/skills/plan/SKILL.md",
            1,
            over_message("plugin/demo/skills/plan/guide.md", len(OVER)),
        )
    ]


def test_warns_at_repo_path_when_repo_agents_names_big_spec(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(
        repos={
            "demo-api": {
                "AGENTS.md": b"# demo-api\n\nThe spec is in `docs/SPEC.md`: read it first.\n",
                "docs/SPEC.md": OVER,
            }
        }
    )

    assert findings(snapshot) == [
        ("../demo-api/AGENTS.md", 3, over_message("docs/SPEC.md", len(OVER)))
    ]


def test_finds_nothing_when_named_doc_missing(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(
        files={"AGENTS.md": b"Read `docs/gone.md` and [it](missing/x.md).\n"},
        repos={"demo-api": {"AGENTS.md": b"Read `docs/SPEC.md`.\n"}, "demo-web": None},
    )

    assert findings(snapshot) == []


def test_finds_nothing_when_big_file_not_a_doc(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(
        files={"AGENTS.md": b"Checked against `hub.schema.json`.\n", "hub.schema.json": OVER}
    )

    assert findings(snapshot) == []


def test_finds_nothing_when_big_doc_unlisted(snapshot_of: SnapshotFactory) -> None:
    # A doc git does not list (ignored, deleted) is not one the agents are sent to.
    snapshot = snapshot_of(
        files={"AGENTS.md": b"Read `docs/SPEC.md`.\n", "docs/SPEC.md": OVER},
        listed=("AGENTS.md",),
    )

    assert findings(snapshot) == []
