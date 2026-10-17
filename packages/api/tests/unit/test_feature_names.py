"""Feature nicknames: saved beside the hub registry, cleared by an empty name."""

from pathlib import Path

from agent_hub.api.feature_names import FeatureNameBody, FeatureNames


def _body(name: str, slug: str = "guard-subagents") -> FeatureNameBody:
    return FeatureNameBody(project="agent-hub", slug=slug, name=name)


def test_feature_names_lists_nothing_when_the_file_is_missing(tmp_path: Path) -> None:
    assert FeatureNames(tmp_path / "names.json").all().items == ()


def test_feature_names_saves_a_trimmed_name_and_lists_it(tmp_path: Path) -> None:
    names = FeatureNames(tmp_path / "config" / "names.json")

    saved = names.set(_body("  Guard   for sub-agents "))

    assert saved.name == "Guard for sub-agents"
    assert [(n.project, n.slug, n.name) for n in names.all().items] == [
        ("agent-hub", "guard-subagents", "Guard for sub-agents")
    ]


def test_feature_names_forgets_a_name_set_blank_or_to_the_slug(tmp_path: Path) -> None:
    names = FeatureNames(tmp_path / "names.json")
    names.set(_body("Guard"))
    names.set(_body("Other", slug="other"))

    assert names.set(_body("  ")).name == ""
    names.set(_body("other", slug="other"))

    assert names.all().items == ()


def test_feature_names_ignores_an_unreadable_file(tmp_path: Path) -> None:
    path = tmp_path / "names.json"
    path.write_text("[not json", encoding="utf-8")

    assert FeatureNames(path).all().items == ()
