"""Evals per delivery and their aggregation per AC (AGH-136 S6, S7; AC-136.19-21)."""

import json

import pytest

from agent_hub.core.features.feature_evals import (
    DELIVERY_PATTERN,
    LEGACY_DELIVERY,
    NOTE_SUFFIX,
    EvalCoverage,
    eval_coverage,
    eval_records,
)
from agent_hub.core.features.feature_record import PlannedTicket, RecordAc
from agent_hub.core.features.feature_reviews import review_records
from agent_hub.core.features.feature_status import FeatureFolder, RecordHead, feature_detail

SLUG = "demo-feature"


def an_eval(name: str, **fields: str) -> RecordHead:
    lines = "".join(f"{key}: {value}\n" for key, value in fields.items())
    return RecordHead(name=name, head=f"---\n{lines}---\n# Eval\n".encode(), problem=None)


def an_ac(ac_id: str, *, passes: bool = False, **extra: object) -> RecordAc:
    return RecordAc.model_validate(
        {"id": ac_id, "description": "Given x, when y, then z", "passes": passes} | extra
    )


def acs_named(count: int, *, passes: bool = False) -> tuple[RecordAc, ...]:
    return tuple(an_ac(f"AC-7.{index}", passes=passes) for index in range(1, count + 1))


def test_lists_every_delivery_when_two_evals_present_aggregate() -> None:
    heads = (
        an_eval(
            "tip-1520.md",
            type="eval",
            delivery="tip-1520",
            verdict="SHIP",
            tickets="[TIP-1520]",
            acs="[AC-7.1, AC-7.2, AC-7.3]",
            prs="[demo-api#12]",
            commit="0a1b2c3",
            evaluated_at="2026-10-09",
        ),
        an_eval(
            "tip-1521.md",
            type="eval",
            delivery="tip-1521",
            verdict="NO-SHIP",
            tickets="[TIP-1521]",
            acs="[AC-7.4, AC-7.5]",
            prs="[demo-api#13]",
            commit="1b2c3d4",
            evaluated_at="2026-10-10",
        ),
    )

    records = eval_records(heads, None, slug=SLUG)
    coverage = eval_coverage(records, acs_named(36))

    assert [(r.delivery, r.verdict, r.path) for r in records] == [
        ("tip-1520", "SHIP", "features/demo-feature/evals/tip-1520.md"),
        ("tip-1521", "NO-SHIP", "features/demo-feature/evals/tip-1521.md"),
    ]
    first = records[0]
    assert (first.tickets, first.acs, first.prs, first.commit, first.evaluated_at) == (
        ("TIP-1520",),
        ("AC-7.1", "AC-7.2", "AC-7.3"),
        ("demo-api#12",),
        "0a1b2c3",
        "2026-10-09",
    )
    assert (first.legacy, first.problem) == (False, None)
    assert coverage.covered == ("AC-7.1", "AC-7.2", "AC-7.3")
    assert (len(coverage.covered), coverage.total) == (3, 36)
    assert "AC-7.4" in coverage.uncovered


def test_lets_latest_eval_decide_when_ac_reevaluated_latest_wins() -> None:
    heads = (
        an_eval("tip-1520.md", verdict="SHIP", acs="[AC-7.1, AC-7.2]", evaluated_at="2026-10-09"),
        an_eval("tip-1521-r2.md", verdict="SHIP", acs="[AC-7.3]", evaluated_at="2026-10-11"),
        an_eval("tip-1521.md", verdict="NO-SHIP", acs="[AC-7.3]", evaluated_at="2026-10-11"),
        an_eval("feature.md", verdict="NO-SHIP", acs="[AC-7.2]", evaluated_at="2026-10-12"),
    )

    records = eval_records(heads, None, slug=SLUG)
    coverage = eval_coverage(records, acs_named(3))

    assert {r.delivery for r in records} == {"tip-1520", "tip-1521", "tip-1521-r2", "feature"}
    assert coverage == EvalCoverage(
        covered=("AC-7.1", "AC-7.3"),
        owner_steps=(),
        uncovered=("AC-7.2",),
        total=3,
        unscoped=False,
    )


def test_orders_by_date_before_rerun_when_dates_differ_latest_wins() -> None:
    heads = (
        an_eval("tip-1521.md", verdict="SHIP", acs="[AC-7.1]", evaluated_at="2026-10-12"),
        an_eval("tip-1521-r2.md", verdict="NO-SHIP", acs="[AC-7.1]", evaluated_at="2026-10-11"),
    )

    coverage = eval_coverage(eval_records(heads, None, slug=SLUG), acs_named(1))

    assert coverage.covered == ("AC-7.1",)


