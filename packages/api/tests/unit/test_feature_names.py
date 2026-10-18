"""Feature nicknames: saved beside the hub registry, cleared by an empty name."""

from pathlib import Path

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
