"""The owner signs off a feature's owner steps (playground)."""

import json
from datetime import UTC, datetime

import pytest

from agent_hub.core.features.feature_evals import eval_coverage, eval_records
from agent_hub.core.features.feature_record import record_from_bytes
from agent_hub.core.features.feature_status import FeatureFolder, RecordHead
from agent_hub.core.features.owner_signoff import (
    OwnerSignOffError,
    SignOffOwnerSteps,
    signoff_name,
)
from agent_hub.core.readmodels.read_ports import EntityNotFoundError

SLUG = "demo-feature"
HUB = "/hubs/demo"
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
RECORD = json.dumps(
    {
        "acs": [
            {"id": "AC-7.1", "description": "Given x, when y, then z", "passes": True},
            {"id": "AC-7.2", "description": "Given x, when y, then z", "passes": True},
        ]
    }
).encode()


def an_eval(name: str, verdict: str) -> RecordHead:
    head = f"---\ntype: eval\nverdict: {verdict}\nacs: all\nevaluated_at: 2026-10-08\n---\n"
    return RecordHead(name=name, head=head.encode(), problem=None)


class Hubs:
    def hub_path_of(self, project: str) -> str:
        if project != "demo":
            raise EntityNotFoundError(entity="project", entity_id=project)
        return HUB


class Folders:
    def __init__(self, folder: FeatureFolder) -> None:
        self.folder = folder

    def feature_folder(self, hub_path: str, slug: str) -> FeatureFolder | None:
        return self.folder if (hub_path, slug) == (HUB, SLUG) else None


class Writer:
    def __init__(self) -> None:
        self.written: dict[str, str] = {}

    def create_eval(self, hub_path: str, *, slug: str, name: str, text: str) -> None:
        assert (hub_path, slug) == (HUB, SLUG)
        if name in self.written:
            raise FileExistsError(name)
        self.written[name] = text


def a_sign_off(*evals: RecordHead) -> tuple[SignOffOwnerSteps, Writer]:
    folder = FeatureFolder(slug=SLUG, files=("features.json",), features_json=RECORD, evals=evals)
    writer = Writer()
    return SignOffOwnerSteps(Hubs(), Folders(folder), writer, clock=lambda: NOW), writer


def test_writes_ship_eval_when_owner_steps_wait() -> None:
    sign_off, writer = a_sign_off(an_eval("abc-1.md", "SHIP-WITH-OWNER-STEPS"))

    written = sign_off("demo", SLUG)

    assert written.delivery == "owner-signoff"
    assert written.verdict == "SHIP"
    text = writer.written["owner-signoff.md"]
    heads = (RecordHead(name="owner-signoff.md", head=text.encode(), problem=None),)
    records = eval_records((an_eval("abc-1.md", "SHIP-WITH-OWNER-STEPS"), *heads), None, slug=SLUG)
    record = record_from_bytes(RECORD)
    assert not isinstance(record, str)
    coverage = eval_coverage(records, record.acs)
    assert coverage.owner_steps == ()
    assert coverage.covered == ("AC-7.1", "AC-7.2")


def test_refuses_when_no_owner_steps_wait() -> None:
    sign_off, writer = a_sign_off(an_eval("abc-1.md", "SHIP"))

    with pytest.raises(OwnerSignOffError, match="no AC waits"):
        sign_off("demo", SLUG)
    assert writer.written == {}


def test_refuses_when_an_ac_is_not_shipped() -> None:
    sign_off, _ = a_sign_off(an_eval("abc-1.md", "NO-SHIP"))

    with pytest.raises(OwnerSignOffError, match="not covered"):
        sign_off("demo", SLUG)


def test_raises_not_found_when_feature_unknown() -> None:
    sign_off, _ = a_sign_off(an_eval("abc-1.md", "SHIP-WITH-OWNER-STEPS"))

    with pytest.raises(EntityNotFoundError):
        sign_off("other", SLUG)


def test_names_rerun_when_signoff_exists() -> None:
    assert signoff_name(("owner-signoff", "abc-1")) == "owner-signoff-r2"