def test_lets_undated_rerun_decide_when_bare_file_dated_latest_wins() -> None:
    heads = (
        an_eval("dem-1.md", verdict="SHIP", acs="[AC-1]", evaluated_at="2026-10-01T10:00:00Z"),
        an_eval("dem-1-r2.md", verdict="NO-SHIP", acs="[AC-1]"),
    )

    records = eval_records(heads, None, slug=SLUG)
    coverage = eval_coverage(records, (an_ac("AC-1"),))

    assert [r.delivery for r in records] == ["dem-1", "dem-1-r2"]
    assert (coverage.covered, coverage.uncovered) == ((), ("AC-1",))


@pytest.mark.parametrize(
    ("earlier", "later", "covered"),
    [("SHIP", "NO-SHIP", ()), ("NO-SHIP", "SHIP", ("AC-7.1",))],
)
def test_compares_instants_when_offsets_differ_latest_wins(
    earlier: str, later: str, covered: tuple[str, ...]
) -> None:
    # 10:00+02:00 is 08:00Z: earlier than 09:00Z, though it sorts later as text.
    heads = (
        an_eval("a.md", verdict=earlier, acs="all", evaluated_at="2026-10-01T10:00:00+02:00"),
        an_eval("b.md", verdict=later, acs="all", evaluated_at="2026-10-01T09:00:00Z"),
    )

    records = eval_records(heads, None, slug=SLUG)

    assert [r.delivery for r in records] == ["a", "b"]
    assert eval_coverage(records, acs_named(1)).covered == covered


def test_orders_by_rerun_suffix_when_dates_missing_latest_wins() -> None:
    heads = (
        an_eval("dem-1-r3.md", verdict="SHIP", acs="[AC-7.1]"),
        an_eval("dem-1-r2.md", verdict="NO-SHIP", acs="[AC-7.1]", evaluated_at="2026-10-11"),
        an_eval("dem-1.md", verdict="NO-SHIP", acs="[AC-7.1, AC-7.2]"),
        an_eval("dem-2-r2.md", verdict="SHIP", acs="[AC-7.2]"),
    )

    coverage = eval_coverage(eval_records(heads, None, slug=SLUG), acs_named(2))

    # dem-1-r3 is newer than dem-1-r2 and dem-1; dem-2-r2 and dem-1 have no order: not covered.
    assert (coverage.covered, coverage.uncovered) == (("AC-7.1",), ("AC-7.2",))


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        (("SHIP", None), ("NO-SHIP", "2026-10-01"), ((), ())),
        (("NO-SHIP", "2026-10-01"), ("SHIP", None), ((), ())),
        (("SHIP", None), ("SHIP", "2026-10-01"), (("AC-7.1",), ())),
        (("SHIP", None), ("SHIP-WITH-OWNER-STEPS", None), (("AC-7.1",), ("AC-7.1",))),
    ],
    ids=["ship-undated", "ship-dated-later-unknown", "both-ship", "owner-steps"],
)
def test_takes_conservative_verdict_when_no_order_known_latest_wins(
    first: tuple[str, str | None],
    second: tuple[str, str | None],
    expected: tuple[tuple[str, ...], tuple[str, ...]],
) -> None:
    heads = tuple(
        an_eval(
            name,
            verdict=verdict,
            acs="all",
            **({} if date is None else {"evaluated_at": date}),
        )
        for name, (verdict, date) in (("x.md", first), ("y.md", second))
    )

    coverage = eval_coverage(eval_records(heads, None, slug=SLUG), acs_named(1))

    assert (coverage.covered, coverage.owner_steps) == expected


def test_lets_undated_eval_beat_legacy_when_neither_dated_legacy() -> None:
    heads = (an_eval("feature.md", verdict="SHIP", acs="all"),)

    records = eval_records(heads, b"Verdict: NO-SHIP\n", slug=SLUG)
    coverage = eval_coverage(records, acs_named(2))

    assert [r.delivery for r in records] == [LEGACY_DELIVERY, "feature"]
    assert coverage.covered == ("AC-7.1", "AC-7.2")


def test_lists_records_oldest_first_when_dates_differ() -> None:
    heads = (
        an_eval("a.md", verdict="SHIP", acs="all", evaluated_at="2026-10-12T09:00:00Z"),
        an_eval("b.md", verdict="SHIP", acs="all", evaluated_at="2026-10-01"),
    )

    assert [r.delivery for r in eval_records(heads, None, slug=SLUG)] == ["b", "a"]


