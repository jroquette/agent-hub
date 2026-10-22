"""The post-merge-verify pack's ``selection.py``, in process: a merge (or the weekly ref) mapped to
its tickets and changed paths, then to the passing ACs of the hub's feature records to verify.
"""

import importlib.util
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(
        files("agent_hub.core").joinpath("workflows/builtin/post-merge-verify/scripts/selection.py")
    )
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.post-merge-verify.scripts.selection"

# The conftest's ``workspace``: a hub and its git repo ``demo-api``.
type Workspace = Any


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


def an_ac(ac_id: str, verification: str = "true", **given: Any) -> dict[str, Any]:
    found: dict[str, Any] = {
        "id": ac_id,
        "description": "A synthetic acceptance criterion.",
        "repo": "demo-api",
        "verification": verification,
        "passes": True,
        "evidence": "Passed.",
    }
    return found | given


def select(
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
) -> tuple[int, Any, str]:
    monkeypatch.chdir(workspace.hub)
    code = load().main(["--repo", "demo-api", *argv])
    captured = capsys.readouterr()
    return code, json.loads(captured.out) if code == 0 else None, captured.err


def a_merge(workspace: Workspace, branch: str, subject: str, **content: str) -> str:
    workspace.git("checkout", "-q", "-b", branch)
    workspace.commit("feat(api): the change (DEM-8)", **content)
    return workspace.merge(branch, subject)


