"""Feature nicknames: saved beside the hub registry, cleared by an empty name."""

import json
from pathlib import Path

import pytest

from agent_hub.api import feature_names
from agent_hub.api.feature_names import FeatureNameBody, FeatureNames


def _body(name: str, slug: str = "guard-subagents") -> FeatureNameBody:
    return FeatureNameBody(project="agent-hub", slug=slug, name=name)


def test_feature_names_lists_nothing_when_the_file_is_missing(tmp_path: Path) -> None:
    assert FeatureNames(tmp_path / "names.json").all().items == ()


def test_saves_and_lists_trimmed_name_when_name_set(tmp_path: Path) -> None:
    names = FeatureNames(tmp_path / "config" / "names.json")

    saved = names.set(_body("  Guard   for sub-agents "))

    assert saved.name == "Guard for sub-agents"
    assert [(n.project, n.slug, n.name) for n in names.all().items] == [
        ("agent-hub", "guard-subagents", "Guard for sub-agents")
    ]


def test_forgets_name_when_set_blank_or_to_slug(tmp_path: Path) -> None:
    names = FeatureNames(tmp_path / "names.json")
    names.set(_body("Guard"))
    names.set(_body("Other", slug="other"))

    assert names.set(_body("  ")).name == ""
    names.set(_body("other", slug="other"))

    assert names.all().items == ()


def test_reads_no_names_when_file_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "names.json"
    path.write_text("[not json", encoding="utf-8")

    assert FeatureNames(path).all().items == ()


# AC-PG-28.1: GET lists every nickname sorted by project, then slug, whatever the order set.
def test_lists_names_sorted_by_project_and_slug_when_set_out_of_order(tmp_path: Path) -> None:
    names = FeatureNames(tmp_path / "names.json")
    for project, slug in (("web", "b"), ("api", "z"), ("web", "a"), ("api", "c")):
        names.set(FeatureNameBody(project=project, slug=slug, name=f"{project} {slug} name"))

    listed = [(item.project, item.slug) for item in names.all().items]

    assert listed == [("api", "c"), ("api", "z"), ("web", "a"), ("web", "b")]


# AC-PG-28.1: the order is that of the "<project>/<slug>" keys, so a project that is a prefix
# of another sorts after it ("-" sorts before "/"). Mismatch with a strict (project, slug) order,
# which would list "demo" first; this test records what the code does.
def test_sorts_by_key_text_when_one_project_prefixes_another(tmp_path: Path) -> None:
    names = FeatureNames(tmp_path / "names.json")
    names.set(FeatureNameBody(project="demo", slug="a", name="Demo A"))
    names.set(FeatureNameBody(project="demo-api", slug="z", name="Demo API Z"))

    listed = [(item.project, item.slug) for item in names.all().items]

    assert listed == [("demo-api", "z"), ("demo", "a")]


# AC-PG-28.1: each write rewrites the whole file (every name, keyed by project/slug), no
# temporary file left beside it.
def test_writes_whole_file_when_name_added(tmp_path: Path) -> None:
    path = tmp_path / "names.json"
    names = FeatureNames(path)
    names.set(_body("Guard"))

    names.set(_body("Other", slug="other"))

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "agent-hub/guard-subagents": "Guard",
        "agent-hub/other": "Other",
    }
    assert sorted(child.name for child in tmp_path.iterdir()) == ["names.json"]


# AC-PG-28.1: the write is atomic: when the replace fails, the old file stays as it was.
def test_keeps_old_file_when_atomic_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "names.json"
    names = FeatureNames(path)
    names.set(_body("Guard"))
    before = path.read_bytes()

    def refuse(_source: object, _target: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(feature_names.os, "replace", refuse)

    with pytest.raises(OSError, match="No space left"):
        names.set(_body("Renamed"))

    assert path.read_bytes() == before
    assert [item.name for item in names.all().items] == ["Guard"]


# AC-PG-28.1: entries that are not "<project>/<slug>" text pairs are ignored when read.
def test_skips_entries_when_file_has_odd_values(tmp_path: Path) -> None:
    path = tmp_path / "names.json"
    odd = {"agent-hub/ok": "Fine", "noslash": "x", "agent-hub/blank": "  ", "agent-hub/n": 3}
    path.write_text(json.dumps(odd), encoding="utf-8")

    assert [(n.slug, n.name) for n in FeatureNames(path).all().items] == [("ok", "Fine")]
