import json
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from agent_hub.core.doctor.feature_output_checks import MAX_VALIDATED_BYTES
from agent_hub.core.doctor.features_rule import FEATURES_TRACKER
from agent_hub.core.doctor.finding import Read
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.features import agent_outputs
from agent_hub.core.features.feature_evals import MAX_EVAL_FILES
from agent_hub.core.features.feature_record import MAX_RECORD_BYTES
from agent_hub.core.features.feature_reviews import MAX_REVIEW_FILES
from agent_hub.core.features.output_models import MAX_OUTPUT_BYTES
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.tree_snapshot import FileEntry, LinkEntry, TreeEntry
from agent_hub.core.testing.builders import a_hub_document

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[str | None, str, str]

RECORD = "brain/features/demo/features.json"
SPEC = "brain/features/demo/spec.md"
RECORD_FIX = "fix the record in features.json"
MASKED_FIX = "end the verification with the check itself, so a failure exits non-zero"
EVIDENCE_FIX = "record the command run and its result in evidence"
SPEC_FIX = "give spec.md and features.json the same AC ids"
JSON_FIX = "fix the JSON of the record"
LINK_FIX = "replace it with the file itself"
TEXT_FIX = "save it as UTF-8 text"
NOT_READ = "not read as a regular file (links are never followed)"
UNREAD = "could not be read"
UNREAD_FIX = "run hub doctor again"
# An id past Python's int-from-string digit limit (4300): the order must not convert it.
LONG_ID = "AC-" + "1" * 5000
LONG_ZERO_ID = "AC-" + "0" * 5000 + "3"
# Ids are echoed cut to 80 characters, ``…`` included.
LONG_SHOWN = "AC-" + "1" * 76 + "…"
LONG_ZERO_SHOWN = "AC-" + "0" * 76 + "…"
MASKED = "`verification` must keep its exit code (no trailing `echo $?`, `|| true` or `| tail`)"
REPOS = "repo must be one of api, demo-hub, web"
NEEDS_EVIDENCE = "passes=true needs evidence (command + result)"


def a_config() -> HubConfig:
    """The hub test's project (hub:tests/test_features_check.py): team TST, api, web, demo-hub."""
    document = a_hub_document()
    document["project"]["hub_repo"] = "acme/demo-hub"
    document["tracker"]["team"] = "TST"
    document["repos"] = [
        {"dir": name, "github": f"acme/{name}", "check_fast": "make f", "check": "make c"}
        for name in ("api", "web")
    ]
    document["guard"] = {}
    return HubConfig.model_validate(document)


def an_ac(number: int, **changes: object) -> dict[str, Any]:
    ac: dict[str, Any] = {
        "id": f"AC-{number}",
        "description": "Given x When y Then z",
        "repo": "api",
        "verification": f"pytest tests/unit/test_x.py::test_{number}",
        "passes": False,
        "evidence": None,
    }
    return ac | changes


def a_record(*acs: object, **changes: object) -> dict[str, Any]:
    return {"feature": "demo", "linear": ["TST-1"], "acs": list(acs)} | changes


def findings_of(snapshot: DoctorSnapshot) -> list[Shown]:
    found = list(FEATURES_TRACKER.check(snapshot))
    assert all(finding.rule == "features.tracker" for finding in found)
    assert all(finding.severity is Severity.ERROR for finding in found)
    assert all(finding.line is None for finding in found)
    return [(finding.path, finding.message, finding.fix) for finding in found]


def checked(
    snapshot_of: SnapshotFactory,
    record: object,
    *,
    spec: bytes | None = None,
    listed: tuple[str, ...] | None = None,
) -> list[Shown]:
    """The findings on one feature record, with its sibling spec when one is given."""
    files = {RECORD: json.dumps(record).encode()}
    if spec is not None:
        files[SPEC] = spec
    return findings_of(snapshot_of(config=a_config(), files=files, listed=listed))


def on_record(*messages: str, fix: str = RECORD_FIX) -> list[Shown]:
    return [(RECORD, message, fix) for message in messages]


def test_reads_listing_when_rule_declared() -> None:
    assert FEATURES_TRACKER.id == "features.tracker"
    assert FEATURES_TRACKER.reads == frozenset({Read.HUB_LISTING})
    assert FEATURES_TRACKER.severity is Severity.ERROR
    assert FEATURES_TRACKER.module is None


def test_accepts_record_when_valid(snapshot_of: SnapshotFactory) -> None:
    record = a_record(an_ac(1), an_ac(2, repo="web"), an_ac(3, repo="demo-hub"))

    assert checked(snapshot_of, record) == []


def test_reports_nothing_when_no_feature_listed(snapshot_of: SnapshotFactory) -> None:
    assert findings_of(snapshot_of(config=a_config())) == []


@pytest.mark.parametrize(
    "verification",
    [
        pytest.param("pytest tests/unit > t.log 2>&1; echo rc=$?", id="semicolon-echo"),
        pytest.param("make check; echo $?", id="bare-echo"),
        pytest.param("make check && echo rc=$? ", id="and-echo"),
        pytest.param("pytest tests/unit || true", id="or-true"),
        pytest.param("pytest tests/unit || :", id="or-colon"),
        pytest.param("pytest tests/unit | tail -5", id="tail"),
        pytest.param("pytest tests/unit | head", id="head"),
        pytest.param("pytest tests/unit | less", id="less"),
        pytest.param("pytest tests/unit | more -n 3", id="more"),
    ],
)
def test_rejects_masked_exit_code_when_ac_pending(
    snapshot_of: SnapshotFactory, verification: str
) -> None:
    record = a_record(an_ac(1, verification=verification))

    assert checked(snapshot_of, record) == on_record(f"AC-1: {MASKED}", fix=MASKED_FIX)


@pytest.mark.parametrize(
    "verification",
    [
        pytest.param("pytest tests/unit > t.log 2>&1", id="redirected"),
        pytest.param("echo $? && make check", id="echo-first"),
        pytest.param("make check || make lint", id="or-command"),
        pytest.param("make headless", id="pager-word-inside"),
        pytest.param("make check | tee log; test -s log", id="pipe-then-command"),
    ],
)
def test_accepts_exit_code_when_not_masked(snapshot_of: SnapshotFactory, verification: str) -> None:
    assert checked(snapshot_of, a_record(an_ac(1, verification=verification))) == []


def test_accepts_command_when_ac_passed(snapshot_of: SnapshotFactory) -> None:
    passed = an_ac(1, verification="make check; echo rc=$?", passes=True, evidence="rc=0")

    assert checked(snapshot_of, a_record(passed)) == []


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        pytest.param(None, on_record(f"AC-1: {NEEDS_EVIDENCE}", fix=EVIDENCE_FIX), id="null"),
        pytest.param("", on_record(f"AC-1: {NEEDS_EVIDENCE}", fix=EVIDENCE_FIX), id="empty"),
        pytest.param(" \t", on_record(f"AC-1: {NEEDS_EVIDENCE}", fix=EVIDENCE_FIX), id="blank"),
        pytest.param("exit 0: 1 passed", [], id="recorded"),
    ],
)
def test_requires_evidence_when_ac_passes(
    snapshot_of: SnapshotFactory, evidence: str | None, expected: list[Shown]
) -> None:
    record = a_record(an_ac(1, passes=True, evidence=evidence))

    assert checked(snapshot_of, record) == expected


@pytest.mark.parametrize(
    ("repo", "expected"),
    [
        pytest.param("demo-hub", [], id="last-segment"),
        pytest.param("acme/demo-hub", on_record(f"AC-1: {REPOS}"), id="whole-hub-repo"),
        pytest.param("acme", on_record(f"AC-1: {REPOS}"), id="owner"),
        pytest.param("demo", on_record(f"AC-1: {REPOS}"), id="project-name"),
    ],
)
def test_accepts_hub_repo_when_named_by_last_segment(
    snapshot_of: SnapshotFactory, repo: str, expected: list[Shown]
) -> None:
    assert checked(snapshot_of, a_record(an_ac(1, repo=repo))) == expected


