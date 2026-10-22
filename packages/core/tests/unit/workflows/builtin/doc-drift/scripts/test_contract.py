"""The doc-drift pack's ``contract.py`` (AGH-491), in process: which contract names a change
removed, and whether anything still declares them."""

import importlib.util
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/doc-drift/scripts/contract.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.doc-drift.scripts.contract"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


contract = load()


def patch_of(path: str, removed: list[str], added: list[str], *, header: str = "") -> str:
    """A ``git diff -U0`` patch of one modified file."""
    lines = [f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}"]
    lines.append(f"@@ -1,{len(removed)} +1,{len(added)} @@ {header}".rstrip())
    lines += [f"-{line}" for line in removed] + [f"+{line}" for line in added]
    return "\n".join(lines) + "\n"


def new_file(path: str, added: list[str]) -> str:
    lines = [f"diff --git a/{path} b/{path}", "--- /dev/null", f"+++ b/{path}"]
    lines.append(f"@@ -0,0 +1,{len(added)} @@")
    return "\n".join(lines + [f"+{line}" for line in added]) + "\n"


def found(status: list[tuple[str, str, str]], patch: str) -> list[tuple[str, str, tuple[str, ...]]]:
    return [(name.kind, name.name, name.new) for name in contract.names_from(status, patch).names]


def test_finds_old_command_and_new_hint_when_typer_command_renamed() -> None:
    patch = patch_of(
        "src/demo/cli.py", ['@app.command("old-cmd")'], ['@app.command("new-cmd")'], header="x"
    )

    extracted = contract.names_from([("M", "src/demo/cli.py", "")], patch)

    assert extracted.names == [contract.Name("command", "old-cmd", ("new-cmd",), "src/demo/cli.py")]
    assert extracted.skipped == 0


MIGRATION = "src/demo/migrations/versions/0002_x.py"


@pytest.mark.parametrize(
    ("status", "patch", "expected"),
    [
        pytest.param(
            [("M", "src/demo/cli.py", "")],
            patch_of(
                "src/demo/cli.py",
                ['app.add_typer(group_app, name="old-group")'],
                ['app.add_typer(group_app, name="new-group")'],
            ),
            ("command", "old-group", ("new-group",)),
            id="typer-group",
        ),
        pytest.param(
            [("M", "Makefile", "")],
            patch_of("Makefile", ["old-target: deps"], ["new-target: deps"]),
            ("make-target", "old-target", ("new-target",)),
            id="make-target",
        ),
        pytest.param(
            [("M", "src/demo/cli.py", "")],
            patch_of(
                "src/demo/cli.py",
                ['    typer.Option("--old-flag")'],
                ['    typer.Option("--new-flag")'],
            ),
            ("flag", "--old-flag", ("--new-flag",)),
            id="flag",
        ),
        pytest.param(
            [("M", "src/demo/hub.schema.json", "")],
            patch_of(
                "src/demo/hub.schema.json",
                ['    "old_key": {"type": "string"},'],
                ['    "new_key": {"type": "string"},'],
            ),
            ("config-key", "old_key", ("new_key",)),
            id="config-key",
        ),
        pytest.param(
            [("R", "plugin/skills/old-skill/SKILL.md", "plugin/skills/new-skill/SKILL.md")],
            "",
            ("skill", "old-skill", ("new-skill",)),
            id="skill",
        ),
        pytest.param(
            [("D", "workflows/pack/old-flow.yaml", "")],
            "",
            ("workflow", "old-flow", ()),
            id="workflow",
        ),
        pytest.param(
            [("R", "docs/guide-old.md", "docs/guide-new.md")],
            "",
            ("path", "docs/guide-old.md", ("docs/guide-new.md",)),
            id="path",
        ),
        pytest.param(
            [("A", MIGRATION, "")],
            new_file(
                MIGRATION,
                [
                    "def upgrade() -> None:",
                    '    op.drop_column("runs", "old_col")',
                    "",
                    "",
                    "def downgrade() -> None:",
                    '    op.add_column("runs", sa.Column("old_col", sa.Text()))',
                ],
            ),
            ("column", "old_col", ()),
            id="drop-column",
        ),
        pytest.param(
            [("A", MIGRATION, "")],
            new_file(
                MIGRATION,
                [
                    "def upgrade() -> None:",
                    "    op.alter_column(",
                    '        "runs", "old_name", new_column_name="new_name"',
                    "    )",
                ],
            ),
            ("column", "old_name", ("new_name",)),
            id="alter-column",
        ),
    ],
)
def test_finds_rule_per_kind_when_patch_removes_contract_name(
    status: list[tuple[str, str, str]], patch: str, expected: tuple[str, str, tuple[str, ...]]
) -> None:
    assert expected in found(status, patch)


