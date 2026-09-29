import pytest
from pydantic import ValidationError

from agent_hub.core.hub_files.rendered_file import Kind, Ownership, RenderedFile
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.rendered_link import RenderedLink


def a_file(path: str) -> RenderedFile:
    return RenderedFile(
        path=path,
        content=b"x\n",
        executable=False,
        kind=Kind.GENERIC,
        ownership=Ownership.MANAGED,
        module=None,
    )


def a_link(path: str, target: str = "../x") -> RenderedLink:
    return RenderedLink(
        path=path, target=target, kind=Kind.GENERIC, ownership=Ownership.MANAGED, module=None
    )


def test_holds_files_and_links_when_built() -> None:
    files = (a_file("a.md"), a_file("b/c.md"))
    links = (a_link(".claude/agents/x.md", "../../b/c.md"), a_link(".claude/skills/y", "../../b"))

    hub = RenderedHub(files=files, links=links)

    assert hub.files == files
    assert hub.links == links


@pytest.mark.parametrize(
    ("files", "links"),
    [
        ((a_file("b.md"), a_file("a.md")), ()),
        ((), (a_link("d/b", "../a.md"), a_link("d/a", "../a.md"))),
    ],
)
def test_rejects_hub_when_paths_unsorted(
    files: tuple[RenderedFile, ...], links: tuple[RenderedLink, ...]
) -> None:
    with pytest.raises(ValidationError, match="sorted by path"):
        RenderedHub(files=files, links=links)


@pytest.mark.parametrize(
    ("files", "links"),
    [
        ((a_file("a.md"), a_file("a.md")), ()),
        ((), (a_link("d/a", "../a.md"), a_link("d/a", "../b.md"))),
    ],
)
def test_rejects_hub_when_path_repeated(
    files: tuple[RenderedFile, ...], links: tuple[RenderedLink, ...]
) -> None:
    with pytest.raises(ValidationError, match="appears more than once"):
        RenderedHub(files=files, links=links)


def test_rejects_hub_when_link_and_file_share_path() -> None:
    with pytest.raises(ValidationError, match="'d/a'.*both a file and a link"):
        RenderedHub(files=(a_file("d/a"),), links=(a_link("d/a", "../b.md"),))


@pytest.mark.parametrize(
    ("files", "links"),
    [
        ((a_file("L/x.md"),), (a_link("L", "b"),)),
        ((), (a_link("L", "b"), a_link("L/M", "../outside"))),
    ],
)
def test_rejects_hub_when_path_under_link(
    files: tuple[RenderedFile, ...], links: tuple[RenderedLink, ...]
) -> None:
    with pytest.raises(ValidationError, match="is under link 'L'"):
        RenderedHub(files=files, links=links)


def test_rejects_assignment_when_rendered_hub_frozen() -> None:
    hub = RenderedHub(files=(a_file("a.md"),), links=())

    with pytest.raises(ValidationError):
        hub.files = ()  # type: ignore[misc]
    with pytest.raises(ValidationError):
        hub.links = ()  # type: ignore[misc]