def test_reports_duplicate_and_malformed_ids_when_listed(snapshot_of: SnapshotFactory) -> None:
    record = a_record(an_ac(1), an_ac(1), an_ac(3, id="R-3"), an_ac(4, id="R-3"))

    assert checked(snapshot_of, record) == on_record(
        "AC-1: duplicate id",
        "R-3: id must look like AC-<n>",
        "R-3: id must look like AC-<n>",
        # Ids are remembered even when malformed, as the old check does.
        "R-3: duplicate id",
    )


@pytest.mark.parametrize("bad", ["AC-1.", "AC-.1", "AC-1..2", "ac-1", "AC-1 ", "AC-x", "AC-"])
def test_reports_malformed_id_when_not_ac_number(snapshot_of: SnapshotFactory, bad: str) -> None:
    assert checked(snapshot_of, a_record(an_ac(1, id=bad))) == on_record(
        f"{bad}: id must look like AC-<n>"
    )


@pytest.mark.parametrize("good", ["AC-1", "AC-1.2", "AC-11.10.3", "AC-007"])
def test_accepts_id_when_ac_number_dotted_or_not(snapshot_of: SnapshotFactory, good: str) -> None:
    assert checked(snapshot_of, a_record(an_ac(1, id=good))) == []


@pytest.mark.parametrize("field", ["id", "description", "repo", "verification", "passes"])
def test_reports_missing_fields_and_bad_repo_when_ac_incomplete(
    snapshot_of: SnapshotFactory, field: str
) -> None:
    incomplete = an_ac(1, repo="other")
    del incomplete[field]
    kind = "be true or false" if field == "passes" else "be a non-empty string"
    # The AC is named by its index until its id is read, then by its id.
    where = "acs[0]" if field == "id" else "AC-1"
    bad_repo = [] if field == "repo" else [f"{where}: {REPOS}"]

    assert checked(snapshot_of, a_record(incomplete)) == on_record(
        f"acs[0]: `{field}` must {kind}", *bad_repo
    )


@pytest.mark.parametrize(
    ("linear", "expected"),
    [
        pytest.param(["ABC-9"], ["`linear` must be a list of TST-<n> ids"], id="other-team"),
        pytest.param("TST-1", ["`linear` must be a list of TST-<n> ids"], id="not-a-list"),
        pytest.param([1], ["`linear` must be a list of TST-<n> ids"], id="not-a-string"),
        pytest.param(["TST-"], ["`linear` must be a list of TST-<n> ids"], id="no-number"),
        pytest.param(["TST-1a"], ["`linear` must be a list of TST-<n> ids"], id="trailing"),
        pytest.param(["tst-1"], ["`linear` must be a list of TST-<n> ids"], id="lower-case"),
        pytest.param(["TST-1", "ABC-9"], ["`linear` must be a list of TST-<n> ids"], id="one-bad"),
        pytest.param(["TST-1", "TST-22"], [], id="team-ids"),
        pytest.param([], [], id="empty"),
    ],
)
def test_requires_team_prefix_when_linear_ids_given(
    snapshot_of: SnapshotFactory, linear: object, expected: list[str]
) -> None:
    record = a_record(an_ac(1), linear=linear)

    assert checked(snapshot_of, record) == on_record(*expected)


def a_teams_config(*teams: str) -> HubConfig:
    """``a_config()``'s project with ``tracker.teams`` set to ``teams`` instead of ``team``."""
    document = a_config().model_dump(mode="json", exclude_none=True)
    document["tracker"] = {"kind": "linear", "teams": list(teams)}
    return HubConfig.model_validate(document)


def linear_checked(snapshot_of: SnapshotFactory, linear: object, *teams: str) -> list[Shown]:
    """The findings on a record whose ``linear`` is ``linear``, on a hub listing ``teams``."""
    files = {RECORD: json.dumps(a_record(an_ac(1), linear=linear)).encode()}
    return findings_of(snapshot_of(config=a_teams_config(*teams), files=files))


def test_accepts_ids_of_every_team_when_hub_lists_teams(snapshot_of: SnapshotFactory) -> None:
    assert linear_checked(snapshot_of, ["APP-1", "OPS-2"], "APP", "OPS") == []


@pytest.mark.parametrize("linear", [["XYZ-1"], ["app-1"]])
def test_names_every_team_when_id_matches_none(
    snapshot_of: SnapshotFactory, linear: list[str]
) -> None:
    assert linear_checked(snapshot_of, linear, "APP", "OPS") == on_record(
        "`linear` must be a list of <TEAM>-<n> ids, <TEAM> one of APP, OPS"
    )


def test_accepts_ids_when_keys_share_prefix(snapshot_of: SnapshotFactory) -> None:
    assert linear_checked(snapshot_of, ["AP-1", "APP-2"], "AP", "APP") == []
    assert linear_checked(snapshot_of, ["APX-1"], "AP", "APP") == on_record(
        "`linear` must be a list of <TEAM>-<n> ids, <TEAM> one of AP, APP"
    )


def test_accepts_record_when_linear_absent(snapshot_of: SnapshotFactory) -> None:
    record = a_record(an_ac(1))
    del record["linear"]

    assert checked(snapshot_of, record) == []


@pytest.mark.parametrize(
    ("spec", "acs", "expected"),
    [
        pytest.param(
            b"- AC-1: Given ...\n- AC-2: Given ...\n- AC-10: Given ...\n",
            (an_ac(1), an_ac(3)),
            [
                "AC-2: in spec.md but not in features.json",
                "AC-10: in spec.md but not in features.json",
                "AC-3: in features.json but not in spec.md",
            ],
            id="numeric-order",
        ),
        # ``\\d`` takes any script's decimal digits; they order by their value.
        pytest.param(
            "- AC-1\n- AC-9\n- AC-\u0661\u0660\n- AC-\u0661.\u0662\n".encode(),
            (an_ac(1),),
            [
                "AC-\u0661.\u0662: in spec.md but not in features.json",
                "AC-9: in spec.md but not in features.json",
                "AC-\u0661\u0660: in spec.md but not in features.json",
            ],
            id="other-script-digits",
        ),
        pytest.param(
            b"- AC-1.1: Given ...\n- AC-1.2: Given ...\n- AC-1.10: Given ...\n",
            (an_ac(1, id="AC-1.1"), an_ac(3, id="AC-1.3")),
            [
                "AC-1.2: in spec.md but not in features.json",
                "AC-1.10: in spec.md but not in features.json",
                "AC-1.3: in features.json but not in spec.md",
            ],
            id="dotted",
        ),
        pytest.param(
            b"- AC-1.1\n- AC-1.2\n- AC-1.10\n",
            (an_ac(1, id="AC-1.1"), an_ac(2, id="AC-1.2"), an_ac(10, id="AC-1.10")),
            [],
            id="dotted-same",
        ),
        pytest.param(b"AC-1 only\r\n", (an_ac(1),), [], id="same"),
        pytest.param(
            b"AC-1 and AC-2\n",
            (an_ac(1),),
            ["AC-2: in spec.md but not in features.json"],
            id="spec-only",
        ),
        # A malformed id sorts first, then by its text: the order never depends on a set.
        pytest.param(
            b"AC-1\n",
            (an_ac(1), an_ac(2, id="R-2"), an_ac(3, id="Q-3")),
            [
                "R-2: id must look like AC-<n>",
                "Q-3: id must look like AC-<n>",
                "Q-3: in features.json but not in spec.md",
                "R-2: in features.json but not in spec.md",
            ],
            id="malformed-first",
        ),
    ],
)
def test_cross_checks_spec_when_sibling_present(
    snapshot_of: SnapshotFactory, spec: bytes, *, acs: tuple[object, ...], expected: list[str]
) -> None:
    findings = checked(snapshot_of, a_record(*acs), spec=spec)

    assert findings == [
        (RECORD, message, RECORD_FIX if "look like" in message else SPEC_FIX)
        for message in expected
    ]


