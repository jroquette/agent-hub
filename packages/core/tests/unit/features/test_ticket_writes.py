"""The ticket records a run writes (two-level-flows AC-2.2, AC-2.3, AC-2.7, AC-2.12): the texts,
each read back by the readers, earlier bytes and entries kept, refusals writing nothing."""

import hashlib
import json
from datetime import UTC, datetime

import pytest

from agent_hub.core.features.feature_record import RecordAc
from agent_hub.core.features.feature_status import RecordHead
from agent_hub.core.features.plan_version import plan_version
from agent_hub.core.features.ticket_records import (
    MAX_PREFLIGHT_BYTES,
    change_requests,
    preflight_record,
)
from agent_hub.core.features.ticket_writes import (
    MAX_REQUEST_BYTES,
    Blocker,
    TicketBrief,
    TicketRecordError,
    amended_plan,
    appended_brief,
    appended_preflight,
    change_request_text,
    cited_adrs,
    decision_text,
    named_paths,
    next_request,
    plan_ids,
    plan_section,
    ticket_acs,
)

AT = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)
PLAN = b"""# Plan

## Tickets

### DEM-8 core: the writer

Change `core/features/ticket_writes.py` and `cli/step_command.py:12`, per ADR 0040.

### DEM-9 web: the panel

Touch `apps/web/src/panel.tsx`.

## Amendments

- A1 (2026-10-19, Dana Owner): First change.
"""


def a_brief(**fields: object) -> TicketBrief:
    values: dict[str, object] = {
        "ticket": "DEM-8",
        "at": AT,
        "plan_version": 2,
        "acs": (RecordAc(id="AC-1.1", description="It writes.", passes=False),),
        "plan_section": "### DEM-8 core: the writer\n\nChange it.\n",
        "blockers": (Blocker(id="DEM-7", outcome_path=None, recorded_at=None),),
        "adrs": ("ADR 0040",),
        "commits": ("`4e1a9c2b7d10` 2026-10-20 feat: a change",),
        "commits_note": None,
    } | fields
    return TicketBrief(**values)  # type: ignore[arg-type]


def a_run(**fields: object) -> bytes:
    run: dict[str, object] = {
        "ran_at": "2026-10-21T09:30:00Z",
        "plan_version": 2,
        "commit": "4e1a9c2",
        "blockers_read": [],
        "input": "none",
        "input_text": None,
        "drift": "none",
        "local_notes": [],
        "change_request": None,
        "run_id": "implement-8",
    }
    return json.dumps(run | fields).encode()


def a_request(n: int = 1, **fields: object) -> bytes:
    values: dict[str, object] = {
        "n": n,
        "ticket": "DEM-8",
        "plan_from": 2,
        "affected": ("DEM-9",),
        "opened_at": AT,
        "run_id": "implement-8",
        "evidence": "The API moved.",
        "proposal": "Follow it.",
    } | fields
    return change_request_text(**values)  # type: ignore[arg-type]


def a_decision(n: int = 1, decision: str = "approved", **fields: object) -> bytes:
    values: dict[str, object] = {
        "n": n,
        "request": a_request(n),
        "decision": decision,
        "decided_by": "Dana Owner",
        "decided_at": AT,
        "note": "Go ahead.",
    } | fields
    return decision_text(**values)  # type: ignore[arg-type]


def heads(*files: tuple[str, bytes]) -> list[RecordHead]:
    return [RecordHead(name=name, head=content, problem=None) for name, content in files]


