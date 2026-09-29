import ast
import inspect
from typing import Any

import pytest
from pydantic import ValidationError

from agent_hub.core.hub_files import rendered_file
from agent_hub.core.hub_files.rendered_file import Kind, Ownership, RenderedFile

ALLOWED_IMPORT_ROOTS = {"enum", "posixpath", "typing", "pydantic"}


def rendered_file_fields(**overrides: object) -> dict[str, Any]:
    return {
        "path": "brain/index.md",
        "content": b"# Brain\n",
        "executable": False,
        "kind": Kind.GENERIC,
        "ownership": Ownership.SEEDED,
        "module": None,
    } | overrides


def test_lists_exact_values_when_kind_enumerated() -> None:
    assert [kind.value for kind in Kind] == ["generic", "module", "project-owned"]


def test_lists_exact_values_when_ownership_enumerated() -> None:
    assert [ownership.value for ownership in Ownership] == ["managed", "seeded"]


def test_declares_contract_fields_when_model_inspected() -> None:
    fields = {name: field.annotation for name, field in RenderedFile.model_fields.items()}

    assert fields == {
        "path": str,
        "content": bytes,
        "executable": bool,
        "kind": Kind,
        "ownership": Ownership,
        "module": str | None,
    }


def test_rejects_assignment_when_rendered_file_frozen() -> None:
    rendered = RenderedFile(**rendered_file_fields())

    with pytest.raises(ValidationError):
        rendered.path = "other.md"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        rendered.content = b""  # type: ignore[misc]


@pytest.mark.parametrize("path", ["/abs", "a/../b", "./a", "a\\b", "a/", "a//b", "", "a\x00b"])
def test_rejects_path_when_not_relative_normalized_posix(path: str) -> None:
    with pytest.raises(ValidationError) as caught:
        RenderedFile(**rendered_file_fields(path=path))

    assert [error["loc"] for error in caught.value.errors()] == [("path",)]


@pytest.mark.parametrize("path", ["brain/index.md", ".github/workflows/ci.yml"])
def test_accepts_path_when_relative_normalized_posix(path: str) -> None:
    rendered = RenderedFile(**rendered_file_fields(path=path))

    assert rendered.path == path


@pytest.mark.parametrize(
    ("kind", "module"),
    [(Kind.MODULE, None), (Kind.GENERIC, "bench"), (Kind.PROJECT_OWNED, "bench")],
)
def test_rejects_module_when_kind_disagrees(kind: Kind, module: str | None) -> None:
    with pytest.raises(ValidationError, match="module"):
        RenderedFile(**rendered_file_fields(kind=kind, module=module))


def test_rejects_module_when_id_unknown() -> None:
    with pytest.raises(ValidationError, match="slack"):
        RenderedFile(**rendered_file_fields(kind=Kind.MODULE, module="slack"))


@pytest.mark.parametrize("module", ["bench", "contract-sync"])
def test_accepts_module_when_kind_module_and_id_closed(module: str) -> None:
    rendered = RenderedFile(**rendered_file_fields(kind=Kind.MODULE, module=module))

    assert rendered.module == module


def test_imports_nothing_outside_core_when_source_parsed() -> None:
    tree = ast.parse(inspect.getsource(rendered_file))
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