def test_orders_long_id_when_spec_names_it(snapshot_of: SnapshotFactory) -> None:
    spec = f"- AC-1\n- {LONG_ID}\n- AC-2\n".encode()

    assert checked(snapshot_of, a_record(an_ac(1)), spec=spec) == [
        (RECORD, "AC-2: in spec.md but not in features.json", SPEC_FIX),
        (RECORD, f"{LONG_SHOWN}: in spec.md but not in features.json", SPEC_FIX),
    ]


def test_orders_long_ids_when_record_holds_them(snapshot_of: SnapshotFactory) -> None:
    # Leading zeros do not count: ``AC-00…03`` is 3, after 2 and before the 5000-digit id.
    record = a_record(an_ac(1), an_ac(5, id=LONG_ID), an_ac(3, id=LONG_ZERO_ID), an_ac(2))

    assert checked(snapshot_of, record, spec=b"AC-1\n") == [
        (RECORD, "AC-2: in features.json but not in spec.md", SPEC_FIX),
        (RECORD, f"{LONG_ZERO_SHOWN}: in features.json but not in spec.md", SPEC_FIX),
        (RECORD, f"{LONG_SHOWN}: in features.json but not in spec.md", SPEC_FIX),
    ]


def test_cuts_echoed_id_when_over_80_characters(snapshot_of: SnapshotFactory) -> None:
    long_bad = "R-" + "x" * 100
    record = a_record(an_ac(1, id=long_bad, repo="other"), an_ac(2, id=long_bad))
    shown = "R-" + "x" * 77 + "…"

    assert len(shown) == 80
    assert checked(snapshot_of, record) == on_record(
        f"{shown}: id must look like AC-<n>",
        f"{shown}: {REPOS}",
        f"{shown}: id must look like AC-<n>",
        f"{shown}: duplicate id",
    )


def test_skips_cross_check_when_spec_absent_or_unlisted(snapshot_of: SnapshotFactory) -> None:
    record = a_record(an_ac(1), an_ac(3))

    assert checked(snapshot_of, record) == []
    assert checked(snapshot_of, record, spec=b"AC-2\n", listed=(RECORD,)) == []


def test_accepts_placeholder_ids_when_spec_names_them(snapshot_of: SnapshotFactory) -> None:
    # A range yields its ends and a placeholder in prose counts (the hub's spec rule relies
    # on it); a number followed by ``.<digit>`` is no id.
    spec = b"Criteria AC-1..AC-3; AC-7 is cited in prose; version AC-9.1x and AC-5.2.\n"
    matching = a_record(an_ac(1), an_ac(3), an_ac(7), an_ac(51, id="AC-5.2"), an_ac(9, id="AC-9"))
    ranged = a_record(an_ac(1), an_ac(2), an_ac(3), an_ac(7), an_ac(51, id="AC-5.2"))

    assert checked(snapshot_of, matching, spec=spec) == [
        (RECORD, "AC-9: in features.json but not in spec.md", SPEC_FIX)
    ]
    assert checked(snapshot_of, ranged, spec=spec) == [
        (RECORD, "AC-2: in features.json but not in spec.md", SPEC_FIX)
    ]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        pytest.param(
            b"{not json",
            "$: not valid JSON: Expecting property name enclosed in double quotes"
            " at line 1 column 2",
            id="syntax",
        ),
        pytest.param(b"", "$: not valid JSON: Expecting value at line 1 column 1", id="empty"),
    ],
)
def test_reports_invalid_json_when_record_unparsable(
    snapshot_of: SnapshotFactory, content: bytes, message: str
) -> None:
    snapshot = snapshot_of(config=a_config(), files={RECORD: content, SPEC: b"AC-1\n"})

    assert findings_of(snapshot) == [(RECORD, message, JSON_FIX)]


def test_reads_record_leniently_when_json_repeats_key(snapshot_of: SnapshotFactory) -> None:
    # The old check used ``json.load``: the last of two keys wins, and NaN is a number.
    content = (
        b'{"feature": "", "feature": "demo", "linear": [], "acs": [{"id": "AC-1",'
        b' "description": "d", "repo": "api", "verification": "v", "passes": false,'
        b' "evidence": NaN}]}'
    )
    snapshot = snapshot_of(config=a_config(), files={RECORD: content})

    assert findings_of(snapshot) == on_record("AC-1: `evidence` must be null or a string")


def test_reports_not_utf8_when_record_undecodable(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(config=a_config(), files={RECORD: b'{"feature": "\xff"}'})

    assert findings_of(snapshot) == [
        (RECORD, "$: not UTF-8 text: byte 13 cannot be decoded", JSON_FIX)
    ]


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(LinkEntry(target="../other/features.json", outside=False), id="link"),
    ],
)
def test_reports_record_when_not_regular_file(
    snapshot_of: SnapshotFactory, entry: TreeEntry
) -> None:
    snapshot = snapshot_of(config=a_config(), entries={RECORD: entry})

    assert findings_of(snapshot) == [(RECORD, NOT_READ, LINK_FIX)]


def test_reports_record_when_regular_but_unread(snapshot_of: SnapshotFactory) -> None:
    # A regular file whose read failed is no link: it asks for another run.
    entry = FileEntry(executable=False, content=None)
    snapshot = snapshot_of(config=a_config(), entries={RECORD: entry})

    assert findings_of(snapshot) == [(RECORD, UNREAD, UNREAD_FIX)]


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        pytest.param(
            FileEntry(executable=False, content=b"AC-1 \xff AC-2\n"),
            (SPEC, "not UTF-8 text: byte 5 cannot be decoded", TEXT_FIX),
            id="not-utf8",
        ),
        pytest.param(
            LinkEntry(target="../other/spec.md", outside=False),
            (SPEC, NOT_READ, LINK_FIX),
            id="link",
        ),
        pytest.param(
            FileEntry(executable=False, content=None), (SPEC, UNREAD, UNREAD_FIX), id="unread"
        ),
    ],
)
def test_reports_spec_when_unreadable_or_not_utf8(
    snapshot_of: SnapshotFactory, entry: TreeEntry, expected: Shown
) -> None:
    # The record is still checked, without the cross-check.
    record = json.dumps(a_record(an_ac(1), an_ac(1, id="R-1"))).encode()
    snapshot = snapshot_of(config=a_config(), files={RECORD: record}, entries={SPEC: entry})

    assert findings_of(snapshot) == [expected, *on_record("R-1: id must look like AC-<n>")]


def test_reads_spec_when_it_holds_nul(snapshot_of: SnapshotFactory) -> None:
    # The old check read any UTF-8 text; a NUL does not stop the cross-check.
    assert checked(snapshot_of, a_record(an_ac(1)), spec=b"AC-1\x00 AC-2\n") == [
        (RECORD, "AC-2: in spec.md but not in features.json", SPEC_FIX)
    ]


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        pytest.param([an_ac(1)], ["top level must be an object"], id="top-level-not-object"),
        pytest.param(
            {"linear": [], "acs": [an_ac(1)]},
            ["`feature` must be a non-empty string"],
            id="feature-missing",
        ),
        pytest.param(
            a_record(an_ac(1), feature=""), ["`feature` must be a non-empty string"], id="empty"
        ),
        pytest.param(
            a_record(an_ac(1), feature=["demo"]),
            ["`feature` must be a non-empty string"],
            id="feature-not-string",
        ),
        # Only an empty name was refused: one of spaces passes, as before.
        pytest.param(a_record(an_ac(1), feature="  "), [], id="feature-blank"),
        pytest.param({"feature": "demo"}, ["`acs` must be a non-empty list"], id="acs-missing"),
        pytest.param(a_record(), ["`acs` must be a non-empty list"], id="acs-empty"),
        pytest.param(
            {"acs": {"AC-1": an_ac(1)}, "linear": ["X-1"]},
            [
                "`feature` must be a non-empty string",
                "`linear` must be a list of TST-<n> ids",
                "`acs` must be a non-empty list",
            ],
            id="acs-not-list-keeps-earlier",
        ),
        pytest.param(
            a_record(an_ac(1), "AC-2", None),
            ["acs[1]: must be an object", "acs[2]: must be an object"],
            id="ac-not-object",
        ),
        pytest.param(
            a_record(an_ac(1, evidence=1)),
            ["AC-1: `evidence` must be null or a string"],
            id="evidence-type",
        ),
        pytest.param(
            a_record(an_ac(1, passes=True, evidence=["ran"])),
            ["AC-1: `evidence` must be null or a string", f"AC-1: {NEEDS_EVIDENCE}"],
            id="evidence-type-when-passed",
        ),
        pytest.param(
            a_record(an_ac(1, passes="yes")),
            ["acs[0]: `passes` must be true or false"],
            id="passes-not-bool",
        ),
        pytest.param(
            a_record(an_ac(1, passes=1, verification="make check || true")),
            ["acs[0]: `passes` must be true or false"],
            id="passes-number-not-pending",
        ),
        pytest.param(
            a_record(an_ac(1, description=" \n")),
            ["acs[0]: `description` must be a non-empty string"],
            id="blank-string-field",
        ),
        pytest.param(
            a_record(an_ac(1, verification=7)),
            ["acs[0]: `verification` must be a non-empty string"],
            id="string-field-not-string",
        ),
        # ``\d`` also matches other scripts' digits, as the old pattern did.
        pytest.param(a_record(an_ac(1, id="AC-١.٢")), [], id="unicode-digit-id"),
    ],
)
def test_pins_old_outcome_when_untested_branch_hit(
    snapshot_of: SnapshotFactory, record: object, expected: list[str]
) -> None:
    findings = checked(snapshot_of, record)

    assert [(path, message) for path, message, _ in findings] == [
        (RECORD, message) for message in expected
    ]
    assert all(fix == RECORD_FIX for _, message, fix in findings if "evidence (" not in message)


