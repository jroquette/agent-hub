from collections.abc import Callable, Mapping

import pytest

from agent_hub.core.doctor.guard_extension_rule import GUARD_EXTENSION, MAX_BYTES
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_files.tree_snapshot import FileEntry, FolderEntry, LinkEntry, TreeEntry

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[Severity, str | None, int | None, str, str]

# The builder's project is ``demo``.
EXTENSION = "plugin/demo/hooks/project_guard.py"
FIX = "make it a UTF-8 Python 3.9 file with a top-level def check(event, cfg)"
NOT_READ_FIX = "run hub doctor again"
TOO_LARGE_FIX = "keep it under 1 MiB"
# The seeded stub's shape (the generator's template), rebuilt here: core never reads templates.
SEEDED_STUB = (
    '"""This project\'s guard extension: the project\'s own rules on top of the base guard."""\n'
    "\n"
    "\n"
    "def check(event, cfg):\n"
    '    """Keep the base verdict: this project has no guard rule yet."""\n'
    "    return None\n"
)


def findings_of(snapshot: DoctorSnapshot) -> list[Shown]:
    found = list(GUARD_EXTENSION.check(snapshot))
    assert all(finding.rule == "hooks.guard-extension" for finding in found)
    return [
        (finding.severity, finding.path, finding.line, finding.message, finding.fix)
        for finding in found
    ]


def with_source(snapshot_of: SnapshotFactory, source: str) -> DoctorSnapshot:
    return snapshot_of(files={EXTENSION: source.encode()})


def an_error(message: str, line: int | None, fix: str = FIX) -> Shown:
    return (Severity.ERROR, EXTENSION, line, message, fix)


def test_reports_nothing_when_extension_absent_or_seeded_stub(
    snapshot_of: SnapshotFactory,
) -> None:
    assert findings_of(snapshot_of()) == []
    assert findings_of(snapshot_of(problem="could not read", paths_read=False)) == []
    assert findings_of(with_source(snapshot_of, SEEDED_STUB)) == []


def test_reads_nothing_beyond_fixed_paths_when_rule_declared() -> None:
    assert GUARD_EXTENSION.reads == frozenset()
    assert GUARD_EXTENSION.severity is Severity.ERROR


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            # The parser points at the match statement's last line.
            "def check(event, cfg):\n    return None\n\n\nmatch 1:\n    case _:\n        pass\n",
            an_error(
                "does not parse as Python 3.9: "
                "Pattern matching is only supported in Python 3.10 and greater",
                7,
            ),
            id="match-statement",
        ),
        pytest.param(
            "import sys\n\ndef check(event, cfg)\n    return None\n",
            an_error("does not parse as Python 3.9: expected ':'", 3),
            id="missing-colon",
        ),
        pytest.param(
            "def guard(event, cfg):\n    return None\n",
            an_error("defines no top-level def check", None),
            id="no-check",
        ),
        pytest.param(
            "async def check(event, cfg):\n    return None\n",
            an_error("check is async; the guard calls it as a plain function", 1),
            id="async-check",
        ),
        pytest.param(
            "class Guard:\n    def check(self, event, cfg):\n        return None\n",
            an_error("defines no top-level def check", None),
            id="check-in-class",
        ),
        pytest.param(
            "def check(event):\n    return None\n",
            an_error("check takes 1 positional parameter; the guard passes 2 (event, cfg)", 1),
            id="one-parameter",
        ),
        pytest.param(
            "def check():\n    return None\n",
            an_error("check takes 0 positional parameters; the guard passes 2 (event, cfg)", 1),
            id="no-parameter",
        ),
        pytest.param(
            "\ndef check(event, cfg, extra):\n    return None\n",
            an_error("check requires 3 positional parameters; the guard passes 2 (event, cfg)", 2),
            id="three-parameters",
        ),
        pytest.param(
            "def check(event, cfg, *, strict):\n    return None\n",
            an_error("check's keyword-only parameter strict has no default", 1),
            id="keyword-only-without-default",
        ),
    ],
)
def test_reports_error_when_extension_not_checkable(
    snapshot_of: SnapshotFactory, source: str, expected: Shown
) -> None:
    assert findings_of(with_source(snapshot_of, source)) == [expected]


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        pytest.param(
            LinkEntry(target="../../../elsewhere.py", outside=True),
            an_error("not a regular file", None),
            id="link",
        ),
        pytest.param(FolderEntry(), an_error("not a regular file", None), id="folder"),
        pytest.param(
            FileEntry(executable=False, content=b"def check(event, cfg):\n    return '\xff'\n"),
            an_error("not UTF-8 text without NUL bytes", None),
            id="non-utf8",
        ),
        pytest.param(
            FileEntry(executable=False, content=b"def check(event, cfg):\n    return '\x00'\n"),
            an_error("not UTF-8 text without NUL bytes", None),
            id="nul-byte",
        ),
        pytest.param(
            FileEntry(executable=False, content=None),
            an_error("content was not read, so it cannot be checked", None, NOT_READ_FIX),
            id="unread",
        ),
    ],
)
def test_reports_error_when_extension_entry_not_checkable(
    snapshot_of: SnapshotFactory, entry: TreeEntry, expected: Shown
) -> None:
    entries: Mapping[str, TreeEntry] = {EXTENSION: entry}

    assert findings_of(snapshot_of(entries=entries)) == [expected]


