"""The owner sign-off's eval note on the file system (playground, AC-PG-10.1): ``HubEvalWriter``
creates it exclusively under ``brain/features/<slug>/evals/``, ``ProjectHubPaths`` finds the hub."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_hub.api.owner_signoff_files import HubEvalWriter, ProjectHubPaths
from agent_hub.core.features.feature_evals import eval_records
from agent_hub.core.features.feature_status import FeatureFolder, RecordHead
from agent_hub.core.features.feature_view import EvalRecord
from agent_hub.core.features.owner_signoff import SignOffOwnerSteps
from agent_hub.core.projects.project_views import ProjectDetail, TrackerView
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.testing.read_model_builders import HUB_ID
from agent_hub.generator.feature_files import read_feature_folder

SLUG = "demo-feature"
RECORD = {
    "acs": [
        {"id": "AC-7.1", "description": "Given x, when y, then z", "passes": True},
        {"id": "AC-7.2", "description": "Given x, when y, then z", "passes": True},
    ]
}


def _eval(verdict: str, evaluated_at: str) -> str:
    return f"---\ntype: eval\nverdict: {verdict}\nacs: all\nevaluated_at: {evaluated_at}\n---\n"


def _hub(tmp_path: Path) -> Path:
    hub = tmp_path / "demo-hub"
    feature = hub / "brain" / "features" / SLUG
    feature.mkdir(parents=True)
    (feature / "features.json").write_text(json.dumps(RECORD), encoding="utf-8")
    return hub


def _detail(hub: Path) -> ProjectDetail:
    return ProjectDetail(
        name="demo",
        hub_id=HUB_ID,
        hub_path=str(hub),
        hub_repo="acme/demo-hub",
        tracker=TrackerView(kind="linear", teams=("DEM",), ready_label=None, failed_label=None),
        default_branch="main",
        branch_prefix="jdoe/",
        platform_version="0.8.0",
        lock_version="0.8.0",
        lock_state="in_sync",
        modules=(),
    )


class DiskFolders:
    """``FeatureFolders`` over the hub's real files, read as ``hub web`` reads them."""

    def feature_folder(self, hub_path: str, slug: str) -> FeatureFolder | None:
        return read_feature_folder(Path(hub_path), slug)


def _read_note(note: Path) -> EvalRecord:
    """The note as the feature reader parses it."""
    [read] = eval_records(
        (RecordHead(name=note.name, head=note.read_bytes(), problem=None),), None, slug=SLUG
    )
    return read


def _sign_off(hub: Path, fakes: SimpleNamespace, at: datetime) -> SignOffOwnerSteps:
    models = fakes.HubReadModels(details={"demo": _detail(hub)})
    return SignOffOwnerSteps(
        ProjectHubPaths(models), DiskFolders(), HubEvalWriter(), clock=lambda: at
    )


# AC-PG-10.1: the hub folder of a project comes from the read models.
def test_answers_hub_path_when_project_known(tmp_path: Path, fakes: SimpleNamespace) -> None:
    models = fakes.HubReadModels(details={"demo": _detail(tmp_path)})

    assert ProjectHubPaths(models).hub_path_of("demo") == str(tmp_path)


# AC-PG-10.1: an unknown project stays not found (the route answers 404).
def test_raises_not_found_when_project_unknown(fakes: SimpleNamespace) -> None:
    with pytest.raises(EntityNotFoundError):
        ProjectHubPaths(fakes.HubReadModels()).hub_path_of("nope")


# AC-PG-10.1: the note lands in brain/features/<slug>/evals/, the folder created when missing.
def test_creates_note_in_evals_folder_when_feature_exists(tmp_path: Path) -> None:
    hub = _hub(tmp_path)

    HubEvalWriter().create_eval(str(hub), slug=SLUG, name="owner-signoff.md", text="note\n")

    note = hub / "brain" / "features" / SLUG / "evals" / "owner-signoff.md"
    assert note.read_text(encoding="utf-8") == "note\n"