def test_checks_every_feature_when_several_listed(snapshot_of: SnapshotFactory) -> None:
    valid = json.dumps(a_record(an_ac(1))).encode()
    invalid = json.dumps(a_record(an_ac(1), an_ac(2, repo="other"))).encode()
    snapshot = snapshot_of(
        config=a_config(),
        files={
            "brain/features/alpha/features.json": valid,
            "brain/features/alpha/spec.md": b"AC-1\n",
            "brain/features/beta/features.json": invalid,
            "brain/features/beta/spec.md": b"AC-1 AC-3\n",
            "brain/features/gamma/features.json": valid,
        },
    )

    assert findings_of(snapshot) == [
        ("brain/features/beta/features.json", f"AC-2: {REPOS}", RECORD_FIX),
        (
            "brain/features/beta/features.json",
            "AC-3: in spec.md but not in features.json",
            SPEC_FIX,
        ),
        (
            "brain/features/beta/features.json",
            "AC-2: in features.json but not in spec.md",
            SPEC_FIX,
        ),
    ]


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("brain/features/features.json", id="no-feature-folder"),
        pytest.param("brain/features/a/b/features.json", id="nested"),
        pytest.param("brain/features/.draft/features.json", id="hidden-folder"),
        pytest.param("brain/other/a/features.json", id="other-brain-folder"),
        pytest.param("docs/features/a/features.json", id="outside-brain"),
        pytest.param("brain/features/a/feature.json", id="other-name"),
        pytest.param("x/brain/features/a/features.json", id="deeper-root"),
    ],
)
def test_reads_only_feature_records_when_listing_searched(
    snapshot_of: SnapshotFactory, path: str
) -> None:
    files: Mapping[str, bytes] = {path: b"{not json", RECORD: b"{not json"}

    snapshot = snapshot_of(config=a_config(), files=files, listed=(path,))

    assert findings_of(snapshot) == []


# AGH-136: the ticket plan (``tickets``, AC ``ticket``), evals per delivery and withdrawn ACs.
TICKET_FIX = "name a key or id of `tickets` (or add that ticket)"
CYCLE_FIX = "remove one blocked_by edge of the cycle"
AC_TICKET_FIX = "name the ticket that delivers the AC: a key or id of `tickets`, or a `linear` id"
EVAL_FIX = "write the eval's frontmatter: type: eval, delivery, verdict, and acs or tickets"
EVAL_ACS_FIX = "name only AC ids of features.json in the eval's acs"
DELIVERY_FIX = "make `delivery` the file name; a re-run is a new file <delivery>-r2.md"
RENAME_FIX = "rename the eval to <delivery>.md: lower-case letters, digits and -"
EVALS = "brain/features/demo/evals"


def a_ticket(key: str, **changes: object) -> dict[str, Any]:
    return {"key": key, "id": None, "title": f"Ticket {key}", "repo": "api", "blocked_by": []} | (
        changes
    )


def a_planned_record(*tickets: object, **changes: object) -> dict[str, Any]:
    acs = [an_ac(1, ticket="T1"), an_ac(2, ticket="T2")]
    return a_record(*acs, tickets=list(tickets)) | changes


def shown_with_level(snapshot: DoctorSnapshot) -> list[tuple[Severity, str | None, str, str]]:
    found = list(FEATURES_TRACKER.check(snapshot))
    return [(finding.severity, finding.path, finding.message, finding.fix) for finding in found]


def test_accepts_tickets_when_plan_well_formed(snapshot_of: SnapshotFactory) -> None:
    record = a_planned_record(
        a_ticket("T1", id="TST-7", order=0),
        a_ticket("T2", blocked_by=["T1"], order=1),
        a_ticket("T3", blocked_by=["TST-7", "T2"], repo="web", title=None),
    )
    record["acs"].append(an_ac(3, ticket="TST-1"))

    assert checked(snapshot_of, record, spec=b"AC-1 AC-2 AC-3\n") == []


@pytest.mark.parametrize(
    ("tickets", "expected"),
    [
        pytest.param(
            [a_ticket("T1"), a_ticket("T2"), a_ticket("T1")],
            [("T1: duplicate key", RECORD_FIX)],
            id="duplicate-key",
        ),
        pytest.param(
            [a_ticket("T1"), a_ticket("T2", blocked_by=["T9"])],
            [("T2: blocked_by T9 is not a key or id of `tickets`", TICKET_FIX)],
            id="unknown-blocked-by",
        ),
        pytest.param(
            [a_ticket("T1", blocked_by=["T1"]), a_ticket("T2")],
            [("T1: blocked by itself", "remove it from blocked_by")],
            id="self",
        ),
        pytest.param(
            [a_ticket("T1"), a_ticket("T2"), a_ticket("1x")],
            [
                (
                    "tickets[2]: `key` must be a draft key such as T1 (a letter, then up to 31"
                    " letters, digits, - or _)",
                    RECORD_FIX,
                )
            ],
            id="malformed-key",
        ),
        pytest.param(
            [a_ticket("T1", id="tst-7"), a_ticket("T2")],
            [("T1: `id` must be null or a tracker id such as TST-12", RECORD_FIX)],
            id="malformed-id",
        ),
        pytest.param(
            [a_ticket("T1", title="x" * 201, repo="other"), a_ticket("T2", order=-1)],
            [
                ("T1: `title` must be null or at most 200 characters", RECORD_FIX),
                ("T1: repo must be one of api, demo-hub, web", RECORD_FIX),
                ("T2: `order` must be null or a whole number, 0 or more", RECORD_FIX),
            ],
            id="field-bounds",
        ),
        pytest.param(
            [a_ticket("T1", blocked_by=[f"T{n}" for n in range(51)]), a_ticket("T2")],
            [("T1: `blocked_by` must be a list of at most 50 keys or ids", RECORD_FIX)],
            id="too-many-blockers",
        ),
        pytest.param(
            [a_ticket("T1"), a_ticket("T2"), "T3"],
            [("tickets[2]: must be an object", RECORD_FIX)],
            id="not-object",
        ),
    ],
)
def test_reports_ticket_plan_when_tickets_malformed(
    snapshot_of: SnapshotFactory, tickets: list[object], expected: list[tuple[str, str]]
) -> None:
    findings = checked(snapshot_of, a_planned_record(*tickets))

    assert findings == [(RECORD, message, fix) for message, fix in expected]


