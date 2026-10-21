"""The change request decision on the file system (two-level-flows AC-2.14, D-11):
``HubDecisionWriter`` creates it exclusively in ``change-requests/``, following no link."""

from pathlib import Path

import pytest

from agent_hub.api.change_request_files import HubDecisionWriter

SLUG = "demo-feature"


def _hub(tmp_path: Path) -> Path:
    hub = tmp_path / "demo-hub"
    (hub / "brain" / "features" / SLUG / "change-requests").mkdir(parents=True)
    return hub


def test_creates_decision_when_request_folder_exists(tmp_path: Path) -> None:
    hub = _hub(tmp_path)

    HubDecisionWriter().create_decision(str(hub), slug=SLUG, n=2, text="decided\n")

    decision = hub / "brain" / "features" / SLUG / "change-requests" / "2.decision.md"
    assert decision.read_text(encoding="utf-8") == "decided\n"


def test_refuses_and_keeps_decision_when_one_exists(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    writer = HubDecisionWriter()
    writer.create_decision(str(hub), slug=SLUG, n=2, text="first\n")

    with pytest.raises(FileExistsError):
        writer.create_decision(str(hub), slug=SLUG, n=2, text="second\n")

    decision = hub / "brain" / "features" / SLUG / "change-requests" / "2.decision.md"
    assert decision.read_text(encoding="utf-8") == "first\n"


@pytest.mark.parametrize("linked", ["feature", "change-requests"])
def test_refuses_when_folder_is_a_link(tmp_path: Path, linked: str) -> None:
    hub = _hub(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "change-requests").mkdir(parents=True)
    features = hub / "brain" / "features"
    slug = SLUG
    if linked == "feature":
        (features / "linked").symlink_to(elsewhere, target_is_directory=True)
        slug = "linked"
    else:
        (features / SLUG / "change-requests").rmdir()
        (features / SLUG / "change-requests").symlink_to(
            elsewhere / "change-requests", target_is_directory=True
        )

    with pytest.raises(FileNotFoundError):
        HubDecisionWriter().create_decision(str(hub), slug=slug, n=2, text="x")

    assert list((elsewhere / "change-requests").iterdir()) == []


def test_refuses_when_request_folder_missing(tmp_path: Path) -> None:
    hub = tmp_path / "demo-hub"
    (hub / "brain" / "features" / SLUG).mkdir(parents=True)

    with pytest.raises(FileNotFoundError):
        HubDecisionWriter().create_decision(str(hub), slug=SLUG, n=2, text="x")


@pytest.mark.parametrize(("slug", "n"), [("../demo", 2), (".hidden", 2), (SLUG, 0)])
def test_refuses_when_name_not_single(tmp_path: Path, slug: str, n: int) -> None:
    with pytest.raises(ValueError, match="invalid feature or change request"):
        HubDecisionWriter().create_decision(str(_hub(tmp_path)), slug=slug, n=n, text="x")
