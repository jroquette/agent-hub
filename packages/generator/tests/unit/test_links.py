import pytest

from agent_hub.core.hub_files.rendered_file import Kind, Ownership, RenderedFile
from agent_hub.core.hub_files.rendered_link import RenderedLink
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.links import plugin_links, project_links


def a_file(path: str, **overrides: object) -> RenderedFile:
    fields: dict[str, object] = {
        "path": path,
        "content": b"x\n",
        "executable": False,
        "kind": Kind.GENERIC,
        "ownership": Ownership.MANAGED,
        "module": None,
    }
    fields.update(overrides)
    return RenderedFile.model_validate(fields)


def link_rows(links: tuple[RenderedLink, ...]) -> list[tuple[str, str]]:
    return [(link.path, link.target) for link in links]


def test_links_each_agent_file_when_plugin_rendered() -> None:
    files = [
        a_file("plugin/hub-workflow/agents/planner.md"),
        a_file("plugin/demo/agents/reviewer.md"),
        a_file("plugin/hub-workflow/agents/architect.md"),
        a_file("plugin/hub-workflow/NOTICE"),
        a_file("AGENTS.md"),
        # Shaped like plugin entries, but outside ``plugin/``: no link.
        a_file("templates/demo/agents/other.md"),
        a_file("templates/demo/skills/s/SKILL.md"),
    ]

    links = plugin_links(files)

    assert link_rows(links) == [
        (".claude/agents/architect.md", "../../plugin/hub-workflow/agents/architect.md"),
        (".claude/agents/planner.md", "../../plugin/hub-workflow/agents/planner.md"),
        (".claude/agents/reviewer.md", "../../plugin/demo/agents/reviewer.md"),
    ]


def test_links_each_skill_folder_once_when_plugin_rendered() -> None:
    files = [
        a_file("plugin/hub-workflow/skills/recall/SKILL.md"),
        a_file("plugin/hub-workflow/skills/recall/reference/sources.md"),
        a_file("plugin/demo/skills/deploy/SKILL.md"),
    ]

    links = plugin_links(files)

    assert link_rows(links) == [
        (".claude/skills/deploy", "../../plugin/demo/skills/deploy"),
        (".claude/skills/recall", "../../plugin/hub-workflow/skills/recall"),
    ]


def test_skips_dotfile_and_non_entry_file_when_plugin_rendered() -> None:
    files = [
        a_file("plugin/demo/agents/.gitkeep"),
        a_file("plugin/demo/skills/.gitkeep"),
        a_file("plugin/demo/skills/README.md"),
        a_file("plugin/demo/skills/.hidden/SKILL.md"),
        a_file("plugin/demo/agents/nested/deep.md"),
        a_file("plugin/demo/agents/kept.md"),
    ]

    links = plugin_links(files)

    # The one linked file is the anchor: dotfiles, the nested agent file and the flat file
    # under ``skills/`` (no skill folder) get nothing.
    assert link_rows(links) == [(".claude/agents/kept.md", "../../plugin/demo/agents/kept.md")]


def test_skips_skill_folder_when_it_holds_only_dotfiles() -> None:
    files = [
        a_file("plugin/demo/skills/empty/.gitkeep"),
        a_file("plugin/demo/skills/deploy/.gitkeep"),
        a_file("plugin/demo/skills/deploy/SKILL.md"),
    ]

    links = plugin_links(files)

    # ``deploy`` is linked through its real file; ``empty`` holds only a dotfile.
    assert link_rows(links) == [(".claude/skills/deploy", "../../plugin/demo/skills/deploy")]


@pytest.mark.parametrize(
    ("first", "second", "link_path"),
    [
        ("plugin/hub-workflow/agents/a.md", "plugin/demo/agents/a.md", ".claude/agents/a.md"),
        (
            "plugin/hub-workflow/skills/s/SKILL.md",
            "plugin/demo/skills/s/SKILL.md",
            ".claude/skills/s",
        ),
    ],
    ids=["agent", "skill"],
)
def test_raises_generator_error_when_two_plugins_share_entry(
    first: str, second: str, link_path: str
) -> None:
    with pytest.raises(GeneratorError) as raised:
        plugin_links([a_file(first), a_file(second)])

    assert type(raised.value) is GeneratorError
    message = str(raised.value)
    assert message.startswith(f"{link_path}: ")
    assert "plugin/hub-workflow" in message
    assert "plugin/demo" in message


def test_marks_links_generic_managed_when_derived() -> None:
    # A seeded, project-owned source still gets a generic, managed link with no module (Q-8).
    files = [
        a_file("plugin/demo/agents/a.md", kind=Kind.PROJECT_OWNED, ownership=Ownership.SEEDED),
        a_file("plugin/demo/skills/s/SKILL.md", kind=Kind.PROJECT_OWNED),
    ]

    links = plugin_links(files)

    assert len(links) == 2
    for link in links:
        assert type(link) is RenderedLink
        assert (link.kind, link.ownership, link.module) == (Kind.GENERIC, Ownership.MANAGED, None)


def test_links_project_entries_when_names_given() -> None:
    links = project_links(
        project="demo", agents=("reviewer.md", "notes"), skills=("review",), taken=()
    )

    # Names only (Q-17): whatever each name holds, it gets one link, sorted by path.
    assert link_rows(links) == [
        (".claude/agents/notes", "../../plugin/demo/agents/notes"),
        (".claude/agents/reviewer.md", "../../plugin/demo/agents/reviewer.md"),
        (".claude/skills/review", "../../plugin/demo/skills/review"),
    ]
    for link in links:
        assert type(link) is RenderedLink
        assert (link.kind, link.ownership, link.module) == (Kind.GENERIC, Ownership.MANAGED, None)
    assert project_links(project="demo", agents=(), skills=(), taken=()) == ()


def test_skips_project_name_when_base_link_taken() -> None:
    base = plugin_links(
        [
            a_file("plugin/hub-workflow/agents/planner.md"),
            a_file("plugin/hub-workflow/skills/recall/SKILL.md"),
        ]
    )

    links = project_links(
        project="demo",
        agents=("planner.md", "mine.md"),
        skills=("recall", "review"),
        taken={link.path for link in base},
    )

    # The base plugin keeps its link; the planner reports the clash (spec Q-17, plan E8).
    assert link_rows(links) == [
        (".claude/agents/mine.md", "../../plugin/demo/agents/mine.md"),
        (".claude/skills/review", "../../plugin/demo/skills/review"),
    ]
