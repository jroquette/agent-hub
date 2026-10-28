"""The perf fixture's plan and events (``scripts/perf/fixture.py``): size, spread, synthetic
content, issue links, determinism and the cache, all in memory (the database checks are in
``tests/e2e/test_perf_suite.py``)."""

import re
from collections.abc import Iterable, Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from agent_hub.core.events.event import Event, EventType
from agent_hub.core.sessions.session_label import (
    LabelRules,
    label_signals,
    session_label,
    with_issue,
)
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.session_scenarios import a_session_events, as_stored
from scripts.perf import fixture
from scripts.perf.fixture import (
    BRANCH_PREFIX,
    DEFAULT_EVENTS,
    FEATURE_SLUG,
    SEED,
    VOCABULARY,
    cache_path,
    ensure,
    plan_sessions,
    session_events,
)

# The ticket's numbers (spec AC-2): 400,000 events over 2,500 sessions (plus or minus 5%), about
# 90 days.
TICKET_EVENTS = 400_000
SESSIONS_LOW, SESSIONS_HIGH = 2_375, 2_625
SPAN_LOW, SPAN_HIGH = timedelta(days=89), timedelta(days=91)
# Plan C2: issue keys AGH-1..AGH-50, AGH-7 being the feature's.
ISSUE_KEYS = frozenset(f"AGH-{n}" for n in range(1, 51))
FEATURE_ISSUE = "AGH-7"
REAL_HANDLES = frozenset({"roquettejh", "jroquette", "roquette", "henrique", "jose"})
SEPARATORS = re.compile(r"[/_:.\- ]")
ISO_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")
HEX = re.compile(r"^[0-9a-f]+$")
BRANCH = re.compile(rf"^{re.escape('perf/')}agh-([1-9][0-9]*)-[a-z]+$")


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _strings(item)


def _tokens(texts: Iterable[str]) -> set[str]:
    return {
        token for text in texts for token in SEPARATORS.split(ISO_STAMP.sub(" ", text)) if token
    }


def _stored_strings(event: Event) -> Iterator[str]:
    yield event.session
    yield event.source_id
    if event.repo is not None:
        yield event.repo
    yield from _strings(event.payload)


def _builder_words() -> set[str]:
    """The fixed words the core builders write whatever their arguments: read from the builders
    themselves, with one-letter arguments that the set then drops."""
    built = [
        *a_session_events("s", project="p", repo="r", cwd="/c", tools=(("T", {}),)),
        *a_session_events(
            "s",
            project="p",
            repo="r",
            cwd="/c",
            tools=(("T", {}),),
            failed_tools=frozenset({0}),
            run="r",
            step="s",
            attempt=1,
            git_branch="b",
            slash_commands=("/x",),
        ),
        an_event(source_id="s"),
    ]
    words = _tokens(text for event in built for text in _stored_strings(event))
    return words - {"s", "p", "r", "c", "T", "b", "x"}


def _events_of(events: int, seed: int) -> list[Event]:
    planned = plan_sessions(events=events, seed=seed)
    return [event for session in planned for event in session_events(session)]


def _dumped(events: Iterable[Event]) -> list[dict[str, object]]:
    return [event.model_dump(mode="json") for event in events]


def test_plans_exactly_the_requested_events_when_events_is_the_default() -> None:
    assert DEFAULT_EVENTS == TICKET_EVENTS

    planned = plan_sessions(events=DEFAULT_EVENTS, seed=SEED)
    starts = [session.start for session in planned]

    assert sum(session.size for session in planned) == TICKET_EVENTS
    assert SESSIONS_LOW <= len(planned) <= SESSIONS_HIGH
    assert SPAN_LOW <= max(starts) - min(starts) <= SPAN_HIGH


def test_spreads_sizes_to_the_exact_total_when_events_is_not_a_multiple() -> None:
    planned = plan_sessions(events=1_001, seed=SEED)
    sizes = [session.size for session in planned]
    built = [len(session_events(session)) for session in planned]

    assert len(planned) > 1
    assert sum(sizes) == 1_001
    assert built == sizes
    assert max(sizes) - min(sizes) <= 1


def test_draws_only_synthetic_tokens_when_payloads_are_walked() -> None:
    events = _events_of(2_000, SEED)
    tokens = _tokens(text for event in events for text in _stored_strings(event))
    allowed = set(VOCABULARY) | _builder_words()

    assert len(events) == 2_000
    assert len(tokens) > 0
    assert not REAL_HANDLES & {word.lower() for word in VOCABULARY}
    assert not REAL_HANDLES & tokens
    assert sorted(t for t in tokens if t not in allowed and not HEX.match(t)) == []


