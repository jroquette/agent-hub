import dataclasses
from collections.abc import Mapping

import pytest

from agent_hub.core.hub_files.extension_inputs import (
    NO_EXTENSIONS,
    ExtensionInputs,
    entry_name_key,
    extension_inputs_from,
)
from agent_hub.core.hub_files.plan_init import PathProblem
from agent_hub.core.hub_files.tree_snapshot import (
    FileEntry,
    FolderEntry,
    LinkEntry,
    OtherEntry,
    TreeEntry,
    TreeSnapshot,
)

PROJECT = "demo"
SETTINGS = ".claude/settings.project.json"
SIBLINGS = (SETTINGS,)
AGENTS = "plugin/demo/agents"
SKILLS = "plugin/demo/skills"


def a_tree(entries: Mapping[str, TreeEntry]) -> TreeSnapshot:
    return TreeSnapshot(entries=dict(entries), git_present=False)


def a_file(content: bytes | None = None) -> FileEntry:
    return FileEntry(executable=False, content=content)


def build(entries: Mapping[str, TreeEntry]) -> ExtensionInputs | tuple[PathProblem, ...]:
    return extension_inputs_from(a_tree(entries), project=PROJECT, siblings=SIBLINGS)


def test_freezes_value_when_built() -> None:
    project_json = {SETTINGS: b"{}\n"}
    inputs = ExtensionInputs(project_json=project_json, agents=("a.md",), skills=("s",))

    project_json[SETTINGS] = b"[]\n"

    assert inputs.project_json == {SETTINGS: b"{}\n"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        inputs.agents = ()  # type: ignore[misc]
    with pytest.raises(TypeError):
        inputs.project_json[SETTINGS] = b"[]\n"  # type: ignore[index]


def test_sorts_names_when_built_unsorted() -> None:
    project_json = {"b.project.json": b"{}\n", "a.project.json": b"[]\n"}
    inputs = ExtensionInputs(project_json=project_json, agents=("b.md", "a.md"), skills=("z", "y"))

    assert list(inputs.project_json) == ["a.project.json", "b.project.json"]
    assert inputs.agents == ("a.md", "b.md")
    assert inputs.skills == ("y", "z")


@pytest.mark.parametrize(
    ("agents", "message"),
    [
        pytest.param(("a.md", "a.md"), "more than once", id="duplicate"),
        pytest.param(("",), "not a plain entry name", id="empty"),
        pytest.param(("x/a.md",), "not a plain entry name", id="nested"),
        pytest.param((".hidden",), "not a plain entry name", id="dotfile"),
        pytest.param(("a\\b.md",), "cannot be linked", id="backslash"),
        pytest.param(("a\udcff.md",), "cannot be linked", id="surrogate"),
        pytest.param(("a\n.md",), "cannot be linked", id="newline"),
    ],
)
def test_rejects_value_when_name_invalid(agents: tuple[str, ...], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ExtensionInputs(project_json={}, agents=agents, skills=())


def test_rejects_value_when_key_not_project_json() -> None:
    with pytest.raises(ValueError, match=r"not a \*\.project\.json path"):
        ExtensionInputs(project_json={".claude/settings.json": b"{}"}, agents=(), skills=())


def test_builds_from_snapshot_when_entries_present() -> None:
    entries: dict[str, TreeEntry] = {
        SETTINGS: a_file(b'{"env": {"X": "1"}}\n'),
        "plugin/demo": FolderEntry(),
        AGENTS: FolderEntry(),
        f"{AGENTS}/planner.md": a_file(),
        f"{AGENTS}/coder.md": FileEntry(executable=True, content=None),
        f"{AGENTS}/.gitkeep": a_file(),
        f"{AGENTS}/linked.md": LinkEntry(target="../x.md", outside=False),
        f"{AGENTS}/folder": FolderEntry(),
        f"{AGENTS}/pipe": OtherEntry(kind="fifo"),
        f"{AGENTS}/folder/nested.md": a_file(),
        SKILLS: FolderEntry(),
        f"{SKILLS}/review": FolderEntry(),
        f"{SKILLS}/audit": FolderEntry(),
        f"{SKILLS}/.hidden": FolderEntry(),
        f"{SKILLS}/.gitkeep": a_file(),
        f"{SKILLS}/file.md": a_file(),
        f"{SKILLS}/linked": LinkEntry(target="../../x", outside=False),
        f"{SKILLS}/review/SKILL.md": a_file(),
        f"{SKILLS}/review/deeper": FolderEntry(),
        "plugin/other/agents/x.md": a_file(),
        "plugin/demo/agents.md": a_file(),
    }

    inputs = build(entries)

    assert inputs == ExtensionInputs(
        project_json={SETTINGS: b'{"env": {"X": "1"}}\n'},
        agents=("coder.md", "planner.md"),
        skills=("audit", "review"),
    )


def test_links_skill_folder_when_it_holds_only_dotfiles() -> None:
    entries: dict[str, TreeEntry] = {
        f"{SKILLS}/review": FolderEntry(),
        f"{SKILLS}/review/.gitkeep": a_file(),
    }

    inputs = build(entries)

    assert isinstance(inputs, ExtensionInputs)
    assert inputs.skills == ("review",)


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(LinkEntry(target="elsewhere.json", outside=False), id="link"),
        pytest.param(FolderEntry(), id="folder"),
        pytest.param(OtherEntry(kind="fifo"), id="fifo"),
    ],
)
def test_reports_problem_when_sibling_not_regular(entry: TreeEntry) -> None:
    found = build({SETTINGS: entry, f"{AGENTS}/a.md": a_file()})

    assert found == (PathProblem(SETTINGS, "not a regular file"),)