@pytest.mark.parametrize(
    "source",
    [
        # The parser's own stack overflows (``MemoryError``).
        pytest.param("x = " + "-" * 100_000 + "1\n", id="parser-stack"),
        # The tree is too deep to build (``RecursionError``).
        pytest.param("x = y" + ".a" * 200_000 + "\n", id="tree-depth"),
    ],
)
def test_reports_error_when_extension_too_complex_to_parse(
    snapshot_of: SnapshotFactory, source: str
) -> None:
    assert findings_of(with_source(snapshot_of, source)) == [an_error("too complex to parse", None)]


def test_accepts_any_parameter_names_when_two_positional(snapshot_of: SnapshotFactory) -> None:
    source = "def check(tool_call, hub):\n    return None\n"

    assert findings_of(with_source(snapshot_of, source)) == []


@pytest.mark.parametrize(
    "signature",
    [
        pytest.param("event, cfg", id="two-positional"),
        pytest.param("event, cfg, extra=None", id="extra-with-default"),
        pytest.param("*args", id="star-args-only"),
        pytest.param("event, *rest", id="one-and-star-args"),
        pytest.param("event, cfg, *args", id="two-and-star-args"),
        pytest.param("event, cfg, **kw", id="double-star-kwargs"),
        pytest.param("event, cfg, /", id="positional-only"),
    ],
)
def test_accepts_signature_when_guard_call_succeeds(
    snapshot_of: SnapshotFactory, signature: str
) -> None:
    source = f"def check({signature}):\n    return None\n"

    assert findings_of(with_source(snapshot_of, source)) == []


def test_accepts_keyword_only_with_default_when_two_positional(
    snapshot_of: SnapshotFactory,
) -> None:
    source = "def check(event, cfg, *, strict=False, **extra):\n    return None\n"

    assert findings_of(with_source(snapshot_of, source)) == []


@pytest.mark.parametrize(
    "signature",
    [
        pytest.param("event, cfg, /", id="both-positional-only"),
        pytest.param("event, /, cfg", id="one-positional-only"),
    ],
)
def test_accepts_positional_only_when_two_given(
    snapshot_of: SnapshotFactory, signature: str
) -> None:
    source = f"def check({signature}):\n    return None\n"

    assert findings_of(with_source(snapshot_of, source)) == []


def test_checks_last_definition_when_check_defined_twice(snapshot_of: SnapshotFactory) -> None:
    # The module's last binding of ``check`` is the one the guard calls.
    fixed = "def check(event):\n    return None\n\n\ndef check(event, cfg):\n    return None\n"
    broken = "def check(event, cfg):\n    return None\n\n\ndef check(event):\n    return None\n"

    assert findings_of(with_source(snapshot_of, fixed)) == []
    assert findings_of(with_source(snapshot_of, broken)) == [
        an_error("check takes 1 positional parameter; the guard passes 2 (event, cfg)", 5)
    ]


def test_never_runs_extension_when_top_level_would_raise(snapshot_of: SnapshotFactory) -> None:
    source = "raise SystemExit('ran')\n\n\ndef check(event, cfg):\n    return None\n"

    assert findings_of(with_source(snapshot_of, source)) == []


