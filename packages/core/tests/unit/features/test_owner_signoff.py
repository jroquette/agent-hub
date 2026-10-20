"""The owner signs off a feature's owner steps (playground)."""

import json
from datetime import UTC, datetime

import pytest

from agent_hub.core.features.feature_evals import eval_coverage, eval_records
from agent_hub.core.features.feature_record import record_from_bytes
from agent_hub.core.features.feature_status import FeatureFolder, RecordHead, feature_parts
from agent_hub.core.features.feature_view import GoldenStep
from agent_hub.core.features.owner_signoff import (
    OwnerSignOffError,
    SignOffOwnerSteps,
    signoff_name,
)
from agent_hub.core.features.ticket_snapshots import SnapshotRead
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.testing.read_model_builders import an_issue_summary
from agent_hub.core.testing.tracker_reader_fakes import SNAPSHOT_TIME
from agent_hub.core.tracker.tracker_reader import IssueState, TicketSnapshot

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
    return a_sign_off_of(folder)


def a_sign_off_of(folder: FeatureFolder) -> tuple[SignOffOwnerSteps, Writer]:
    writer = Writer()
    return SignOffOwnerSteps(Hubs(), Folders(folder), writer, clock=lambda: NOW), writer


# A feature whose two tickets are merged: only its Acceptance step can still wait.
PLANNED = json.dumps(
    {
        "tickets": [
            {"key": "T1", "id": "ACME-1520", "order": 1},
            {"key": "T2", "id": "ACME-1521", "order": 2},
        ],
        "acs": [
            {"id": "AC-7.1", "description": "d", "passes": True, "ticket": "T1"},
            {"id": "AC-7.2", "description": "d", "passes": False, "ticket": "T2"},
            {"id": "AC-7.3", "description": "d", "passes": False, "verification": "manual"},
        ],
    }
).encode()
DONE = IssueState(name="Done", type="completed")
MERGED = SnapshotRead(
    snapshot=TicketSnapshot(
        summaries=tuple(
            an_issue_summary(id=issue, state=DONE, blocks=(), blocked_by=())
            for issue in ("ACME-1520", "ACME-1521")
        ),
        missing=(),
        external=(),
    ),
    source="linear",
    stale=False,
    as_of=SNAPSHOT_TIME,
    failure=None,
    detail=None,
    http_status=None,
)


def a_head(name: str, verdict: str, *, scope: str, at: str) -> RecordHead:
    head = f"---\ntype: eval\nverdict: {verdict}\n{scope}\nevaluated_at: {at}\n---\n"
    return RecordHead(name=f"{name}.md", head=head.encode(), problem=None)


def a_planned_folder(*evals: RecordHead, eval_head: bytes | None = None) -> FeatureFolder:
    files = ("spec.md", "plan.md", "issues.md", "features.json")
    return FeatureFolder(
        slug=SLUG,
        files=(*files, "eval.md") if eval_head else files,
        features_json=PLANNED,
        evals=evals,
        eval_head=eval_head,
    )


def acceptance_of(folder: FeatureFolder) -> GoldenStep:
    steps = feature_parts(folder, MERGED).golden_path.steps
    return next(step for step in steps if step.name == "acceptance")


def signed(folder: FeatureFolder, writer: Writer) -> FeatureFolder:
    notes = tuple(
        RecordHead(name=name, head=text.encode(), problem=None)
        for name, text in writer.written.items()
    )
    return FeatureFolder(
        slug=folder.slug,
        files=folder.files,
        features_json=folder.features_json,
        evals=(*folder.evals, *notes),
        eval_head=folder.eval_head,
    )


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


def test_refuses_when_whole_feature_eval_says_no_ship() -> None:
    sign_off, writer = a_sign_off(an_eval("abc-1.md", "NO-SHIP"))

    with pytest.raises(OwnerSignOffError, match="no AC waits"):
        sign_off("demo", SLUG)
    assert writer.written == {}


# two-level-flows A3 (AGH-325 Q1): the writer signs off exactly what the Acceptance step counts.
def test_signs_off_counted_owner_steps_when_ticket_ship_follows_whole_feature_eval() -> None:
    whole = a_head("feature", "SHIP-WITH-OWNER-STEPS", scope="acs: all", at="2026-10-10")
    ticket = a_head("acme-1520", "SHIP", scope="acs: [AC-7.1, AC-7.2, AC-7.3]", at="2026-10-11")
    folder = a_planned_folder(whole, ticket)
    waiting = acceptance_of(folder)
    sign_off, writer = a_sign_off_of(folder)

    written = sign_off("demo", SLUG)

    assert waiting.meta == "Waiting on you: sign off 3 ACs"
    assert written.acs == ("AC-7.1", "AC-7.2", "AC-7.3")
    assert "the owner steps listed in feature are done" in writer.written["owner-signoff.md"]
    after = acceptance_of(signed(folder, writer))
    assert (after.state, after.meta) == ("done", "Owner steps signed off")


