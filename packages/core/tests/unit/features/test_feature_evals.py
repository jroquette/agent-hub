"""Evals per delivery and their aggregation per AC (AGH-136 S6, S7; AC-136.19-21)."""

import pytest

from agent_hub.core.features.feature_evals import (
    DELIVERY_PATTERN,
    LEGACY_DELIVERY,
    EvalCoverage,
    eval_coverage,
    eval_records,
)
from agent_hub.core.features.feature_record import PlannedTicket, RecordAc
from agent_hub.core.features.feature_status import RecordHead

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
            "demo-1520.md",
            type="eval",
            delivery="demo-1520",
            verdict="SHIP",
            tickets="[DEMO-1520]",
            acs="[AC-7.1, AC-7.2, AC-7.3]",
            prs="[demo-api#12]",
            commit="0a1b2c3",
            evaluated_at="2026-10-09",
        ),
        an_eval(
            "demo-1521.md",
            type="eval",
            delivery="demo-1521",
            verdict="NO-SHIP",
            tickets="[DEMO-1521]",
            acs="[AC-7.4, AC-7.5]",
            prs="[demo-api#13]",
            commit="1b2c3d4",
            evaluated_at="2026-10-10",
        ),
    )

    records = eval_records(heads, None, slug=SLUG)
    coverage = eval_coverage(records, acs_named(36))

    assert [(r.delivery, r.verdict, r.path) for r in records] == [
        ("demo-1520", "SHIP", "features/demo-feature/evals/demo-1520.md"),
        ("demo-1521", "NO-SHIP", "features/demo-feature/evals/demo-1521.md"),
    ]
    first = records[0]
    assert (first.tickets, first.acs, first.prs, first.commit, first.evaluated_at) == (
        ("DEMO-1520",),
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
        an_eval("demo-1520.md", verdict="SHIP", acs="[AC-7.1, AC-7.2]", evaluated_at="2026-10-09"),
        an_eval("demo-1521-r2.md", verdict="SHIP", acs="[AC-7.3]", evaluated_at="2026-10-11"),
        an_eval("demo-1521.md", verdict="NO-SHIP", acs="[AC-7.3]", evaluated_at="2026-10-11"),
        an_eval("feature.md", verdict="NO-SHIP", acs="[AC-7.2]", evaluated_at="2026-10-12"),
    )

    records = eval_records(heads, None, slug=SLUG)
    coverage = eval_coverage(records, acs_named(3))

    assert {r.delivery for r in records} == {"demo-1520", "demo-1521", "demo-1521-r2", "feature"}
    assert coverage == EvalCoverage(
        covered=("AC-7.1", "AC-7.3"),
        owner_steps=(),
        uncovered=("AC-7.2",),
        total=3,
        unscoped=False,
    )


def test_orders_by_date_before_rerun_when_dates_differ_latest_wins() -> None:
    heads = (
        an_eval("demo-1521.md", verdict="SHIP", acs="[AC-7.1]", evaluated_at="2026-10-12"),
        an_eval("demo-1521-r2.md", verdict="NO-SHIP", acs="[AC-7.1]", evaluated_at="2026-10-11"),
    )

    coverage = eval_coverage(eval_records(heads, None, slug=SLUG), acs_named(1))

    assert coverage.covered == ("AC-7.1",)


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
        an_eval("demo-1520.md", verdict="SHIP-WITH-OWNER-STEPS", tickets="[DEMO-1520]"),
        an_eval("t2.md", verdict="SHIP", tickets="[t2]"),
    )
    tickets = (PlannedTicket(key="T1", id="DEMO-1520"), PlannedTicket(key="T2"))
    acs = (
        an_ac("AC-7.1", ticket="T1"),
        an_ac("AC-7.2", ticket="DEMO-1520"),
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


@pytest.mark.parametrize("name", ["demo-1520", "pr-demo-api-12", "feature", "demo-1521-r2"])
def test_accepts_delivery_when_name_follows_pattern(name: str) -> None:
    assert DELIVERY_PATTERN.fullmatch(name)
