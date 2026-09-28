import pytest

from agent_hub.core.hub_config.problems import json_path, one_line


def test_formats_path_when_loc_has_fields_and_indices() -> None:
    assert json_path(("repos", 0, "dir")) == "repos[0].dir"
    assert json_path(("guard", "ask_before_edit", 2)) == "guard.ask_before_edit[2]"
    assert json_path(("modules", "contract-sync")) == "modules.contract-sync"


@pytest.mark.parametrize(
    ("loc", "expected"),
    [
        (
            ("doctor", "rules", "instructions.size", "max_lines", "AGENTS.md"),
            'doctor.rules["instructions.size"].max_lines["AGENTS.md"]',
        ),
        (("doctor", "rules", "bench.tasks"), 'doctor.rules["bench.tasks"]'),
        (("$schema",), "$schema"),
        (("a\nb",), '["a\\nb"]'),
        (("project", "x y"), 'project["x\\u2028y"]'),
        (("0",), '["0"]'),
        (("",), '[""]'),
        (("a b",), '["a b"]'),
        (("[key]",), '["[key]"]'),
    ],
    ids=[
        "glob-key",
        "dotted-rule",
        "dollar-key",
        "newline",
        "line-separator",
        "digit",
        "empty",
        "space",
        "marker-spelling",
    ],
)
def test_quotes_segment_when_key_not_plain(loc: tuple[str | int, ...], expected: str) -> None:
    path = json_path(loc)

    assert path == expected
    assert len(path.splitlines()) == 1


def test_uses_root_when_loc_empty() -> None:
    assert json_path(()) == "$"


def test_escapes_characters_when_not_printable() -> None:
    assert one_line("a\nb c\td\x85e é") == "a\\nb\\u2028c\\td\\x85e é"