@pytest.mark.parametrize(
    ("head", "second_passes", "expected"),
    [
        (b"# Eval\n\nVerdict: SHIP\n", True, ((), ("AC-7.1", "AC-7.2"), False)),
        (b"# Eval\n\nVerdict: SHIP\n", False, ((), (), True)),
        (
            b"---\nacs: [AC-7.1]\n---\n# Eval\n**Verdict:** SHIP-WITH-OWNER-STEPS\n",
            False,
            (("AC-7.1",), ("AC-7.1",), False),
        ),
        (b"---\nacs: all\n---\nVerdict: SHIP\n", False, ("all", ("AC-7.1", "AC-7.2"), False)),
    ],
    ids=["unscoped-all-pass", "unscoped-some-fail", "scoped", "scoped-all"],
)
def test_applies_legacy_rule_when_only_eval_md_legacy(
    head: bytes,
    second_passes: bool,  # noqa: FBT001 - a parametrized case
    expected: tuple[tuple[str, ...] | str, tuple[str, ...], bool],
) -> None:
    records = eval_records((), head, slug=SLUG)
    acs = (an_ac("AC-7.1", passes=True), an_ac("AC-7.2", passes=second_passes))
    coverage = eval_coverage(records, acs)

    [record] = records
    assert (record.delivery, record.legacy, record.path) == (
        LEGACY_DELIVERY,
        True,
        "features/demo-feature/eval.md",
    )
    assert record.verdict in ("SHIP", "SHIP-WITH-OWNER-STEPS")
    assert (record.acs, coverage.covered, coverage.unscoped) == expected


def test_keeps_legacy_without_verdict_when_no_verdict_line_legacy() -> None:
    [record] = eval_records((), b"# Eval\n\nNot finished.\n", slug=SLUG)

    assert (record.verdict, record.problem) == (None, None)
    assert eval_coverage((record,), acs_named(1)).covered == ()


def test_lets_newer_eval_decide_when_legacy_undated_legacy() -> None:
    heads = (an_eval("feature.md", verdict="NO-SHIP", acs="all", evaluated_at="2026-10-12"),)

    records = eval_records(heads, b"Verdict: SHIP\n", slug=SLUG)
    coverage = eval_coverage(records, acs_named(2, passes=True))

    assert [r.delivery for r in records] == [LEGACY_DELIVERY, "feature"]
    assert coverage.covered == ()


@pytest.mark.parametrize(
    ("head", "problem"),
    [
        (b"---\nverdict: SHIP\nacs: all\n", "not closed"),
        (b"# Eval\n\nVerdict: SHIP\n", "no frontmatter"),
        (b"---\nverdict: MAYBE\nacs: all\n---\n", "verdict"),
        (b"---\nverdict: SHIP\n---\n", "scope"),
        (b"---\ntype: review\nverdict: SHIP\nacs: all\n---\n", "type"),
        (b"---\nverdict: SHIP\nacs: all\nevaluated_at: yesterday\n---\n", "evaluated_at"),
        (b"---\nverdict: SHIP\nacs: [AC 7 1]\n---\n", "acs"),
        (b"---\nverdict: SHIP\nacs: all\ndelivery: other\n---\n", "delivery"),
        (b"---\nverdict: [SHIP]\nacs: all\n---\n", "verdict"),
        (b"---\nverdict: SHIP\nacs: all\ncommit: [a, b]\n---\n", "commit"),
    ],
    ids=[
        "unclosed",
        "absent",
        "verdict",
        "no-scope",
        "type",
        "date",
        "ac-id",
        "delivery",
        "list-verdict",
        "list-commit",
    ],
)
def test_reports_problem_when_frontmatter_malformed(head: bytes, problem: str) -> None:
    [record] = eval_records(
        (RecordHead(name="dem-7.md", head=head, problem=None),), None, slug=SLUG
    )

    assert record.problem is not None
    assert problem in record.problem
    assert (record.delivery, record.verdict, record.acs, record.tickets) == ("dem-7", None, (), ())
    assert eval_coverage((record,), acs_named(1)).covered == ()


def test_reports_problem_when_head_unreadable_malformed() -> None:
    head = RecordHead(name="dem-7.md", head=None, problem="not a regular file")

    [record] = eval_records((head,), None, slug=SLUG)

    assert (record.delivery, record.problem) == ("dem-7", "not a regular file")


def test_reports_problem_when_file_name_not_a_delivery_malformed() -> None:
    [record] = eval_records((an_eval("Bad_Name.md", verdict="SHIP", acs="all"),), None, slug=SLUG)

    assert record.problem is not None
    assert "delivery" in record.problem


def test_maps_tickets_scope_when_acs_absent() -> None:
    heads = (
        an_eval("tip-1520.md", verdict="SHIP-WITH-OWNER-STEPS", tickets="[TIP-1520]"),
        an_eval("t2.md", verdict="SHIP", tickets="[t2]"),
    )
    tickets = (PlannedTicket(key="T1", id="TIP-1520"), PlannedTicket(key="T2"))
    acs = (
        an_ac("AC-7.1", ticket="T1"),
        an_ac("AC-7.2", ticket="TIP-1520"),
        an_ac("AC-7.3", ticket="T2"),
        an_ac("AC-7.4", ticket="T3"),
    )

    coverage = eval_coverage(eval_records(heads, None, slug=SLUG), acs, tickets=tickets)

    assert coverage.covered == ("AC-7.1", "AC-7.2", "AC-7.3")
    assert coverage.owner_steps == ("AC-7.1", "AC-7.2")
    assert coverage.uncovered == ("AC-7.4",)