class TestBrief:
    def test_writes_version_one_with_its_fields_when_no_brief_exists(self) -> None:
        text, version = appended_brief(None, a_brief())

        assert version == 1
        body = text.decode()
        assert body.startswith("---\ntype: ticket-brief\nticket: DEM-8\n---\n")
        assert "## Brief v1 (2026-10-21T10:00:00+00:00)" in body
        fields = json.loads(body.split("```json\n", 1)[1].split("\n```", 1)[0])
        assert fields == {
            "plan_version": 2,
            "blockers": [{"id": "DEM-7", "outcome_path": None, "recorded_at": None}],
            "adrs": ["ADR 0040"],
        }
        for part in (
            "**AC-1.1** It writes.",
            "> ### DEM-8 core: the writer",
            "DEM-7: none recorded",
        ):
            assert part in body
        assert "feat: a change" in body

    def test_appends_a_new_version_keeping_every_earlier_byte_when_run_again(self) -> None:
        first, _ = appended_brief(None, a_brief())

        second, version = appended_brief(first, a_brief(plan_version=3, commits=()))

        assert version == 2
        assert second.startswith(first)
        assert b"## Brief v2 (" in second[len(first) :]
        assert b'"plan_version": 3' in second[len(first) :]

    def test_names_the_reason_when_no_commit_was_read(self) -> None:
        text, _ = appended_brief(None, a_brief(commits=(), commits_note="no file named"))

        assert "None read: no file named." in text.decode()

    @pytest.mark.parametrize("tail", [b"\n\n", b"\n  \n", b"x  "])
    def test_keeps_every_earlier_byte_when_the_brief_ends_in_blank_lines_or_spaces(
        self, tail: bytes
    ) -> None:
        first = appended_brief(None, a_brief())[0] + tail

        second, _ = appended_brief(first, a_brief())

        assert second.startswith(first)

    @pytest.mark.parametrize(
        "existing", [b"# Someone's notes\n", appended_brief(None, a_brief(ticket="DEM-9"))[0]]
    )
    def test_refuses_to_append_when_the_file_is_not_this_tickets_brief(
        self, existing: bytes
    ) -> None:
        with pytest.raises(TicketRecordError, match="not a ticket brief of DEM-8"):
            appended_brief(existing, a_brief())

    def test_counts_versions_only_from_its_own_headings_when_the_plan_quotes_one(self) -> None:
        first, _ = appended_brief(None, a_brief(plan_section="## Brief v9 (x)\n"))

        _, version = appended_brief(first, a_brief())

        assert version == 2


class TestPlanReads:
    def test_takes_each_section_whose_heading_names_the_ticket_when_reading_the_plan(
        self,
    ) -> None:
        section = plan_section(PLAN.decode(), ("dem-8", "S1-T1"))

        assert section.startswith("### DEM-8 core: the writer\n")
        assert "DEM-9" not in section
        assert plan_section(PLAN.decode(), ("DEM-80",)) == ""

    def test_takes_the_table_rows_whose_first_cell_names_a_plan_id_when_the_key_is_joined(
        self,
    ) -> None:
        plan = (
            "| Ticket | Boundary | ACs |\n|---|---|---|\n"
            "| S2-T3 | `core/a.py` | AC-2.7 |\n| S2-T30 | other | AC-2.9 |\n"
            "| S2-T4 | writers | AC-2.2, AC-2.3 |\n| S2-T3, S2-T4 | AGH-403 | `S2-T3-T4` |\n"
        )

        section = plan_section(plan, plan_ids("S2-T3-T4"))

        assert plan_ids("S2-T3-T4") == ("S2-T3-T4", "S2-T3", "S2-T4")
        assert plan_ids("T2") == ("T2",)
        assert plan_section("text | S2-T3 | x\n", ("S2-T3",)) == ""
        assert section == (
            "| S2-T3 | `core/a.py` | AC-2.7 |\n| S2-T4 | writers | AC-2.2, AC-2.3 |\n"
            "| S2-T3, S2-T4 | AGH-403 | `S2-T3-T4` |\n"
        )

    def test_lists_the_acs_keyed_to_the_ticket_or_named_in_its_section_when_read(self) -> None:
        acs = tuple(
            RecordAc(id=ident, description=ident, passes=False, ticket=ticket, withdrawn=gone)
            for ident, ticket, gone in (
                ("AC-2.1", None, False),
                ("AC-2.2", None, False),
                ("AC-2.3", "s2-t3-t4", False),
                ("AC-2.20", None, False),
                ("AC-2.7", "S2-T5", True),
            )
        )

        found = ticket_acs(acs, ("S2-T3-T4", "AGH-403"), "| S2-T4 | AC-2.2, AC-2.7 |\n")

        assert [ac.id for ac in found] == ["AC-2.2", "AC-2.3"]
        assert ticket_acs(acs[:2], ("S2-T4",), "| S2-T4 | AC-2.20 |\n") == ()

    def test_lists_the_paths_and_adrs_a_section_names_when_read(self) -> None:
        section = plan_section(PLAN.decode(), ("DEM-8",))

        assert named_paths(section) == ("core/features/ticket_writes.py", "cli/step_command.py")
        assert cited_adrs(section + "docs/adr/0032-engine.md and ADR-0040") == (
            "ADR 0032",
            "ADR 0040",
        )