VALID_DEF = "def check(event, cfg):\n    return None\n\n\n"


@pytest.mark.parametrize(
    ("binding", "kind"),
    [
        pytest.param("class check:\n    pass\n", "class", id="class"),
        pytest.param("import check\n", "import", id="import"),
        pytest.param("import check.sub\n", "import", id="dotted-import"),
        pytest.param("import json as check\n", "import", id="import-as"),
        pytest.param("from json import check\n", "import", id="from-import"),
        pytest.param("from json import loads as check\n", "import", id="from-import-as"),
        pytest.param("check = None\n", "assignment", id="assign"),
        pytest.param("check, other = None, None\n", "assignment", id="tuple-assign"),
        pytest.param("[other, *check] = [1, 2]\n", "assignment", id="starred-list-assign"),
        pytest.param("check: object = None\n", "annotated assignment", id="annotated-assign"),
        pytest.param("check += 1\n", "augmented assignment", id="augmented-assign"),
        pytest.param("del check\n", "del", id="delete"),
    ],
)
def test_reports_error_when_check_last_bound_by_other_than_def(
    snapshot_of: SnapshotFactory, binding: str, kind: str
) -> None:
    # The binding sits on line 5, after a valid def.
    source = VALID_DEF + binding

    assert findings_of(with_source(snapshot_of, source)) == [
        an_error(f"check is last bound by {kind} at line 5, not a def", 5)
    ]


@pytest.mark.parametrize(
    "binding",
    [
        pytest.param("check: object\n", id="annotation-without-value"),
        pytest.param("import check_other\nfrom json import check as other\n", id="other-names"),
        pytest.param("import other.check\n", id="dotted-import-binds-first-name"),
        pytest.param("checked = check\n", id="read-not-bound"),
    ],
)
def test_reports_nothing_when_statement_does_not_bind_check(
    snapshot_of: SnapshotFactory, binding: str
) -> None:
    assert findings_of(with_source(snapshot_of, VALID_DEF + binding)) == []


def test_accepts_def_when_it_rebinds_check_last(snapshot_of: SnapshotFactory) -> None:
    source = "check = None\n\n\n" + VALID_DEF

    assert findings_of(with_source(snapshot_of, source)) == []


def test_reports_nothing_when_utf8_bom_starts_valid_file(snapshot_of: SnapshotFactory) -> None:
    content = b"\xef\xbb\xbf" + SEEDED_STUB.encode()
    entries: Mapping[str, TreeEntry] = {EXTENSION: FileEntry(executable=False, content=content)}

    assert findings_of(snapshot_of(entries=entries)) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "# coding: bogus\n" + SEEDED_STUB,
            an_error("does not parse as Python 3.9: unknown encoding: bogus", None),
            id="unknown-coding",
        ),
        pytest.param(
            "# coding: ascii\ndef check(event, cfg):\n    return '\u00e9'\n",
            an_error(
                "does not parse as Python 3.9: 'ascii' codec can't decode byte 0xc3 "
                "in position 51: ordinal not in range(128)",
                None,
            ),
            id="ascii-coding-with-utf8",
        ),
    ],
)
def test_reports_error_when_coding_cookie_rejects_file(
    snapshot_of: SnapshotFactory, source: str, expected: Shown
) -> None:
    assert findings_of(with_source(snapshot_of, source)) == [expected]


def test_reports_error_when_extension_too_large(snapshot_of: SnapshotFactory) -> None:
    # Not UTF-8 either: the size cap is checked before the text gate.
    content = b"\xff" * (MAX_BYTES + 1)
    entries: Mapping[str, TreeEntry] = {EXTENSION: FileEntry(executable=False, content=content)}

    assert findings_of(snapshot_of(entries=entries)) == [
        an_error(
            f"too large to check ({MAX_BYTES + 1} bytes, limit 1 MiB)",
            None,
            TOO_LARGE_FIX,
        )
    ]


def test_reports_nothing_when_valid_extension_exactly_at_size_limit(
    snapshot_of: SnapshotFactory,
) -> None:
    content = SEEDED_STUB.encode().ljust(MAX_BYTES, b"#")
    entries: Mapping[str, TreeEntry] = {EXTENSION: FileEntry(executable=False, content=content)}

    assert len(content) == MAX_BYTES
    assert findings_of(snapshot_of(entries=entries)) == []