def test_builds_the_same_events_when_seed_is_repeated() -> None:
    first = _dumped(_events_of(2_000, SEED))

    assert len(first) == 2_000
    assert _dumped(_events_of(2_000, SEED)) == first


def test_builds_other_events_when_seed_differs() -> None:
    assert _dumped(_events_of(2_000, SEED)) != _dumped(_events_of(2_000, SEED + 1))


def test_links_the_issue_with_the_hub_rules_when_a_session_has_a_branch() -> None:
    assert BRANCH_PREFIX == "perf/"
    rules = LabelRules(teams=("AGH",), branch_prefix=BRANCH_PREFIX)
    branched = [s for s in plan_sessions(events=20_000, seed=SEED) if s.git_branch is not None]

    assert len(branched) > 0
    for planned in branched:
        found = BRANCH.match(planned.git_branch)
        assert found is not None, planned.git_branch
        label = session_label(label_signals(as_stored(session_events(planned))))
        issue = with_issue(label, rules).issue
        assert issue == f"AGH-{found.group(1)}"
        assert issue in ISSUE_KEYS
    every_branch = [s.git_branch for s in plan_sessions(events=DEFAULT_EVENTS, seed=SEED)]
    assert any(b is not None and b.startswith("perf/agh-7-") for b in every_branch)


def test_edits_the_feature_spec_when_some_sessions_are_planned() -> None:
    spec = f"brain/features/{FEATURE_SLUG}/spec.md"
    planned = plan_sessions(events=20_000, seed=SEED)
    editing = [
        session
        for session in planned
        if any(
            event.type == EventType.TOOL_CALL
            and event.payload.get("tool") == "Edit"
            and event.payload.get("path") == spec
            for event in session_events(session)
        )
    ]

    assert len(planned) > 1
    assert 0 < len(editing) < len(planned)


def test_names_the_cache_by_events_seed_and_head_when_keyed(tmp_path: Path) -> None:
    assert cache_path(tmp_path, events=400_000, seed=7, head="0010") == (
        tmp_path / "fixture-e400000-s7-h0010.db"
    )


class RecordingBuilder:
    """A stand-in for ``fixture.build``: records each call and writes a small text file."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[Path, int, int]] = []
        self.partials: list[Path] = []
        self.fail = fail

    def __call__(self, path: Path, *, events: int, seed: int) -> None:
        self.calls.append((path, events, seed))
        if self.fail:
            partial = Path(f"{path}.partial")
            partial.write_text("half a build\n", "utf-8")
            self.partials.append(partial)
            raise RuntimeError("synthetic build failure")
        path.write_text(f"built {len(self.calls)}\n", "utf-8")


def test_reuses_the_cached_file_when_the_key_is_unchanged(tmp_path: Path) -> None:
    builder = RecordingBuilder()

    first = ensure(tmp_path, events=1_000, seed=SEED, rebuild=False, builder=builder)
    again = ensure(tmp_path, events=1_000, seed=SEED, rebuild=False, builder=builder)

    assert first.name.startswith(f"fixture-e1000-s{SEED}-h")
    assert again == first
    assert len(builder.calls) == 1
    assert first.read_text("utf-8") == "built 1\n"
    other = ensure(tmp_path, events=1_001, seed=SEED, rebuild=False, builder=builder)
    assert other != first
    assert len(builder.calls) == 2


def test_rebuilds_when_rebuild_is_set(tmp_path: Path) -> None:
    builder = RecordingBuilder()
    cached = ensure(tmp_path, events=1_000, seed=SEED, rebuild=False, builder=builder)
    assert cached.read_text("utf-8") == "built 1\n"

    rebuilt = ensure(tmp_path, events=1_000, seed=SEED, rebuild=True, builder=builder)

    assert rebuilt == cached
    assert len(builder.calls) == 2
    assert builder.calls[-1][1:] == (1_000, SEED)
    assert rebuilt.read_text("utf-8") == "built 2\n"


def test_leaves_no_cached_file_when_the_build_fails(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    builder = RecordingBuilder(fail=True)

    with pytest.raises(RuntimeError, match="synthetic build failure"):
        ensure(cache, events=1_000, seed=SEED, rebuild=False, builder=builder)

    assert len(builder.partials) == 1
    assert not builder.partials[0].exists()
    assert sorted(cache.iterdir()) == []


def test_reads_the_event_count_from_perf_events_when_no_flag_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = RecordingBuilder()
    monkeypatch.setattr(fixture, "build", builder)
    out = tmp_path / "fixture.db"

    code = fixture.main(["--out", str(out)], {"PERF_EVENTS": "1500"})

    assert code == 0
    assert builder.calls == [(out, 1_500, SEED)]