def test_maps_merge_to_tickets_when_subjects_carry_keys(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    merge = a_merge(
        workspace,
        "jdoe/dem-7-thing",
        "Merge pull request #9 from acme/jdoe/dem-7-thing",
        src__api__x_py="x = 1\n",
    )
    squash = workspace.commit("fix(api): the squash (DEM-12)", src__api__y_py="y = 2\n")

    code, merged, _ = select(workspace, monkeypatch, capsys, "--sha", merge)
    squashed_code, squashed, _ = select(workspace, monkeypatch, capsys, "--sha", squash[:7])

    assert code == 0
    assert merged["mode"] == "merge"
    assert merged["sha"] == merge
    assert sorted(merged["tickets"]) == ["DEM-7", "DEM-8"]
    assert merged["repo_path"] == str(workspace.repo.resolve())
    assert squashed_code == 0
    assert squashed["tickets"] == ["DEM-12"]
    assert squashed["sha"] == squash


def test_lists_changed_paths_when_merge_has_first_parent(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    merge = a_merge(
        workspace,
        "jdoe/dem-7-thing",
        "Merge pull request #9 from acme/jdoe/dem-7-thing",
        src__api__x_py="x = 1\n",
        docs__a_md="a\n",
    )

    code, found, _ = select(workspace, monkeypatch, capsys, "--sha", merge)

    assert code == 0
    assert found["changed_paths"] == 2
    assert found["paths_truncated"] is False


@pytest.mark.parametrize("sha", ["0a1b2c3d4e5f", "not-a-sha", "-v"])
def test_exits_two_when_sha_is_unknown(
    sha: str,
    *,
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, _, err = select(workspace, monkeypatch, capsys, "--sha", sha)

    assert code == 2
    assert err.startswith("selection.py: ")


def test_exits_two_when_sha_has_no_parent(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = workspace.git("rev-list", "--max-parents=0", "HEAD")

    code, _, err = select(workspace, monkeypatch, capsys, "--sha", root)

    assert code == 2
    assert "no parent" in err


def test_exits_two_when_repo_is_not_in_hub_json(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(workspace.hub)

    code = load().main(["--repo", "other", "--sha", ""])

    assert code == 2
    assert "other" in capsys.readouterr().err


def test_resolves_ref_when_sha_is_blank(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    head = workspace.commit("feat(api): later (DEM-9)", later="1\n")
    workspace.git("branch", "verified")
    workspace.commit("feat(api): after (DEM-10)", after="1\n")

    code, found, _ = select(workspace, monkeypatch, capsys, "--sha", "", "--ref", "verified")
    bad, _, err = select(workspace, monkeypatch, capsys, "--sha", "", "--ref", "--all")

    assert code == 0
    assert found["mode"] == "weekly"
    assert found["sha"] == head
    assert found["tickets"] == []
    assert bad == 2
    assert err.startswith("selection.py: ")


def ticketed(key: str, **record: Any) -> dict[str, Any]:
    return {"feature": key, "acs": [an_ac("AC-1.1")]} | record


@pytest.mark.parametrize(
    ("key", "record"),
    [
        ("one", {"feature": "one", "acs": [an_ac("AC-1", ticket="DEM-7")]}),
        (
            "two",
            {
                "feature": "two",
                "tickets": [{"key": "T1", "id": "DEM-7"}],
                "acs": [an_ac("AC-1", ticket="T1")],
            },
        ),
        ("three", {"feature": "three", "linear": ["DEM-6", "DEM-7"], "acs": [an_ac("AC-7.2")]}),
        ("four", {"feature": "four", "linear": ["DEM-7"], "acs": [an_ac("AC-1")]}),
        ("grp/DEM-7", {"feature": "grp/DEM-7", "acs": [an_ac("AC-1")]}),
    ],
)
def test_selects_ticket_acs_when_ac_ticket_or_record_names_the_key(
    key: str,
    record: dict[str, Any],
    *,
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace.record(key, record)
    # Not selected: another ticket's AC in the same scheme.
    workspace.record("other", {"feature": "other", "acs": [an_ac("AC-1", ticket="DEM-70")]})
    workspace.record(
        "near", {"feature": "near", "linear": ["DEM-6", "DEM-7"], "acs": [an_ac("AC-6.1")]}
    )
    merge = a_merge(workspace, "jdoe/dem-7-x", "Merge pull request #9 from acme/jdoe/dem-7-x")

    code, found, _ = select(workspace, monkeypatch, capsys, "--sha", merge)

    assert code == 0
    assert {"feature": key, "ac": record["acs"][0]["id"], "why": "ticket"} in found["selected"]
    assert [item["feature"] for item in found["selected"]] == [key]


def test_selects_nested_record_when_features_json_sits_two_levels_deep(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace.record("grp/DEM-7", {"feature": "grp/DEM-7", "acs": [an_ac("AC-1"), an_ac("AC-2")]})
    merge = a_merge(workspace, "jdoe/dem-7-x", "Merge pull request #9 from acme/jdoe/dem-7-x")

    code, found, _ = select(workspace, monkeypatch, capsys, "--sha", merge)

    assert code == 0
    assert found["selected"] == [
        {"feature": "grp/DEM-7", "ac": "AC-1", "why": "ticket"},
        {"feature": "grp/DEM-7", "ac": "AC-2", "why": "ticket"},
    ]


def test_selects_ac_when_verification_names_a_changed_path_or_its_folder(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace.record(
        "paths",
        {
            "feature": "paths",
            "acs": [
                an_ac("AC-1", "uv run pytest src/api/test_x_py::test_a -q"),
                an_ac("AC-2", "uv run pytest src/api -q"),
                an_ac("AC-3", "uv run pytest src/web/test_y_py -q"),
                an_ac("AC-4", "uv run pytest src/ap -q"),
            ],
        },
    )
    merge = a_merge(
        workspace,
        "jdoe/dem-70-x",
        "Merge pull request #9 from acme/jdoe/dem-70-x",
        src__api__test_x_py="x = 1\n",
    )

    code, found, _ = select(workspace, monkeypatch, capsys, "--sha", merge)

    assert code == 0
    assert found["selected"] == [
        {"feature": "paths", "ac": "AC-1", "why": "path"},
        {"feature": "paths", "ac": "AC-2", "why": "path"},
    ]


def test_selects_every_passing_ac_when_mode_is_weekly(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace.record("a", {"feature": "a", "acs": [an_ac("AC-1"), an_ac("AC-2", passes=False)]})
    workspace.record("b", {"feature": "b", "acs": [an_ac("AC-3")]})

    code, found, _ = select(workspace, monkeypatch, capsys, "--sha", "", "--ref", "main")

    assert code == 0
    assert found["selected"] == [
        {"feature": "a", "ac": "AC-1", "why": "weekly"},
        {"feature": "b", "ac": "AC-3", "why": "weekly"},
    ]
    assert found["skipped_not_passing"] == 1


def test_skips_ac_when_not_passing_or_withdrawn_or_other_repo(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace.record(
        "grp/DEM-7",
        {
            "feature": "grp/DEM-7",
            "acs": [
                an_ac("AC-1"),
                an_ac("AC-2", passes=False),
                an_ac("AC-3", withdrawn=True),
                an_ac("AC-4", repo="other"),
                an_ac("AC-5", passes="true"),
            ],
        },
    )
    merge = a_merge(workspace, "jdoe/dem-7-x", "Merge pull request #9 from acme/jdoe/dem-7-x")

    code, found, _ = select(workspace, monkeypatch, capsys, "--sha", merge)

    assert code == 0
    assert found["selected"] == [{"feature": "grp/DEM-7", "ac": "AC-1", "why": "ticket"}]
    assert found["skipped_not_passing"] == 3


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("{not json", "not JSON"),
        ('{"feature": "x"}', "no acs list"),
        ('{"acs": [{"id": "AC-1", "repo": "demo-api"}]}', "AC 0 lacks verification"),
        (
            '{"acs": [{"id": "AC\\n1", "repo": "demo-api", "verification": "x", "passes": true}]}',
            "AC 0 id is not printable ASCII of 1 to 64 characters",
        ),
        ('{"acs": [7]}', "AC 0 is not an object"),
    ],
)
def test_lists_unreadable_record_when_features_json_is_not_json(
    content: str,
    reason: str,
    *,
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    folder = workspace.hub / "brain/features/broken"
    folder.mkdir()
    (folder / "features.json").write_text(content, encoding="utf-8")
    workspace.record("fine", {"feature": "fine", "acs": [an_ac("AC-1")]})

    code, found, _ = select(workspace, monkeypatch, capsys, "--sha", "", "--ref", "main")

    assert code == 0
    assert found["unreadable"] == [
        {"path": "brain/features/broken/features.json", "reason": reason}
    ]
    assert found["selected"] == [{"feature": "fine", "ac": "AC-1", "why": "weekly"}]


def test_skips_record_when_file_exceeds_size_cap(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    selection = load()
    big = workspace.record(
        "big", {"feature": "big", "acs": [an_ac("AC-1")], "pad": "x" * selection.MAX_RECORD_BYTES}
    )
    linked = workspace.hub / "brain/features/linked"
    linked.mkdir()
    (linked / "features.json").symlink_to(big)

    code, found, _ = select(workspace, monkeypatch, capsys, "--sha", "", "--ref", "main")

    assert code == 0
    assert found["unreadable"] == [
        {"path": "brain/features/big/features.json", "reason": "too large"}
    ]
    assert found["selected"] == []


def test_counts_truncated_when_selection_exceeds_cap(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cap = load().MAX_SELECTED
    workspace.record("many", {"feature": "many", "acs": [an_ac(f"AC-{n}") for n in range(cap + 3)]})

    code, found, _ = select(workspace, monkeypatch, capsys, "--sha", "", "--ref", "main")

    assert code == 0
    assert len(found["selected"]) == cap
    assert found["truncated"] == 3


def test_ignores_folders_deeper_than_the_scan_depth_when_records_scanned(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace.record("a/b/c/d", {"feature": "a/b/c/d", "acs": [an_ac("AC-1")]})
    workspace.record("a/b/c/d/e", {"feature": "a/b/c/d/e", "acs": [an_ac("AC-2")]})

    code, found, _ = select(workspace, monkeypatch, capsys, "--sha", "", "--ref", "main")

    assert code == 0
    assert found["selected"] == [{"feature": "a/b/c/d", "ac": "AC-1", "why": "weekly"}]


def test_reads_no_record_when_hub_has_no_features_folder(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (workspace.hub / "brain/features").rmdir()

    code, found, _ = select(workspace, monkeypatch, capsys, "--sha", "", "--ref", "main")

    assert code == 0
    assert found["selected"] == []
    assert found["unreadable"] == []


def test_exits_two_when_hub_json_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    code = load().main(["--repo", "demo-api"])

    assert code == 2
    assert "hub.json" in capsys.readouterr().err