def test_ignores_downgrade_when_migration_drops_in_downgrade_only() -> None:
    patch = new_file(
        MIGRATION,
        [
            "def upgrade() -> None:",
            '    op.create_table("runs")',
            "",
            "",
            "def downgrade() -> None:",
            '    op.drop_table("runs")',
            '    op.drop_column("runs", "old_col")',
        ],
    )

    assert found([("A", MIGRATION, "")], patch) == []


def test_ignores_schema_keywords_when_schema_lines_removed() -> None:
    patch = patch_of(
        "src/demo/hub.schema.json", ['  "type": "object",', '  "properties": {'], ["  {"]
    )

    assert found([("M", "src/demo/hub.schema.json", "")], patch) == []


def test_finds_no_name_when_merge_changes_only_internals() -> None:
    body = patch_of("src/demo/core.py", ["    return 1"], ["    return 2"], header="def f():")
    added = patch_of("src/demo/cli.py", [], ['@app.command("added")'])

    assert found([("M", "src/demo/core.py", ""), ("M", "src/demo/cli.py", "")], body + added) == []


def test_skips_short_name_when_shorter_than_three_characters() -> None:
    patch = patch_of("src/demo/cli.py", ['@app.command("ab")', "--x"], [])

    extracted = contract.names_from([("M", "src/demo/cli.py", "")], patch)

    assert extracted.names == []
    assert extracted.skipped == 1


def test_ignores_test_and_doc_lines_when_they_remove_a_flag() -> None:
    tests = patch_of("tests/test_cli.py", ['run("--old-flag")'], [])
    docs = patch_of("docs/USING.md", ["Use `--old-flag`."], [])

    assert found([("M", "tests/test_cli.py", ""), ("M", "docs/USING.md", "")], tests + docs) == []


@pytest.mark.parametrize(
    ("kind", "name", "tree", "expected"),
    [
        ("command", "old-cmd", {"src/other.py": '@x.command("old-cmd")'}, True),
        ("command", "old-group", {"src/other.py": '    name="old-group",'}, True),
        ("command", "old-cmd", {"llms-full.txt": '@x.command("old-cmd")'}, False),
        ("make-target", "old-target", {"mk/x.mk": "old-target: y\n"}, True),
        ("make-target", "old-target", {"Makefile": "x: old-target\n"}, False),
        ("flag", "--old-flag", {"src/a.py": 'Option("--old-flag")'}, True),
        ("flag", "--old-flag", {"src/a.py": 'Option("--old-flag-two")'}, False),
        ("config-key", "old_key", {"a.schema.json": '"old_key": {}'}, True),
        ("skill", "old-skill", {"p/skills/old-skill/SKILL.md.tmpl": ""}, True),
        ("workflow", "old-flow", {"workflows/x/old-flow.yaml": ""}, True),
        ("path", "docs/a.md", {"docs/a.md": ""}, True),
        ("column", "old_col", {"src/m.py": "old_col"}, False),
    ],
)
def test_reads_declarations_when_tree_checked(
    kind: str, name: str, tree: dict[str, str], *, expected: bool
) -> None:
    assert contract.still_declared(kind, name, tree) is expected


def test_counts_truncated_when_names_exceed_cap() -> None:
    many = [contract.Name("flag", f"--flag-{n}", (), "src/a.py") for n in range(150)]
    long = "x" * 200
    heavy = [contract.Name("path", f"{long}{n}"[-200:], (long,) * 5, long) for n in range(100)]

    kept, truncated = contract.capped(many)
    heavy_kept, heavy_truncated = contract.capped(heavy)

    assert (len(kept), truncated) == (100, 50)
    assert heavy_truncated > 0
    assert len(heavy_kept) + heavy_truncated == 100
    size = sum(len(str(name.as_json())) for name in heavy_kept)
    assert size <= contract.MAX_NAMES_BYTES