def test_reports_tickets_when_not_a_list_or_over_cap(snapshot_of: SnapshotFactory) -> None:
    over = a_record(an_ac(1), tickets=[a_ticket(f"T{n}") for n in range(201)])
    not_list = a_record(an_ac(1), tickets={"T1": {}})
    message = "`tickets` must be a list of at most 200 tickets"

    assert checked(snapshot_of, over) == on_record(message)
    assert checked(snapshot_of, not_list) == on_record(message)


def test_reports_ac_ticket_when_not_in_tickets_or_linear(snapshot_of: SnapshotFactory) -> None:
    record = a_planned_record(a_ticket("T1"), a_ticket("T2"))
    record["acs"] += [an_ac(3, ticket="T7"), an_ac(4, ticket=3)]

    assert checked(snapshot_of, record) == [
        (RECORD, "AC-3: ticket T7 is not a key or id of `tickets` or `linear`", AC_TICKET_FIX),
        (RECORD, "AC-4: `ticket` must be null or a string", RECORD_FIX),
    ]


def test_accepts_ac_ticket_when_named_by_linear_without_tickets(
    snapshot_of: SnapshotFactory,
) -> None:
    # A record without a ticket plan parses as before; its AC may name a ``linear`` id.
    assert checked(snapshot_of, a_record(an_ac(1, ticket="TST-1"))) == []


def test_warns_cycle_when_tickets_block_each_other(snapshot_of: SnapshotFactory) -> None:
    record = a_planned_record(
        a_ticket("T1", blocked_by=["T3"]),
        a_ticket("T2", id="TST-8", blocked_by=["T1"]),
        a_ticket("T3", blocked_by=["TST-8"]),
        a_ticket("T4", blocked_by=["T1"]),
    )
    files = {RECORD: json.dumps(record).encode()}

    assert shown_with_level(snapshot_of(config=a_config(), files=files)) == [
        (Severity.WARNING, RECORD, "T1, T2, T3: a cycle of blocked_by", CYCLE_FIX)
    ]


def an_eval(**fields: str) -> bytes:
    lines = "".join(f"{name}: {value}\n" for name, value in fields.items())
    return f"---\n{lines}---\n# Eval\n".encode()


def a_good_eval(delivery: str = "tst-7", **changes: str) -> bytes:
    fields = {"type": "eval", "delivery": delivery, "verdict": "SHIP", "acs": "[AC-1, AC-2]"}
    return an_eval(**(fields | changes))


def evals_checked(snapshot_of: SnapshotFactory, evals: Mapping[str, bytes]) -> list[Shown]:
    files = {RECORD: json.dumps(a_record(an_ac(1), an_ac(2))).encode()} | {
        f"{EVALS}/{name}": content for name, content in evals.items()
    }
    return findings_of(snapshot_of(config=a_config(), files=files))


def test_accepts_evals_when_scope_recorded(snapshot_of: SnapshotFactory) -> None:
    evals = {
        "tst-7.md": a_good_eval(),
        "tst-7-r2.md": a_good_eval("tst-7-r2", verdict="NO-SHIP", acs="all"),
        "feature.md": a_good_eval(
            "feature", verdict="SHIP-WITH-OWNER-STEPS", tickets="[TST-1]"
        ).replace(b"acs: [AC-1, AC-2]\n", b""),
        ".draft.md": b"not an eval",
        "notes.txt": b"not an eval",
    }

    assert evals_checked(snapshot_of, evals) == []


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        pytest.param(
            an_eval(type="eval", delivery="tst-7", acs="[AC-1]"),
            ("`verdict` must be SHIP, SHIP-WITH-OWNER-STEPS or NO-SHIP", EVAL_FIX),
            id="no-verdict",
        ),
        pytest.param(
            a_good_eval(verdict="MAYBE"),
            ("`verdict` must be SHIP, SHIP-WITH-OWNER-STEPS or NO-SHIP", EVAL_FIX),
            id="bad-verdict",
        ),
        pytest.param(
            an_eval(type="eval", delivery="tst-7", verdict="SHIP"),
            ("no scope: give `acs` (a list of AC ids, or all) or `tickets`", EVAL_FIX),
            id="no-scope",
        ),
        pytest.param(
            a_good_eval(acs="[AC-1, AC-9]"),
            ("AC-9: in the eval's acs but not in features.json", EVAL_ACS_FIX),
            id="unknown-ac",
        ),
        pytest.param(
            a_good_eval(acs="some"),
            ("`acs` must be a list of AC ids, or all", EVAL_FIX),
            id="bad-acs",
        ),
        pytest.param(
            a_good_eval(tickets="TST-1"),
            ("`tickets` must be a list of ticket keys or ids", EVAL_FIX),
            id="bad-tickets",
        ),
        pytest.param(
            a_good_eval("tst-8"),
            ("`delivery` must be the file name, tst-7", DELIVERY_FIX),
            id="delivery-differs",
        ),
        pytest.param(
            b"# Eval\nVerdict: SHIP\n",
            ("no frontmatter: an eval starts with a --- block", EVAL_FIX),
            id="no-frontmatter",
        ),
        pytest.param(
            b"---\nverdict SHIP\n---\n",
            ("frontmatter: Line 2 of the frontmatter is not 'key: value'", EVAL_FIX),
            id="malformed-frontmatter",
        ),
        pytest.param(
            b"---\nverdict: SHIP \xff\n---\n",
            ("not UTF-8 text: byte 18 cannot be decoded", TEXT_FIX),
            id="not-utf8",
        ),
    ],
)
def test_reports_evals_when_frontmatter_invalid(
    snapshot_of: SnapshotFactory, content: bytes, expected: tuple[str, str]
) -> None:
    message, fix = expected

    assert evals_checked(snapshot_of, {"tst-7.md": content}) == [
        (f"{EVALS}/tst-7.md", message, fix)
    ]


def test_reports_eval_when_file_name_not_a_delivery(snapshot_of: SnapshotFactory) -> None:
    findings = evals_checked(snapshot_of, {"TST 7.md": a_good_eval("TST 7")})

    assert findings == [(f"{EVALS}/TST 7.md", "the file name is not a delivery name", RENAME_FIX)]


def test_reports_eval_when_link_or_unread(snapshot_of: SnapshotFactory) -> None:
    record = json.dumps(a_record(an_ac(1))).encode()
    snapshot = snapshot_of(
        config=a_config(),
        files={RECORD: record},
        entries={
            f"{EVALS}/a.md": LinkEntry(target="../eval.md", outside=False),
            f"{EVALS}/b.md": FileEntry(executable=False, content=None),
        },
    )

    assert findings_of(snapshot) == [
        (f"{EVALS}/a.md", NOT_READ, LINK_FIX),
        (f"{EVALS}/b.md", UNREAD, UNREAD_FIX),
    ]


def test_checks_evals_without_ac_ids_when_record_invalid(snapshot_of: SnapshotFactory) -> None:
    files = {RECORD: b"{not json", f"{EVALS}/tst-7.md": a_good_eval(acs="[AC-9]")}

    findings = findings_of(snapshot_of(config=a_config(), files=files))

    assert [path for path, _, _ in findings] == [RECORD]


def test_accepts_withdrawn_ac_when_spec_amended(snapshot_of: SnapshotFactory) -> None:
    spec = (
        b"---\nstatus: approved\n---\n- AC-1: Given ...\n- AC-2: (withdrawn, A1)\n\n"
        b"## Amendments\n\n- A1 (2026-10-13, owner): AC-2 withdrawn.\n"
    )
    # A withdrawn AC keeps its old command: the pending-command check skips it.
    withdrawn = an_ac(2, withdrawn=True, verification="make check | tail -5")
    files = {
        RECORD: json.dumps(a_record(an_ac(1), withdrawn)).encode(),
        SPEC: spec,
        f"{EVALS}/feature.md": a_good_eval("feature"),
    }

    assert findings_of(snapshot_of(config=a_config(), files=files)) == []