# two-level-flows A6: a legacy eval.md without scope is whole-feature, failing ACs and all.
def test_signs_off_every_ac_when_legacy_eval_without_scope_ships_with_owner_steps() -> None:
    legacy = b"# Eval\n\n**Verdict: SHIP-WITH-OWNER-STEPS.** One manual step left.\n"
    folder = a_planned_folder(eval_head=legacy)
    waiting = acceptance_of(folder)
    sign_off, writer = a_sign_off_of(folder)

    written = sign_off("demo", SLUG)

    assert waiting.meta == "Waiting on you: sign off 3 ACs"
    assert written.acs == ("AC-7.1", "AC-7.2", "AC-7.3")
    assert acceptance_of(signed(folder, writer)).state == "done"


# two-level-flows A3 (AGH-325 Q2): with no AC to list, the app has nothing to sign off.
def test_refuses_when_features_json_lists_no_live_ac() -> None:
    record = json.dumps({"acs": []}).encode()
    whole = an_eval("feature.md", "SHIP-WITH-OWNER-STEPS")
    folder = FeatureFolder(
        slug=SLUG, files=("features.json",), features_json=record, evals=(whole,)
    )
    sign_off, writer = a_sign_off_of(folder)

    with pytest.raises(OwnerSignOffError, match="lists no AC to sign off"):
        sign_off("demo", SLUG)
    assert writer.written == {}


def test_raises_not_found_when_feature_unknown() -> None:
    sign_off, _ = a_sign_off(an_eval("abc-1.md", "SHIP-WITH-OWNER-STEPS"))

    with pytest.raises(EntityNotFoundError):
        sign_off("other", SLUG)


def test_names_rerun_when_signoff_exists() -> None:
    assert signoff_name(("owner-signoff", "abc-1")) == "owner-signoff-r2"


# two-level-flows A9 (AGH-325 R2-Q1): a sign-off that would not rank newer than the acceptance
# eval would never turn Acceptance done, so it is refused and nothing is written.
@pytest.mark.parametrize(
    "dated",
    ["", "evaluated_at: 2026-10-18\n"],
    ids=["undated", "future-dated"],
)
def test_refuses_when_signoff_would_not_be_newer_than_acceptance_eval(dated: str) -> None:
    head = f"---\ntype: eval\nverdict: SHIP-WITH-OWNER-STEPS\nacs: all\n{dated}---\n"
    whole = RecordHead(name="feature.md", head=head.encode(), problem=None)
    sign_off, writer = a_sign_off(whole)

    with pytest.raises(OwnerSignOffError, match="would not be newer than feature"):
        sign_off("demo", SLUG)
    assert writer.written == {}


# two-level-flows A9 (AGH-325 R2-m2): an AC whose latest eval is NO-SHIP is not signed off over.
def test_refuses_naming_acs_when_their_latest_eval_is_no_ship() -> None:
    whole = a_head("feature", "SHIP-WITH-OWNER-STEPS", scope="acs: all", at="2026-10-10")
    reopened = a_head("acme-1521", "NO-SHIP", scope="acs: [AC-7.2, AC-7.3]", at="2026-10-11")
    sign_off, writer = a_sign_off_of(a_planned_folder(whole, reopened))

    with pytest.raises(OwnerSignOffError) as refused:
        sign_off("demo", SLUG)

    assert refused.value.reason == (
        "the latest eval of AC-7.2, AC-7.3 is NO-SHIP; fix or re-evaluate them first"
    )
    assert writer.written == {}


# two-level-flows A9 (AGH-325 R2-m3): more evals than were read is no ground to sign off.
def test_refuses_when_folder_holds_more_evals_than_were_read() -> None:
    folder = FeatureFolder(
        slug=SLUG,
        files=("features.json",),
        features_json=RECORD,
        evals=(an_eval("abc-1.md", "SHIP-WITH-OWNER-STEPS"),),
        evals_skipped=1,
    )
    sign_off, writer = a_sign_off_of(folder)

    with pytest.raises(OwnerSignOffError, match="not all were read"):
        sign_off("demo", SLUG)
    assert writer.written == {}
