import ast
import inspect
from typing import Any

import pytest
from pydantic import ValidationError

from agent_hub.core.hub_files import rendered_link
from agent_hub.core.hub_files.rendered_file import Kind, Ownership
from agent_hub.core.hub_files.rendered_link import RenderedLink

ALLOWED_IMPORT_ROOTS = {"posixpath", "typing", "pydantic"}
AGENT_LINK = ".claude/agents/architect.md"


def rendered_link_fields(**overrides: object) -> dict[str, Any]:
    return {
        "path": AGENT_LINK,
        "target": "../../plugin/hub-workflow/agents/architect.md",
        "kind": Kind.GENERIC,
        "ownership": Ownership.MANAGED,
        "module": None,
    } | overrides


def test_declares_contract_fields_when_model_inspected() -> None:
    fields = {name: field.annotation for name, field in RenderedLink.model_fields.items()}

    assert fields == {
        "path": str,
        "target": str,
        "kind": Kind,
        "ownership": Ownership,
        "module": str | None,
    }


def test_rejects_assignment_when_rendered_link_frozen() -> None:
    link = RenderedLink(**rendered_link_fields())

    with pytest.raises(ValidationError):
        link.path = "other.md"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        link.target = "other.md"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("path", "target", "problem"),
    [
        (AGENT_LINK, "", "must not be empty"),
        (AGENT_LINK, "/x", "must be relative"),
        (AGENT_LINK, "a\\b", "must use / as the separator"),
        (AGENT_LINK, "../../../x", "resolves outside the hub"),
        ("a", "..", "resolves outside the hub"),
        (AGENT_LINK, "x\x00y", "must not contain NUL"),
        ("L", "L/../x", "must be a normalized POSIX path"),
        ("a", "x//y", "must be a normalized POSIX path"),
        ("a", "./x", "must be a normalized POSIX path"),
        ("a", "x/", "must be a normalized POSIX path"),
        ("a/b", "..", "must not point at the hub root or at itself"),
        ("L", ".", "must not point at the hub root or at itself"),
        ("a", "a", "must not point at the hub root or at itself"),
    ],
)
def test_rejects_target_when_empty_absolute_backslash_or_outside(
    path: str, target: str, problem: str
) -> None:
    with pytest.raises(ValidationError, match=problem) as caught:
        RenderedLink(**rendered_link_fields(path=path, target=target))

    assert [error["loc"] for error in caught.value.errors()] == [("target",)]


@pytest.mark.parametrize(
    ("path", "target"),
    [
        (AGENT_LINK, "../../plugin/hub-workflow/agents/architect.md"),
        (".claude/skills/kickoff", "../../plugin/hub-workflow/skills/kickoff"),
        ("a", "..cache/x"),
    ],
)
def test_accepts_target_when_inside_hub(path: str, target: str) -> None:
    link = RenderedLink(**rendered_link_fields(path=path, target=target))

    assert (link.path, link.target) == (path, target)


@pytest.mark.parametrize("path", ["/abs", "a/../b", "./a", "a\\b", "a/", "a//b", ""])
def test_rejects_path_when_not_relative_normalized_posix(path: str) -> None:
    with pytest.raises(ValidationError) as caught:
        RenderedLink(**rendered_link_fields(path=path, target="x"))

    assert [error["loc"] for error in caught.value.errors()] == [("path",)]


@pytest.mark.parametrize(
    ("kind", "module"),
    [
        (Kind.MODULE, None),
        (Kind.GENERIC, "bench"),
        (Kind.PROJECT_OWNED, "bench"),
        (Kind.MODULE, "slack"),
    ],
)
def test_rejects_module_when_kind_disagrees(kind: Kind, module: str | None) -> None:
    with pytest.raises(ValidationError, match="module"):
        RenderedLink(**rendered_link_fields(kind=kind, module=module))


def test_imports_nothing_outside_core_when_source_parsed() -> None:
    tree = ast.parse(inspect.getsource(rendered_link))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import"
            imported.append(node.module or "")
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

    assert imported
    assert [
        name
        for name in imported
        if name.split(".")[0] not in ALLOWED_IMPORT_ROOTS and not name.startswith("agent_hub.core.")
    ] == []
    assert {"open", "os", "pathlib"}.isdisjoint(names)