def test_reports_withdrawn_ac_when_dropped_from_spec_or_not_bool(
    snapshot_of: SnapshotFactory,
) -> None:
    record = a_record(an_ac(1), an_ac(2, withdrawn=True), an_ac(3, withdrawn="yes"))

    assert checked(snapshot_of, record, spec=b"AC-1 AC-3\n") == [
        (RECORD, "AC-3: `withdrawn` must be true or false", RECORD_FIX),
        (RECORD, "AC-2: in features.json but not in spec.md", SPEC_FIX),
    ]


ISSUES = "brain/features/demo/issues.md"
NO_IDS = "issues.md exists but `linear` holds no tracker id, here or in spec.md"
NO_IDS_FIX = "write the created issue ids into features.json → linear"
SPEC_NO_IDS = b"---\nlinear: []\n---\n# Demo\n\n- AC-1: Given x\n"


def found_with_issues(
    snapshot_of: SnapshotFactory, record: dict[str, Any], *, spec: bytes | None = None
) -> list[tuple[Severity, str | None, str, str]]:
    """Every finding, with its level, on a feature folder that also lists ``issues.md``."""
    files = {RECORD: json.dumps(record).encode(), ISSUES: b"# Issues\n\n## T1: x\n"}
    if spec is not None:
        files[SPEC] = spec
    snapshot = snapshot_of(config=a_config(), files=files)
    return [
        (finding.severity, finding.path, finding.message, finding.fix)
        for finding in FEATURES_TRACKER.check(snapshot)
    ]


@pytest.mark.parametrize(
    "spec",
    [
        pytest.param(None, id="no-spec"),
        pytest.param(SPEC_NO_IDS, id="spec-linear-empty"),
        pytest.param(b"---\nprocess_size: bounded\n---\nAC-1\n", id="spec-linear-absent"),
        pytest.param(b"# Demo\n\nlinear: [TST-4]\n\nAC-1\n", id="spec-without-frontmatter"),
        pytest.param(b"---\nlinear: [<TEAM>-N]\n---\nAC-1\n", id="spec-placeholder"),
        pytest.param(b"---\nlinear: [OPS-4, tst-5]\n---\nAC-1\n", id="spec-other-team"),
        pytest.param(
            b"---\n" + b"x: y\n" * 13_200 + b"linear: [TST-4]\n---\nAC-1\n",
            id="spec-ids-past-head",
        ),
    ],
)
@pytest.mark.parametrize("absent", [False, True], ids=["linear-empty", "linear-absent"])
def test_warns_on_record_when_issues_drafted_without_ids(
    snapshot_of: SnapshotFactory, spec: bytes | None, *, absent: bool
) -> None:
    record = a_record(an_ac(1), linear=[])
    if absent:
        del record["linear"]

    assert found_with_issues(snapshot_of, record, spec=spec) == [
        (Severity.WARNING, RECORD, NO_IDS, NO_IDS_FIX)
    ]


@pytest.mark.parametrize(
    ("linear", "spec"),
    [
        pytest.param(["TST-1"], SPEC_NO_IDS, id="ids-in-record"),
        pytest.param([], b"---\nlinear: [TST-4, TST-5]\n---\nAC-1\n", id="ids-in-spec"),
        pytest.param([], b"---\nlinear: TST-4\n---\nAC-1\n", id="one-id-in-spec"),
    ],
)
def test_accepts_record_when_issue_ids_recorded(
    snapshot_of: SnapshotFactory, linear: list[str], spec: bytes
) -> None:
    record = a_record(an_ac(1), linear=linear)

    assert found_with_issues(snapshot_of, record, spec=spec) == []


# AGH-136 + AGH-143: a planned ticket's ``id`` is a recorded tracker id too; drafts are not.
def test_warns_on_record_unless_ticket_id_recorded_when_issues_drafted(
    snapshot_of: SnapshotFactory,
) -> None:
    drafts = a_planned_record(a_ticket("T1"), a_ticket("T2"), linear=[])
    created = a_planned_record(a_ticket("T1", id="TST-7"), a_ticket("T2"), linear=[])
    spec = b"---\nlinear: []\n---\nAC-1 AC-2\n"

    assert found_with_issues(snapshot_of, drafts, spec=spec) == [
        (Severity.WARNING, RECORD, NO_IDS, NO_IDS_FIX)
    ]
    assert found_with_issues(snapshot_of, created, spec=spec) == []


def test_accepts_empty_linear_when_no_issues_drafted(snapshot_of: SnapshotFactory) -> None:
    assert checked(snapshot_of, a_record(an_ac(1), linear=[]), spec=SPEC_NO_IDS) == []


def test_keeps_warning_when_record_has_other_errors(snapshot_of: SnapshotFactory) -> None:
    record = a_record(an_ac(1, repo="other"), linear=[])

    assert found_with_issues(snapshot_of, record) == [
        (Severity.ERROR, RECORD, f"AC-1: {REPOS}", RECORD_FIX),
        (Severity.WARNING, RECORD, NO_IDS, NO_IDS_FIX),
    ]


@pytest.mark.parametrize(
    ("record", "spec", "expected"),
    [
        pytest.param(
            a_record(an_ac(1), linear="TST-1"),
            None,
            [(RECORD, "`linear` must be a list of TST-<n> ids", RECORD_FIX)],
            id="linear-malformed",
        ),
        pytest.param(
            ["not", "an", "object"],
            None,
            [(RECORD, "top level must be an object", RECORD_FIX)],
            id="record-not-object",
        ),
        pytest.param(
            a_record(an_ac(1), linear=[]),
            b"\xff---\n",
            [(SPEC, "not UTF-8 text: byte 0 cannot be decoded", TEXT_FIX)],
            id="spec-unreadable",
        ),
    ],
)
def test_adds_no_warning_when_record_or_spec_already_fails(
    snapshot_of: SnapshotFactory, record: object, *, spec: bytes | None, expected: list[Shown]
) -> None:
    files = {RECORD: json.dumps(record).encode(), ISSUES: b"# Issues\n"}
    if spec is not None:
        files[SPEC] = spec

    assert findings_of(snapshot_of(config=a_config(), files=files)) == expected


# AGH-139 S9: the light check of agent outputs, warnings only, inside features.tracker.
REVIEWS = "brain/features/demo/reviews"
NO_EVAL_NOTE = "eval output without its record evals/<name>.md"
NO_EVAL_NOTE_FIX = "write the eval record beside it, or remove the output"
NO_REVIEW_NOTE = "review output without its ticket record reviews/<ticket>.md"
NO_REVIEW_NOTE_FIX = (
    "write reviews/<ticket>.md once the ticket's reviews pass, or remove the output"
)
SHIP_FIELDS = {"commit": "feb9c4c"}
# Eight outputs of the largest size fill the per-feature budget exactly (``MAX_VALIDATED_BYTES``).
BUDGET_OUTPUTS = 8

type Leveled = tuple[Severity, str | None, str, str]


def a_result_of(ac: str) -> dict[str, object]:
    return {"ac": ac, "command": "pytest", "exit_code": 0, "status": "pass", "summary": "Passes."}


def an_eval_output(delivery: str = "tst-7", **changes: object) -> bytes:
    """An eval output that agrees with ``a_good_eval(delivery, **SHIP_FIELDS)`` and the record."""
    document: dict[str, object] = {
        "schema": "agent-hub/eval/1",
        "delivery": delivery,
        "verdict": "SHIP",
        "commit": "feb9c4c",
        "tickets": [],
        "acs": ["AC-1", "AC-2"],
        "results": [a_result_of("AC-1"), a_result_of("AC-2")],
        "gates": [{"repo": "api", "name": "check", "exit_code": 0, "status": "pass"}],
        "red_on_parent": [],
        "owner_steps": [],
    }
    return json.dumps(document | changes).encode()


def a_review_output(ticket: str = "TST-7", **changes: object) -> bytes:
    document: dict[str, object] = {
        "schema": "agent-hub/review/1",
        "reviewer": "spec",
        "ticket": ticket,
        "task": "T1",
        "round": 1,
        "commit": "feb9c4c",
        "verdict": "PASS",
        "findings": [],
    }
    return json.dumps(document | changes).encode()