def test_leaves_withdrawn_out_when_counting_coverage() -> None:
    heads = (an_eval("feature.md", verdict="SHIP", acs="[AC-7.1]"),)
    acs = (an_ac("AC-7.1"), an_ac("AC-7.2", withdrawn=True))

    coverage = eval_coverage(eval_records(heads, None, slug=SLUG), acs)

    assert (coverage.covered, coverage.uncovered, coverage.total) == (("AC-7.1",), (), 1)


def test_ignores_withdrawn_ac_when_legacy_rule_checks_passes() -> None:
    acs = (an_ac("AC-7.1", passes=True), an_ac("AC-7.2", withdrawn=True))

    coverage = eval_coverage(eval_records((), b"Verdict: SHIP\n", slug=SLUG), acs)

    assert (coverage.covered, coverage.unscoped) == (("AC-7.1",), False)


@pytest.mark.parametrize("name", ["tip-1520", "pr-demo-api-12", "feature", "tip-1521-r2"])
def test_accepts_delivery_when_name_follows_pattern(name: str) -> None:
    assert DELIVERY_PATTERN.fullmatch(name)


# AGH-139 AC-139.24: a folder's agent outputs (``evals/*.json``, ``reviews/<ticket>/*.json``)
# change no record, coverage, phase or skipped count. Core reads a folder as ``FeatureFolder``,
# whose heads are its ``evals/*.md`` and ``reviews/*.md`` only; ``folder_of`` builds it from a
# tree of files as the reader does.
LEGACY_TREE = {
    "evals/dem-1.md": b"---\ntype: eval\ndelivery: dem-1\nverdict: SHIP\nacs: [AC-7.1]\n---\n",
    "evals/dem-2.md": b"---\ntype: eval\ndelivery: dem-2\nverdict: NO-SHIP\nacs: [AC-7.2]\n---\n",
    "reviews/DEM-1.md": b"---\ntype: review\nticket: DEM-1\noutcome: approved\n---\n",
}
OUTPUTS_TREE = {
    "evals/dem-1.json": b'{"schema": "agent-hub/eval/1", "verdict": "NO-SHIP"}',
    "evals/dem-3.json": b"{}",
    "reviews/DEM-1/spec-r1.json": b'{"schema": "agent-hub/review/1", "verdict": "FAIL"}',
    "reviews/DEM-2/spec-r1.json": b"{}",
}


def folder_of(tree: dict[str, bytes]) -> FeatureFolder:
    """The folder as read: ``eval.md``, and the heads of the ``.md`` files of each record folder."""

    def heads(folder: str) -> tuple[RecordHead, ...]:
        return tuple(
            RecordHead(name=name.split("/")[1], head=tree[name], problem=None)
            for name in sorted(tree)
            if name.startswith(f"{folder}/") and name.count("/") == 1 and name.endswith(NOTE_SUFFIX)
        )

    acs = [{"id": ac.id, "description": ac.description, "passes": False} for ac in acs_named(3)]
    record = {"feature": SLUG, "linear": ["DEM-1"], "tickets": [{"key": "DEM-1"}], "acs": acs}
    return FeatureFolder(
        slug=SLUG,
        files=("spec.md", "plan.md", "features.json", "eval.md"),
        features_json=json.dumps(record).encode(),
        eval_head=b"**Verdict: SHIP.**\n",
        evals=heads("evals"),
        reviews=heads("reviews"),
        evals_skipped=1,
        reviews_skipped=1,
    )


def test_ignores_json_outputs_when_legacy_and_outputs_mixed() -> None:
    legacy = folder_of(LEGACY_TREE)
    mixed = folder_of(LEGACY_TREE | OUTPUTS_TREE)

    records = eval_records(mixed.evals, mixed.eval_head, slug=SLUG)

    assert records == eval_records(legacy.evals, legacy.eval_head, slug=SLUG)
    assert [record.delivery for record in records] == [LEGACY_DELIVERY, "dem-1", "dem-2"]
    assert eval_coverage(records, acs_named(3)) == eval_coverage(
        eval_records(legacy.evals, legacy.eval_head, slug=SLUG), acs_named(3)
    )
    assert review_records(mixed.reviews, slug=SLUG) == review_records(legacy.reviews, slug=SLUG)
    assert feature_detail(mixed, project="demo") == feature_detail(legacy, project="demo")
    assert (mixed.evals_skipped, mixed.reviews_skipped) == (1, 1)