class TestPreflight:
    def test_starts_the_record_with_the_folder_ticket_when_none_exists(self) -> None:
        written, count = appended_preflight(None, a_run(), folder="DEM-8")

        record = preflight_record(written, folder="DEM-8")
        assert count == 1
        assert not isinstance(record, str) and record is not None
        assert record.ticket == "DEM-8"

    def test_keeps_every_earlier_entry_equal_in_canonical_form_when_a_run_is_appended(
        self,
    ) -> None:
        hand_written = json.dumps(
            {
                "runs": [json.loads(a_run(ran_at="2026-10-20T09:30:00Z"))],
                "ticket": "dem-8",
                "schema": "agent-hub/preflight/1",
            },
        ).encode()

        written, count = appended_preflight(
            hand_written, a_run(drift="local", local_notes=["renamed"]), folder="DEM-8"
        )

        def canonical(entry: object) -> str:
            return json.dumps(entry, sort_keys=True, separators=(",", ":"))

        before, after = json.loads(hand_written)["runs"], json.loads(written)["runs"]
        assert count == 2
        assert json.loads(written)["ticket"] == "dem-8"
        assert [canonical(entry) for entry in after[:-1]] == [canonical(e) for e in before]
        assert after[-1]["drift"] == "local"

    @pytest.mark.parametrize(
        ("run", "message"),
        [
            (a_run(drift="plan"), "change_request is required when drift is plan"),
            (a_run(drift="local"), "local_notes needs at least one note"),
            (a_run(input="discovery"), "input_text is required"),
            (a_run(extra=1), "extra"),
            (b"[]", "must be a JSON object"),
        ],
    )
    def test_refuses_a_run_the_model_refuses_when_appending(self, run: bytes, message: str) -> None:
        with pytest.raises(TicketRecordError, match=message):
            appended_preflight(None, run, folder="DEM-8")

    @pytest.mark.parametrize(
        ("existing", "message"),
        [
            (b"{", "preflight.json could not be read"),
            (
                json.dumps(
                    {"schema": "agent-hub/preflight/1", "ticket": "DEM-9", "runs": []}
                ).encode(),
                "not the folder's ticket DEM-8",
            ),
        ],
    )
    def test_refuses_without_writing_when_the_record_is_malformed_or_names_another_ticket(
        self, existing: bytes, message: str
    ) -> None:
        with pytest.raises(TicketRecordError, match=message):
            appended_preflight(existing, a_run(), folder="DEM-8")

    def test_refuses_when_the_record_would_pass_its_read_cap(self) -> None:
        notes = ["n" * 1000] * 50
        written = None
        with pytest.raises(TicketRecordError, match=f"larger than {MAX_PREFLIGHT_BYTES}"):
            for _ in range(10):
                written, _ = appended_preflight(
                    written, a_run(drift="local", local_notes=notes), folder="DEM-8"
                )
        assert written is not None
        assert len(written) <= MAX_PREFLIGHT_BYTES