def an_eval_pair(delivery: str, output: bytes | None = None) -> dict[str, bytes]:
    """``evals/<delivery>.md`` and its ``.json``, both valid unless ``output`` replaces the JSON."""
    return {
        f"{EVALS}/{delivery}.md": a_good_eval(delivery, **SHIP_FIELDS),
        f"{EVALS}/{delivery}.json": an_eval_output(delivery) if output is None else output,
    }


def outputs_found(
    snapshot_of: SnapshotFactory,
    files: Mapping[str, bytes],
    *,
    entries: Mapping[str, TreeEntry] | None = None,
    record: bytes | None = None,
) -> list[Leveled]:
    """Every finding, with its level, on the demo feature folder holding ``files``."""
    default = json.dumps(a_record(an_ac(1), an_ac(2))).encode()
    all_files = {RECORD: default if record is None else record} | dict(files)
    return shown_with_level(snapshot_of(config=a_config(), files=all_files, entries=entries))


def eval_warning(name: str, message: str, fix: str) -> Leveled:
    return (Severity.WARNING, f"{EVALS}/{name}", message, fix)


def review_warning(name: str, message: str, fix: str) -> Leveled:
    return (Severity.WARNING, f"{REVIEWS}/{name}", message, fix)


def validate_fix(kind: str, path: str) -> str:
    return f"run ./hub validate-output {kind} {path}"


def counting(monkeypatch: pytest.MonkeyPatch, name: str) -> list[None]:
    """Count the calls the doctor makes to ``agent_outputs.<name>``: one per validated output."""
    calls: list[None] = []
    original = getattr(agent_outputs, name)

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls.append(None)
        return original(*args, **kwargs)

    monkeypatch.setattr(agent_outputs, name, counted)
    return calls


def test_passes_valid_outputs_when_records_present(snapshot_of: SnapshotFactory) -> None:
    files = {
        **an_eval_pair("tst-7"),
        **an_eval_pair("tst-7-r2"),
        f"{REVIEWS}/TST-7.md": b"---\nstatus: approved\n---\n",
        f"{REVIEWS}/TST-7/spec-r1.json": a_review_output(),
        f"{REVIEWS}/TST-7/quality-r2.json": a_review_output(reviewer="quality", round=2),
        f"{REVIEWS}/tst-8.md": b"# Review\n",
        f"{REVIEWS}/tst-8/spec-r1.json": a_review_output("TST-8"),
        f"{EVALS}/.draft.json": b"not an output",
        f"{EVALS}/notes.txt": b"not an output",
        f"{REVIEWS}/TST-7/.draft.json": b"not an output",
        f"{REVIEWS}/.hidden/spec-r1.json": b"not an output",
        f"{REVIEWS}/TST-7/notes.md": b"not an output",
    }

    assert outputs_found(snapshot_of, files) == []


def test_warns_on_eval_outputs_when_sibling_missing(snapshot_of: SnapshotFactory) -> None:
    # A lone output is not validated: its only warning is the missing record.
    files = {f"{EVALS}/abc-2.json": b"{}", f"{EVALS}/abc-4.json": an_eval_output("abc-4")}
    entries = {f"{EVALS}/abc-4.md": LinkEntry(target="../abc-4.md", outside=False)}

    assert outputs_found(snapshot_of, files, entries=entries) == [
        (Severity.ERROR, f"{EVALS}/abc-4.md", NOT_READ, LINK_FIX),
        eval_warning("abc-2.json", NO_EVAL_NOTE, NO_EVAL_NOTE_FIX),
        eval_warning("abc-4.json", NO_EVAL_NOTE, NO_EVAL_NOTE_FIX),
    ]


@pytest.mark.parametrize(
    ("output", "sibling", "message"),
    [
        pytest.param(
            an_eval_output("abc-3", verdict="MAYBE", colour=1),
            a_good_eval("abc-3", **SHIP_FIELDS),
            "invalid eval output: 2 problems, first: verdict: Input should be 'SHIP',"
            " 'SHIP-WITH-OWNER-STEPS' or 'NO-SHIP'",
            id="two-problems",
        ),
        # Valid without a record; the folder's features.json names AC-2 too.
        pytest.param(
            an_eval_output("abc-3", acs="all", results=[a_result_of("AC-1")]),
            a_good_eval("abc-3", acs="all", **SHIP_FIELDS),
            "invalid eval output: 1 problem, first: results: no result for AC-2,"
            " which the scope names",
            id="record-scope",
        ),
    ],
)
def test_warns_on_invalid_outputs_when_validation_fails(
    snapshot_of: SnapshotFactory, output: bytes, *, sibling: bytes, message: str
) -> None:
    files = {**an_eval_pair("abc-1"), f"{EVALS}/abc-3.md": sibling, f"{EVALS}/abc-3.json": output}

    assert outputs_found(snapshot_of, files) == [
        eval_warning("abc-3.json", message, validate_fix("eval", f"{EVALS}/abc-3.json"))
    ]


def test_warns_on_review_outputs_when_record_missing(snapshot_of: SnapshotFactory) -> None:
    files = {
        f"{REVIEWS}/TST-7/spec-r1.json": b"{}",
        f"{REVIEWS}/TST-8/spec-r1.json": a_review_output("TST-8"),
    }
    entries = {f"{REVIEWS}/TST-8.md": LinkEntry(target="../TST-8.md", outside=False)}

    assert outputs_found(snapshot_of, files, entries=entries) == [
        review_warning("TST-7/spec-r1.json", NO_REVIEW_NOTE, NO_REVIEW_NOTE_FIX),
        review_warning("TST-8/spec-r1.json", NO_REVIEW_NOTE, NO_REVIEW_NOTE_FIX),
    ]


def test_warns_on_invalid_review_outputs_when_validation_fails(
    snapshot_of: SnapshotFactory,
) -> None:
    path = f"{REVIEWS}/TST-8/quality-r1.json"
    files = {
        f"{REVIEWS}/TST-8.md": b"# Review\n",
        path: a_review_output(reviewer="quality", verdict="FAIL"),
    }

    assert outputs_found(snapshot_of, files) == [
        review_warning(
            "TST-8/quality-r1.json",
            "invalid review output: 2 problems, first: ticket: the ticket is TST-7 but the"
            " folder is TST-8",
            validate_fix("review", path),
        )
    ]


def test_skips_outputs_when_folder_has_no_record(snapshot_of: SnapshotFactory) -> None:
    other = "brain/features/other"
    files = {
        f"{other}/reviews/TST-9/spec-r1.json": b"{}",
        f"{other}/evals/abc-1.json": b"{}",
        f"{other}/evals/abc-2.md": b"not an eval",
        f"{other}/evals/abc-2.json": b"{}",
    }

    assert outputs_found(snapshot_of, files) == []


def test_warns_when_outputs_not_regular(snapshot_of: SnapshotFactory) -> None:
    files = {
        f"{EVALS}/abc-1.md": a_good_eval("abc-1", **SHIP_FIELDS),
        f"{REVIEWS}/TST-7.md": b"# Review\n",
    }
    entries: dict[str, TreeEntry] = {
        f"{EVALS}/abc-1.json": LinkEntry(target="../abc-1.json", outside=False),
        f"{REVIEWS}/TST-7/spec-r1.json": FileEntry(executable=False, content=None),
    }

    assert outputs_found(snapshot_of, files, entries=entries) == [
        eval_warning("abc-1.json", NOT_READ, LINK_FIX),
        review_warning("TST-7/spec-r1.json", UNREAD, UNREAD_FIX),
    ]


def test_warns_once_when_outputs_over_bound(snapshot_of: SnapshotFactory) -> None:
    oversize = b" " * (MAX_OUTPUT_BYTES + 1)
    files = {
        **an_eval_pair("abc-1", oversize),
        f"{REVIEWS}/TST-7.md": b"# Review\n",
        f"{REVIEWS}/TST-7/spec-r1.json": oversize,
    }

    assert outputs_found(snapshot_of, files) == [
        eval_warning(
            "abc-1.json",
            "invalid eval output: 1 problem, first: $: the file is over 524288 bytes",
            validate_fix("eval", f"{EVALS}/abc-1.json"),
        ),
        review_warning(
            "TST-7/spec-r1.json",
            "invalid review output: 1 problem, first: $: the file is over 524288 bytes",
            validate_fix("review", f"{REVIEWS}/TST-7/spec-r1.json"),
        ),
    ]