# AC-PG-10.1: an eval already there is never overwritten.
def test_refuses_and_keeps_note_when_name_taken(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    writer = HubEvalWriter()
    writer.create_eval(str(hub), slug=SLUG, name="owner-signoff.md", text="first\n")

    with pytest.raises(FileExistsError):
        writer.create_eval(str(hub), slug=SLUG, name="owner-signoff.md", text="second\n")

    note = hub / "brain" / "features" / SLUG / "evals" / "owner-signoff.md"
    assert note.read_text(encoding="utf-8") == "first\n"


# AC-PG-10.1: no feature folder, nothing written.
def test_refuses_when_feature_folder_missing(tmp_path: Path) -> None:
    hub = _hub(tmp_path)

    with pytest.raises(FileNotFoundError):
        HubEvalWriter().create_eval(str(hub), slug="other", name="owner-signoff.md", text="x")

    assert not (hub / "brain" / "features" / "other").exists()


# AC-PG-10.1: no link is followed into the feature folder or its evals folder.
@pytest.mark.parametrize("linked", ["feature", "evals"])
def test_refuses_when_folder_is_a_link(tmp_path: Path, linked: str) -> None:
    hub = _hub(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    feature = hub / "brain" / "features" / SLUG
    if linked == "feature":
        (hub / "brain" / "features" / "linked").symlink_to(feature, target_is_directory=True)
        slug = "linked"
    else:
        (feature / "evals").symlink_to(elsewhere, target_is_directory=True)
        slug = SLUG

    with pytest.raises(FileNotFoundError):
        HubEvalWriter().create_eval(str(hub), slug=slug, name="owner-signoff.md", text="x")

    assert list(elsewhere.iterdir()) == []


# AC-PG-10.1: the slug and the note name are single names, never a path.
@pytest.mark.parametrize(
    ("slug", "name"),
    [
        ("../demo", "owner-signoff.md"),
        (".hidden", "owner-signoff.md"),
        (SLUG, "../x.md"),
        (SLUG, ".x"),
    ],
)
def test_refuses_when_name_not_single(tmp_path: Path, slug: str, name: str) -> None:
    hub = _hub(tmp_path)

    with pytest.raises(ValueError, match="invalid feature or eval name"):
        HubEvalWriter().create_eval(str(hub), slug=slug, name=name, text="x")

    assert not (hub / "brain" / "features" / SLUG / "evals").exists()


# AC-PG-10.1: the sign-off writes owner-signoff.md: verdict SHIP, provenance owner, those ACs.
def test_writes_owner_signoff_note_when_owner_steps_wait(
    tmp_path: Path, fakes: SimpleNamespace
) -> None:
    hub = _hub(tmp_path)
    evals = hub / "brain" / "features" / SLUG / "evals"
    evals.mkdir()
    (evals / "dem-7.md").write_text(_eval("SHIP-WITH-OWNER-STEPS", "2026-10-08"), "utf-8")
    at = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)

    record = _sign_off(hub, fakes, at)("demo", SLUG)

    assert (record.delivery, record.verdict, record.acs) == (
        "owner-signoff",
        "SHIP",
        ("AC-7.1", "AC-7.2"),
    )
    assert record.path == f"features/{SLUG}/evals/owner-signoff.md"
    text = (evals / "owner-signoff.md").read_text(encoding="utf-8")
    assert "verdict: SHIP\n" in text
    assert "provenance: owner\n" in text
    assert "acs: [AC-7.1, AC-7.2]\n" in text
    written = _read_note(evals / "owner-signoff.md")
    assert (written.delivery, written.verdict, written.provenance, written.problem) == (
        "owner-signoff",
        "SHIP",
        "owner",
        None,
    )
    assert written.acs == ("AC-7.1", "AC-7.2")


# AC-PG-10.1: when owner-signoff is taken, the next sign-off is owner-signoff-r2.
def test_writes_rerun_note_when_owner_signoff_taken(tmp_path: Path, fakes: SimpleNamespace) -> None:
    hub = _hub(tmp_path)
    evals = hub / "brain" / "features" / SLUG / "evals"
    evals.mkdir()
    (evals / "dem-7.md").write_text(_eval("SHIP-WITH-OWNER-STEPS", "2026-10-08"), "utf-8")
    _sign_off(hub, fakes, datetime(2026, 10, 17, 12, 0, tzinfo=UTC))("demo", SLUG)
    (evals / "dem-8.md").write_text(_eval("SHIP-WITH-OWNER-STEPS", "2026-10-18"), "utf-8")

    record = _sign_off(hub, fakes, datetime(2026, 10, 19, 12, 0, tzinfo=UTC))("demo", SLUG)

    assert record.delivery == "owner-signoff-r2"
    assert sorted(path.name for path in evals.iterdir()) == [
        "dem-7.md",
        "dem-8.md",
        "owner-signoff-r2.md",
        "owner-signoff.md",
    ]
    rerun = _read_note(evals / "owner-signoff-r2.md")
    assert (rerun.delivery, rerun.verdict, rerun.provenance) == (
        "owner-signoff-r2",
        "SHIP",
        "owner",
    )
    assert rerun.acs == ("AC-7.1", "AC-7.2")