class TestChangeRequest:
    def test_writes_a_request_the_reader_reads_open_when_created(self) -> None:
        text = a_request(3, affected=("DEM-9", "DEM-10"))

        [request] = change_requests(heads(("3.md", text)), skipped=0).requests
        assert (request.n, request.ticket, request.status) == (3, "DEM-8", "open")
        assert (request.plan_to, request.affected, request.problem) == (
            3,
            ("DEM-9", "DEM-10"),
            None,
        )
        body = text.decode()
        assert "plan_from: 2\n" in body
        assert "opened_at: 2026-10-21T10:00:00+00:00\n" in body
        assert "run_id: implement-8\n" in body
        assert "## Evidence\n\nThe API moved.\n" in body
        assert "## Proposal\n\nFollow it.\n" in body

    @pytest.mark.parametrize(
        ("fields", "message"),
        [
            ({"ticket": "../x"}, "ticket"),
            ({"affected": ("not a key",)}, "affected"),
            ({"run_id": "R 1"}, "run id"),
            ({"evidence": " "}, "evidence"),
            ({"proposal": ""}, "proposal"),
        ],
    )
    def test_refuses_a_field_the_reader_could_not_read_when_created(
        self, fields: dict[str, object], message: str
    ) -> None:
        with pytest.raises(TicketRecordError, match=message):
            a_request(**fields)

    def test_refuses_a_request_when_its_text_would_pass_the_read_cap(self) -> None:
        with pytest.raises(TicketRecordError, match=f"larger than {MAX_REQUEST_BYTES} bytes"):
            a_request(evidence="e" * MAX_REQUEST_BYTES)

    def test_takes_the_next_free_number_when_requests_and_decisions_exist(self) -> None:
        assert next_request([]) == 1
        assert next_request(["1.md", "2.decision.md", "notes.txt", "10.md"]) == 11


class TestDecision:
    @pytest.mark.parametrize("decision", ["approved", "declined"])
    def test_writes_a_decision_the_reader_folds_into_the_status_when_decided(
        self, decision: str
    ) -> None:
        text = a_decision(decision=decision, note='Keep "v2"\nfor now')

        folded = change_requests(heads(("1.md", a_request()), ("1.decision.md", text)), skipped=0)
        assert folded.requests[0].status == decision
        body = text.decode()
        assert "decided_by: Dana Owner\n" in body
        assert 'note: "Keep \\"v2\\" for now"\n' in body
        assert body.endswith('Keep "v2"\nfor now\n')

    @pytest.mark.parametrize(
        ("who", "message"),
        [
            ("", "decided_by is missing"),
            ("  ", "decided_by is missing"),
            ("unknown", "names no person"),
            (" Unknown ", "names no person"),
        ],
    )
    def test_refuses_a_decision_when_it_names_no_person(self, who: str, message: str) -> None:
        with pytest.raises(TicketRecordError, match=message):
            a_decision(decided_by=who)

    @pytest.mark.parametrize("who", ["Dana (owner)", "Dana)"])
    def test_refuses_an_approval_when_its_approver_could_not_be_written_in_the_plan(
        self, who: str
    ) -> None:
        with pytest.raises(TicketRecordError, match="could not be written in an amendment"):
            a_decision(decided_by=who)
        assert b"decision: declined\n" in a_decision(decision="declined", decided_by=who)

    @pytest.mark.parametrize("note", [None, "", "  "])
    def test_refuses_a_decline_when_it_has_no_note(self, note: str | None) -> None:
        with pytest.raises(TicketRecordError, match="a declined change needs a note"):
            a_decision(decision="declined", note=note)

    @pytest.mark.parametrize("decision", ["approved\ndecision: declined", "maybe", "Approved"])
    def test_refuses_a_decision_when_it_is_not_exactly_approved_or_declined(
        self, decision: str
    ) -> None:
        with pytest.raises(TicketRecordError, match="the decision must be approved or declined"):
            a_decision(decision=decision, note="")

    def test_refuses_a_decision_when_its_text_would_pass_the_read_cap(self) -> None:
        with pytest.raises(TicketRecordError, match=f"larger than {MAX_REQUEST_BYTES} bytes"):
            a_decision(note="n" * MAX_REQUEST_BYTES)

    def test_takes_an_approval_when_it_has_no_note(self) -> None:
        assert b"decision: approved\n" in a_decision(note=None)

    def test_refuses_a_decision_when_the_reader_cannot_read_its_request(self) -> None:
        with pytest.raises(TicketRecordError, match="could not be read"):
            a_decision(request=b"---\ntype: change-request\n---\n")