def test_raises_when_sibling_content_not_read() -> None:
    with pytest.raises(ValueError, match=r"settings\.project\.json: content was not read"):
        build({SETTINGS: a_file()})


@pytest.mark.parametrize(
    ("path", "entry", "reason"),
    [
        pytest.param(f"{AGENTS}/a\\b.md", a_file(), "holds a backslash", id="backslash"),
        pytest.param(f"{SKILLS}/r\udcffx", FolderEntry(), "not UTF-8", id="surrogate"),
        pytest.param(f"{AGENTS}/a\nb.md", a_file(), "not printable", id="newline"),
        # E34: the first reason that matches wins.
        pytest.param(f"{AGENTS}/a\\\nb.md", a_file(), "holds a backslash", id="backslash-newline"),
    ],
)
def test_reports_problem_when_entry_name_unlinkable(
    path: str, entry: TreeEntry, reason: str
) -> None:
    found = build({path: entry, f"{AGENTS}/ok.md": a_file()})

    assert found == (PathProblem(path, f"cannot be linked: {reason}"),)


def test_reports_every_problem_when_several_inputs_bad() -> None:
    entries: dict[str, TreeEntry] = {
        SETTINGS: FolderEntry(),
        f"{SKILLS}/b\\x": FolderEntry(),
        # Out of path order on purpose: the result is sorted, whatever the snapshot's order.
        f"{AGENTS}/b\\x.md": a_file(),
        f"{AGENTS}/a\\x.md": a_file(),
    }

    found = build(entries)

    assert found == (
        PathProblem(SETTINGS, "not a regular file"),
        PathProblem(f"{AGENTS}/a\\x.md", "cannot be linked: holds a backslash"),
        PathProblem(f"{AGENTS}/b\\x.md", "cannot be linked: holds a backslash"),
        PathProblem(f"{SKILLS}/b\\x", "cannot be linked: holds a backslash"),
    )


def test_skips_unlinkable_name_when_entry_never_linked() -> None:
    entries: dict[str, TreeEntry] = {
        f"{AGENTS}/.a\\b.md": a_file(),
        f"{AGENTS}/x\\y": FolderEntry(),
        f"{SKILLS}/s\\t.md": a_file(),
        f"{SKILLS}/l\\k": LinkEntry(target="x", outside=False),
    }

    assert build(entries) == NO_EXTENSIONS


def test_returns_empty_value_when_nothing_present() -> None:
    assert build({}) == NO_EXTENSIONS
    assert ExtensionInputs(project_json={}, agents=(), skills=()) == NO_EXTENSIONS


@pytest.mark.parametrize(
    ("one", "other"),
    [
        pytest.param("evaluator.md", "evaluator.md", id="same"),
        pytest.param("Evaluator.md", "evaluator.md", id="case"),
        pytest.param("cafe\u0301.md", "caf\u00e9.md", id="nfd-nfc"),
        pytest.param("CAFE\u0301.md", "caf\u00e9.md", id="case-and-form"),
        pytest.param("STRASSE", "stra\u00dfe", id="casefold-not-lower"),
        # Folding the capital iota's NFC form gives a decomposed result: NFC again composes it.
        pytest.param("\u0399\u0308\u0301", "\u0390", id="nfc-after-casefold"),
        # Marks out of canonical order: folding U+0345 first gives a spacing iota, so without the
        # inner NFC the two forms of one name fold apart.
        pytest.param("\u03b1\u0345\u0301", "\u1fb4", id="nfc-before-casefold"),
    ],
)
def test_gives_one_key_when_names_differ_only_in_case_or_form(one: str, other: str) -> None:
    assert entry_name_key(one) == entry_name_key(other)


@pytest.mark.parametrize(
    ("one", "other"),
    [
        pytest.param("evaluator.md", "evaluator.mdx", id="suffix"),
        pytest.param("cafe.md", "caf\u00e9.md", id="accent"),
    ],
)
def test_gives_two_keys_when_names_differ(one: str, other: str) -> None:
    assert entry_name_key(one) != entry_name_key(other)
