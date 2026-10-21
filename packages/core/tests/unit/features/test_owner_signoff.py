"""The owner signs off a feature's owner steps (playground)."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from agent_hub.core.features.feature_evals import eval_coverage, eval_records
from agent_hub.core.features.feature_record import record_from_bytes
from agent_hub.core.features.feature_status import (
    FeatureFolder,
    RecordHead,
    feature_detail,
    feature_parts,
)
from agent_hub.core.features.feature_view import GoldenStep
from agent_hub.core.features.owner_signoff import (
    OwnerDecision,
    OwnerSignOffError,
    SignOffOwnerSteps,
    signoff_name,
)
from agent_hub.core.features.ticket_snapshots import SnapshotRead
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.testing.read_model_builders import READ_TIME, an_issue_summary
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
    steps = feature_parts(folder, MERGED, now=READ_TIME).golden_path.steps
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

    assert waiting.meta == "Sign off 3 ACs"
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

    assert waiting.meta == "Sign off 3 ACs"
    assert written.acs == ("AC-7.1", "AC-7.2", "AC-7.3")
    assert acceptance_of(signed(folder, writer)).state == "done"


# two-level-flows A10: with no AC to list, the app has nothing to sign off.
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


# two-level-flows A9 (AGH-325 R3-Q1): the note keeps evaluated_at to the second, so a clock a
# fraction of a second past the acceptance eval would write a sign-off dated the same second.
def test_refuses_when_signoff_would_be_dated_the_same_second_as_acceptance_eval() -> None:
    whole = a_head("feature", "SHIP-WITH-OWNER-STEPS", scope="acs: all", at="2026-10-17T10:00:00Z")
    half_past = datetime(2026, 10, 17, 10, 0, 0, 500_000, tzinfo=UTC)
    writer = Writer()
    sign_off = SignOffOwnerSteps(
        Hubs(), Folders(a_planned_folder(whole)), writer, clock=lambda: half_past
    )

    with pytest.raises(OwnerSignOffError) as refused:
        sign_off("demo", SLUG)

    assert refused.value.reason == (
        "a sign-off would not be newer than feature: it has no evaluated_at, or one at or after now"
    )
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


# AGH-325 x AGH-384: settling the acceptance eval itself is the whole-feature sign-off (A9).
# A later agent ticket SHIP of T1 leaves AC-7.1 out of the scoped path's owner steps, while the
# Acceptance step still waits on it (only an owner SHIP signs one off): the A9 routing shows.
LATER_TICKET_SHIP = a_head("acme-1520", "SHIP", scope="tickets: [T1]", at="2026-10-11")


def test_signs_off_what_acceptance_waits_on_when_acceptance_eval_named() -> None:
    whole = a_head("feature", "SHIP-WITH-OWNER-STEPS", scope="acs: all", at="2026-10-10")
    sign_off, writer = a_sign_off_of(a_planned_folder(whole, LATER_TICKET_SHIP))

    written = sign_off("demo", SLUG, delivery="feature", note="Done by hand.")

    assert (written.verdict, written.acs, written.tickets) == (
        "SHIP",
        ("AC-7.1", "AC-7.2", "AC-7.3"),
        (),
    )
    assert "owner steps listed in feature are done" in writer.written["owner-signoff.md"]


def test_refuses_naming_reopened_acs_when_acceptance_eval_named() -> None:
    whole = a_head("feature", "SHIP-WITH-OWNER-STEPS", scope="acs: all", at="2026-10-10")
    reopened = a_head("acme-1521", "NO-SHIP", scope="acs: [AC-7.2]", at="2026-10-11")
    sign_off, writer = a_sign_off_of(a_planned_folder(whole, reopened))

    with pytest.raises(OwnerSignOffError) as refused:
        sign_off("demo", SLUG, delivery="feature")

    assert refused.value.reason == (
        "the latest eval of AC-7.2 is NO-SHIP; fix or re-evaluate them first"
    )
    assert writer.written == {}


def test_reopens_what_acceptance_waits_on_when_more_work_on_acceptance_eval() -> None:
    whole = a_head("feature", "SHIP-WITH-OWNER-STEPS", scope="acs: all", at="2026-10-10")
    sign_off, _ = a_sign_off_of(a_planned_folder(whole, LATER_TICKET_SHIP))

    written = sign_off("demo", SLUG, delivery="feature", decision="more_work")

    assert (written.verdict, written.acs) == ("NO-SHIP", ("AC-7.1", "AC-7.2", "AC-7.3"))


# A11: "more work" is not refused over ACs an agent's eval already reopened.
def test_reopens_every_waiting_ac_when_more_work_follows_agent_no_ship() -> None:
    whole = a_head("feature", "SHIP-WITH-OWNER-STEPS", scope="acs: all", at="2026-10-10")
    reopened = a_head("acme-1521", "NO-SHIP", scope="acs: [AC-7.2]", at="2026-10-11")
    sign_off, writer = a_sign_off_of(a_planned_folder(whole, reopened))

    written = sign_off("demo", SLUG, delivery="feature", decision="more_work")

    assert (written.verdict, written.acs) == ("NO-SHIP", ("AC-7.1", "AC-7.2", "AC-7.3"))
    assert "acs: [AC-7.1, AC-7.2, AC-7.3]\n" in writer.written["owner-signoff.md"]


def a_later_sign_off(folder: FeatureFolder, *, day: int = 18) -> tuple[SignOffOwnerSteps, Writer]:
    writer = Writer()
    later = datetime(2026, 10, day, 12, 0, tzinfo=UTC)
    return SignOffOwnerSteps(Hubs(), Folders(folder), writer, clock=lambda: later), writer


# A11: once an owner decision newer than the acceptance eval settled it, either decision on the
# acceptance eval is refused, writing nothing (the same request twice writes once).
@pytest.mark.parametrize(
    ("first", "reason"),
    [
        ("done", "the owner already signed off the owner steps of feature"),
        (
            "more_work",
            "AC-7.1, AC-7.2, AC-7.3 were reopened by an owner decision; "
            "an agent evaluates them again first",
        ),
    ],
)
@pytest.mark.parametrize("second", ["done", "more_work"])
def test_refuses_writing_nothing_when_owner_already_settled_acceptance_eval(
    first: OwnerDecision, reason: str, second: OwnerDecision
) -> None:
    whole = a_head("feature", "SHIP-WITH-OWNER-STEPS", scope="acs: all", at="2026-10-10")
    folder = a_planned_folder(whole)
    sign_off, writer = a_sign_off_of(folder)
    sign_off("demo", SLUG, delivery="feature", decision=first)
    again, rewriter = a_later_sign_off(signed(folder, writer))

    with pytest.raises(OwnerSignOffError) as refused:
        again("demo", SLUG, delivery="feature", decision=second)

    assert refused.value.reason == reason
    assert rewriter.written == {}


# A11: an owner NO-SHIP from settling a ticket eval also reopens what Acceptance waits on.
def test_refuses_writing_nothing_when_owner_more_work_on_ticket_eval_reopened_an_ac() -> None:
    whole = a_head("feature", "SHIP-WITH-OWNER-STEPS", scope="acs: all", at="2026-10-10")
    ticket = a_head("acme-1520", "SHIP-WITH-OWNER-STEPS", scope="tickets: [T1]", at="2026-10-11")
    folder = a_planned_folder(whole, ticket)
    sign_off, writer = a_sign_off_of(folder)
    sign_off("demo", SLUG, delivery="acme-1520", decision="more_work")
    again, rewriter = a_later_sign_off(signed(folder, writer))

    with pytest.raises(OwnerSignOffError) as refused:
        again("demo", SLUG, delivery="feature")

    assert refused.value.reason == (
        "AC-7.1 was reopened by an owner decision; an agent evaluates it again first"
    )
    assert rewriter.written == {}


@pytest.mark.parametrize(
    ("agent", "decision", "verdict"),
    [("SHIP", "done", "SHIP"), ("NO-SHIP", "more_work", "NO-SHIP")],
)
def test_decides_again_when_agent_evaluated_after_owner_more_work(
    agent: str, decision: OwnerDecision, verdict: str
) -> None:
    whole = a_head("feature", "SHIP-WITH-OWNER-STEPS", scope="acs: all", at="2026-10-10")
    folder = a_planned_folder(whole)
    sign_off, writer = a_sign_off_of(folder)
    sign_off("demo", SLUG, delivery="feature", decision="more_work")
    redone = a_head("acme-1522", agent, scope="acs: [AC-7.1, AC-7.2, AC-7.3]", at="2026-10-18")
    reevaluated = signed(folder, writer)
    again, rewriter = a_later_sign_off(
        FeatureFolder(
            slug=SLUG,
            files=reevaluated.files,
            features_json=PLANNED,
            evals=(*reevaluated.evals, redone),
        ),
        day=19,
    )

    written = again("demo", SLUG, delivery="feature", decision=decision)

    assert (written.verdict, written.acs) == (verdict, ("AC-7.1", "AC-7.2", "AC-7.3"))
    assert list(rewriter.written) == ["owner-signoff-r2.md"]


# A11: while an owner's NO-SHIP reopened ACs, Acceptance asks for a new evaluation, not a sign-off.
def test_reads_reopened_in_acceptance_when_owner_more_work_on_acceptance_eval() -> None:
    whole = a_head("feature", "SHIP-WITH-OWNER-STEPS", scope="acs: all", at="2026-10-10")
    folder = a_planned_folder(whole)
    sign_off, writer = a_sign_off_of(folder)
    sign_off("demo", SLUG, delivery="feature", decision="more_work")

    acceptance = acceptance_of(signed(folder, writer))

    assert (acceptance.state, acceptance.meta) == ("current", "3 ACs reopened · evaluate again")


def test_signs_off_only_the_rest_when_a_ticket_eval_was_settled() -> None:
    whole = a_head("feature", "SHIP-WITH-OWNER-STEPS", scope="acs: all", at="2026-10-10")
    ticket = a_head("acme-1520", "SHIP-WITH-OWNER-STEPS", scope="tickets: [T1]", at="2026-10-11")
    signed = a_head(
        "owner-signoff", "SHIP", scope="acs: [AC-7.1]\nprovenance: owner", at="2026-10-12"
    )
    sign_off, _ = a_sign_off_of(a_planned_folder(whole, ticket, signed))

    written = sign_off("demo", SLUG)

    assert written.acs == ("AC-7.2", "AC-7.3")
    assert written.delivery == "owner-signoff-r2"


_WHOLE = a_head("feature", "SHIP-WITH-OWNER-STEPS", scope="acs: all", at="2026-10-10")
_REOPENED = a_head("acme-1521", "NO-SHIP", scope="acs: [AC-7.2]", at="2026-10-12")
_MORE_WORK = a_head(
    "owner-signoff", "NO-SHIP", scope="acs: [AC-7.2]\nprovenance: owner", at="2026-10-13"
)
_UNDATED = RecordHead(
    name="feature.md",
    head=b"---\ntype: eval\nverdict: SHIP-WITH-OWNER-STEPS\nacs: all\n---\n",
    problem=None,
)
_FUTURE = a_head("feature", "SHIP-WITH-OWNER-STEPS", scope="acs: all", at="2026-11-21T09:00:30Z")
_NO_ACS = json.dumps(
    {"tickets": [{"key": "T1", "id": "ACME-1520", "order": 1}], "acs": []}
).encode()
_ALLOWS = {"done": ("sign_off",), "more_work": ("sign_off", "reopened")}


def _case(*evals: RecordHead, **fields: Any) -> FeatureFolder:
    return replace(a_planned_folder(*evals), **fields)


# two-level-flows A9-A11, A15 (AGH-330 Q10): the served wait offers exactly what the write accepts.
@pytest.mark.parametrize(
    ("folder", "state"),
    [
        (_case(_WHOLE), "sign_off"),
        (_case(_WHOLE, _REOPENED), "reopened"),
        (_case(_UNDATED, _REOPENED), "undated"),
        (_case(_FUTURE), "future"),
        (_case(_WHOLE, features_json=_NO_ACS), "no_acs"),
        (_case(_WHOLE, evals_skipped=3), None),
        (_case(_WHOLE, _REOPENED, _MORE_WORK), None),
    ],
    ids=["sign_off", "reopened", "undated", "future", "no_acs", "evals_skipped", "settled"],
)
@pytest.mark.parametrize("decision", ["done", "more_work"])
def test_offers_only_decisions_the_write_accepts_when_owner_wait_served(
    folder: FeatureFolder, state: str | None, decision: OwnerDecision
) -> None:
    detail = feature_detail(folder, project="demo", read=MERGED, now=NOW)
    assert detail.acceptance_eval is not None
    wait = detail.acceptance_eval.owner_wait
    sign_off, _ = a_sign_off_of(folder)

    try:
        sign_off("demo", SLUG, delivery="feature", decision=decision)
        accepted = True
    except OwnerSignOffError:
        accepted = False

    assert (None if wait is None else wait.state) == state
    assert accepted is (state in _ALLOWS[decision])


# AGH-330 Q3: the write dates its note to the second, so the read compares the same way.
def test_serves_future_wait_when_eval_dated_in_the_current_second() -> None:
    same_second = a_head(
        "feature", "SHIP-WITH-OWNER-STEPS", scope="acs: all", at="2026-10-17T12:00:00Z"
    )
    folder = a_planned_folder(same_second)

    detail = feature_detail(
        folder, project="demo", read=MERGED, now=NOW.replace(microsecond=500_000)
    )

    assert detail.acceptance_eval is not None
    assert detail.acceptance_eval.owner_wait is not None
    assert detail.acceptance_eval.owner_wait.state == "future"