def test_warns_once_on_eval_outputs_when_record_over_bound(snapshot_of: SnapshotFactory) -> None:
    record = json.dumps(a_record(an_ac(1), an_ac(2))).encode().ljust(MAX_RECORD_BYTES + 1)

    assert outputs_found(snapshot_of, an_eval_pair("abc-1"), record=record) == [
        eval_warning(
            "abc-1.json",
            "invalid eval output: 1 problem, first: $: features.json is over 1048576 bytes",
            validate_fix("eval", f"{EVALS}/abc-1.json"),
        )
    ]


def many_eval_outputs(count: int) -> dict[str, bytes]:
    return {
        path: content
        for index in range(count)
        for path, content in an_eval_pair(f"e-{index:03}", b"{}").items()
    }


def many_review_outputs(count: int) -> dict[str, bytes]:
    outputs = {f"{REVIEWS}/TST-7/spec-r{index}.json": b"{}" for index in range(1, count + 1)}
    return {f"{REVIEWS}/TST-7.md": b"# Review\n", **outputs}


@pytest.mark.parametrize(
    ("name", "files", "cap"),
    [
        pytest.param("eval_problems", many_eval_outputs(201), 200, id="eval"),
        pytest.param("review_problems", many_review_outputs(501), 500, id="review"),
    ],
)
def test_validates_at_most_cap_when_outputs_many(
    snapshot_of: SnapshotFactory,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    *,
    files: dict[str, bytes],
    cap: int,
) -> None:
    calls = counting(monkeypatch, name)

    found = outputs_found(snapshot_of, files)

    outputs = sorted(path for path in files if path.endswith(".json"))
    assert len(calls) == cap
    assert [path for _, path, _, _ in found[:-1]] == outputs[:cap]
    assert {severity for severity, _, _, _ in found[:-1]} == {Severity.WARNING}
    # E22: the output past the cap is counted in the run's one info line.
    assert found[-1] == skipped_info(1)
    assert (MAX_EVAL_FILES, MAX_REVIEW_FILES) == (200, 500)


@pytest.mark.parametrize(
    ("name", "files", "validated"),
    [
        # A review costs its own bytes: eight of the largest fill the budget exactly.
        pytest.param(
            "review_problems",
            {
                f"{REVIEWS}/TST-7.md": b"# Review\n",
                **{
                    f"{REVIEWS}/TST-7/spec-r{index}.json": b"{}".ljust(MAX_OUTPUT_BYTES)
                    for index in range(1, BUDGET_OUTPUTS + 2)
                },
            },
            BUDGET_OUTPUTS,
            id="review",
        ),
        # An eval also costs its sibling's head and the record, so one fewer fits.
        pytest.param(
            "eval_problems",
            {
                path: content
                for index in range(BUDGET_OUTPUTS)
                for path, content in an_eval_pair(
                    f"e-{index}", b"{}".ljust(MAX_OUTPUT_BYTES)
                ).items()
            },
            BUDGET_OUTPUTS - 1,
            id="eval",
        ),
    ],
)
def test_validates_within_budget_when_outputs_large(
    snapshot_of: SnapshotFactory,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    *,
    files: dict[str, bytes],
    validated: int,
) -> None:
    calls = counting(monkeypatch, name)

    found = outputs_found(snapshot_of, files)

    assert len(calls) == validated
    assert len(found) == validated + 1
    # E22: the output that does not fit the budget is counted in the run's one info line.
    assert found[-1] == skipped_info(1)
    assert MAX_VALIDATED_BYTES == 4_194_304


OTHER_RECORD = "brain/features/other/features.json"
FEATURES_DIR = "brain/features"
SKIPPED_FIX = "run ./hub validate-output <kind> <path> on each"


def skipped_info(count: int) -> Leveled:
    noun = "output" if count == 1 else "outputs"
    message = f"{count} agent {noun} not validated (over the doctor's budget)"
    return (Severity.INFO, FEATURES_DIR, message, SKIPPED_FIX)


def full_budget_reviews(folder: str) -> dict[str, bytes]:
    """Reviews of the largest size that fill the whole run's budget on their own."""
    outputs = {
        f"{folder}/reviews/TST-7/spec-r{index}.json": b"{}".ljust(MAX_OUTPUT_BYTES)
        for index in range(1, BUDGET_OUTPUTS + 1)
    }
    return {f"{folder}/reviews/TST-7.md": b"# Review\n", **outputs}


def test_shares_budget_when_outputs_in_many_features(
    snapshot_of: SnapshotFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # E22: one budget per run, spent in listing order; the second feature finds it spent.
    calls = counting(monkeypatch, "review_problems")
    files = {
        OTHER_RECORD: json.dumps(a_record(an_ac(1), an_ac(2))).encode(),
        **full_budget_reviews("brain/features/demo"),
        **full_budget_reviews("brain/features/other"),
    }

    found = outputs_found(snapshot_of, files)

    assert len(calls) == BUDGET_OUTPUTS
    assert [path for _, path, _, _ in found[:-1]] == sorted(
        path for path in files if path.startswith(f"{REVIEWS}/") and path.endswith(".json")
    )
    assert found[-1] == skipped_info(BUDGET_OUTPUTS)


def test_counts_skipped_outputs_once_when_caps_reached_in_many_features(
    snapshot_of: SnapshotFactory,
) -> None:
    other = "brain/features/other"
    files = {
        OTHER_RECORD: json.dumps(a_record(an_ac(1))).encode(),
        **many_review_outputs(502),
        f"{other}/reviews/TST-7.md": b"# Review\n",
        **{f"{other}/reviews/TST-7/spec-r{index}.json": b"{}" for index in range(1, 504)},
    }

    found = outputs_found(snapshot_of, files)

    assert [finding for finding in found if finding[0] is Severity.INFO] == [skipped_info(5)]
    assert found[-1] == skipped_info(5)


def test_adds_no_info_when_no_outputs_skipped(snapshot_of: SnapshotFactory) -> None:
    files = {**many_review_outputs(500), **an_eval_pair("abc-1", b"{}")}

    found = outputs_found(snapshot_of, files)

    assert len(found) == 501
    assert {severity for severity, _, _, _ in found} == {Severity.WARNING}


def test_keeps_findings_when_outputs_added_to_legacy_folder(
    snapshot_of: SnapshotFactory,
) -> None:
    legacy = {
        SPEC: b"AC-1 AC-2 AC-3\n",
        "brain/features/demo/eval.md": b"# Eval\n",
        f"{EVALS}/tst-7.md": a_good_eval("tst-7", **SHIP_FIELDS),
        f"{EVALS}/tst-8.md": a_good_eval("tst-9"),
        f"{REVIEWS}/TST-7.md": b"# Review\n",
    }
    outputs = {
        f"{EVALS}/tst-7.json": an_eval_output("tst-7"),
        f"{EVALS}/tst-10.json": an_eval_output("tst-10"),
        f"{REVIEWS}/TST-7/spec-r1.json": a_review_output(),
        f"{REVIEWS}/TST-9/spec-r1.json": a_review_output("TST-9"),
    }
    record = json.dumps(a_record(an_ac(1), an_ac(2, repo="other"))).encode()

    before = outputs_found(snapshot_of, legacy, record=record)
    after = outputs_found(snapshot_of, legacy | outputs, record=record)

    assert len(before) == 3
    assert [finding for finding in after if finding[1] not in outputs] == before
    assert [finding for finding in after if finding[1] in outputs] == [
        eval_warning("tst-10.json", NO_EVAL_NOTE, NO_EVAL_NOTE_FIX),
        review_warning("TST-9/spec-r1.json", NO_REVIEW_NOTE, NO_REVIEW_NOTE_FIX),
    ]