class TestAmendment:
    def amend(
        self, plan: bytes, *, decision: bytes | None = None, summary: str = "Use v2."
    ) -> bytes:
        request = a_request(2)
        decided = a_decision(2) if decision is None else decision
        written, _ = amended_plan(plan, n=2, request=request, decision=decided, summary=summary)
        return written

    def test_appends_one_entry_keeping_every_earlier_byte_when_approved(self) -> None:
        prefix = hashlib.sha256(PLAN).hexdigest()

        written = self.amend(PLAN)

        assert hashlib.sha256(written[: len(PLAN)]).hexdigest() == prefix
        added = written[len(PLAN) :].decode()
        assert added == (
            "- A2 (2026-10-21, Dana Owner): Use v2. ([change request 2](change-requests/2.md))\n"
        )
        assert plan_version(written).version == 3

    @pytest.mark.parametrize("tail", [b"\n\n", b"\n \n\n", b"  "])
    def test_keeps_every_earlier_byte_when_the_plan_ends_in_blank_lines_or_spaces(
        self, tail: bytes
    ) -> None:
        plan = PLAN + tail
        prefix = hashlib.sha256(plan).hexdigest()

        written = self.amend(plan)

        assert hashlib.sha256(written[: len(plan)]).hexdigest() == prefix
        assert plan_version(written).version == 3

    def test_names_the_approver_on_one_line_when_it_spans_lines(self) -> None:
        decision = a_decision(2, decided_by="Dana\nSmith")

        written, _ = amended_plan(PLAN, n=2, request=a_request(2), decision=decision, summary="Go.")

        assert written[len(PLAN) :].startswith(b"- A2 (2026-10-21, Dana Smith): Go.")

    def test_takes_the_number_after_the_highest_when_the_ids_have_a_gap(self) -> None:
        plan = PLAN + b"- A3 (2026-10-20, Dana Owner): Third.\n"
        request = a_request(2, plan_from=3)
        decision = a_decision(2, request=request)

        _, ident = amended_plan(plan, n=2, request=request, decision=decision, summary="Go.")

        assert ident == "A4"

    def test_opens_an_amendments_heading_at_the_end_when_the_last_section_is_another(
        self,
    ) -> None:
        plan = b"# Plan\n\n## Amendments\n\n- A1 (2026-10-19, Dana Owner): One.\n\n## Notes\n\nx"

        written = self.amend(plan)

        assert written.startswith(plan)
        assert written[len(plan) :].decode().startswith("\n\n## Amendments\n\n- A2 (")
        assert plan_version(written).version == 3

    def test_returns_the_existing_entry_unchanged_when_the_request_was_already_amended(
        self,
    ) -> None:
        once = self.amend(PLAN)

        again, ident = amended_plan(
            once, n=2, request=a_request(2), decision=a_decision(2), summary="Other."
        )

        assert (again, ident) == (once, "A2")

    def test_refuses_when_the_plan_moved_since_the_request(self) -> None:
        with pytest.raises(TicketRecordError, match="plan.md is v1"):
            self.amend(b"# Plan\n")

    def test_refuses_when_the_request_is_not_approved(self) -> None:
        declined = a_decision(2, decision="declined", note="No.")

        with pytest.raises(TicketRecordError, match="is declined, not approved"):
            self.amend(PLAN, decision=declined)

    def test_refuses_when_the_entry_would_not_read_as_an_amendment(self) -> None:
        # A decision file written by hand: decision_text refuses this approver.
        odd = a_decision(2).replace(b"decided_by: Dana Owner", b'decided_by: "Dana (owner)"')

        with pytest.raises(TicketRecordError, match="would not read as A2"):
            self.amend(PLAN, decision=odd)