TICKETED = json.dumps(
    {
        "acs": [
            {"id": "AC-7.1", "description": "d", "passes": True, "ticket": "DEM-1"},
            {"id": "AC-7.2", "description": "d", "passes": True, "ticket": "DEM-2"},
        ]
    }
).encode()


def a_ticket_eval(name: str, verdict: str, ticket: str) -> RecordHead:
    head = (
        f"---\ntype: eval\nverdict: {verdict}\ntickets: [{ticket}]\nevaluated_at: 2026-10-08\n---\n"
    )
    return RecordHead(name=name, head=head.encode(), problem=None)


def a_ticket_sign_off(*evals: RecordHead) -> tuple[SignOffOwnerSteps, Writer]:
    folder = FeatureFolder(slug=SLUG, files=("features.json",), features_json=TICKETED, evals=evals)
    writer = Writer()
    return SignOffOwnerSteps(Hubs(), Folders(folder), writer, clock=lambda: NOW), writer


def test_settles_one_eval_when_rest_of_feature_uncovered() -> None:
    sign_off, writer = a_ticket_sign_off(
        a_ticket_eval("dem-1.md", "SHIP-WITH-OWNER-STEPS", "DEM-1")
    )

    written = sign_off("demo", SLUG, delivery="dem-1", note="Deployed the config by hand.")

    assert (written.verdict, written.acs, written.tickets) == ("SHIP", ("AC-7.1",), ("DEM-1",))
    text = writer.written["owner-signoff.md"]
    assert "tickets: [DEM-1]\n" in text
    assert "## Owner's note\n\nDeployed the config by hand.\n" in text


def test_writes_no_ship_when_owner_finds_more_work() -> None:
    source = a_ticket_eval("dem-1.md", "SHIP-WITH-OWNER-STEPS", "DEM-1")
    sign_off, writer = a_ticket_sign_off(source)

    written = sign_off("demo", SLUG, delivery="dem-1", decision="more_work")

    assert written.verdict == "NO-SHIP"
    text = writer.written["owner-signoff.md"]
    heads = (RecordHead(name="owner-signoff.md", head=text.encode(), problem=None),)
    record = record_from_bytes(TICKETED)
    assert not isinstance(record, str)
    coverage = eval_coverage(eval_records((source, *heads), None, slug=SLUG), record.acs)
    assert coverage.uncovered == ("AC-7.1", "AC-7.2")
    assert coverage.owner_steps == ()


def test_refuses_eval_when_not_owner_steps() -> None:
    sign_off, _ = a_ticket_sign_off(a_ticket_eval("dem-1.md", "SHIP", "DEM-1"))

    with pytest.raises(OwnerSignOffError, match="not a SHIP-WITH-OWNER-STEPS"):
        sign_off("demo", SLUG, delivery="dem-1")


def test_refuses_eval_when_unknown() -> None:
    sign_off, _ = a_ticket_sign_off(a_ticket_eval("dem-1.md", "SHIP-WITH-OWNER-STEPS", "DEM-1"))

    with pytest.raises(OwnerSignOffError, match="no eval dem-9"):
        sign_off("demo", SLUG, delivery="dem-9")


def test_refuses_eval_when_already_settled() -> None:
    sign_off, _ = a_ticket_sign_off(
        a_ticket_eval("dem-1.md", "SHIP-WITH-OWNER-STEPS", "DEM-1"),
        a_ticket_eval("dem-1-r2.md", "SHIP", "DEM-1"),
    )

    with pytest.raises(OwnerSignOffError, match="no AC of dem-1 waits"):
        sign_off("demo", SLUG, delivery="dem-1")


def test_refuses_more_work_when_no_eval_named() -> None:
    sign_off, _ = a_sign_off(an_eval("abc-1.md", "SHIP-WITH-OWNER-STEPS"))

    with pytest.raises(OwnerSignOffError, match="name the eval"):
        sign_off("demo", SLUG, decision="more_work")
