"""The hooks' ``hub.json`` reader, as rendered at ``plugin/hub-workflow/hooks/stdlib_reader.py``.

Every read runs in a child, on ``hook_python`` (this interpreter and a real 3.9): the child loads
the rendered reader, prints ``dataclasses.asdict`` of what it read as JSON, and evaluates the
equality checks it is given with the reader's own classes. Those checks stay in the child because
dataclass equality holds only between classes of one loaded module, and a tuple is not a list.
"""

import ast
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import (
    Doctor,
    Guard,
    HubConfig,
    Platform,
    Project,
    Repo,
    Tracker,
)
from agent_hub.core.testing.builders import a_hub_document

READER = "plugin/hub-workflow/hooks/stdlib_reader.py"

# The optional fields of AC-1.5, as paths into the JSON document.
OPTIONAL_PATHS: tuple[tuple[str | int, ...], ...] = (
    ("project", "default_branch"),
    ("tracker", "ready_label"),
    ("tracker", "failed_label"),
    ("repos", 0, "role"),
    ("guard", "ask_before_edit"),
    ("guard", "deny_hosts"),
    ("guard", "deny_paths"),
    ("modules",),
    ("doctor", "rules"),
)

# argv: mode, reader file, hub.json path, checks (JSON: name -> [actual, expected] expressions,
# evaluated with the reader's names and ``hub_file``). Modes: ``import`` (a sibling import, as the
# hooks do), ``by_path`` (the registration the reader's docstring asks for, as the scripts do),
# ``cwd_gone`` (``import``, after the child removes its own working directory). Prints what it
# read, each check's result, and whether the model or pydantic came along.
READ = """
import dataclasses, importlib.util, json, os
mode, reader_file, hub_json, checks = sys.argv[1:5]
if mode == "by_path":
    spec = importlib.util.spec_from_file_location("hub_stdlib_reader", reader_file)
    reader = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = reader
    spec.loader.exec_module(reader)
else:
    import stdlib_reader as reader
if mode == "cwd_gone":
    os.rmdir(os.getcwd())
hub_file = reader.load_hub_file(hub_json)
scope = dict(vars(reader), hub_file=hub_file)
heavy = ("pydantic", "agent_hub.core.hub_config.model")
print(json.dumps({
    "hub_file": dataclasses.asdict(hub_file),
    "equal": {
        name: eval(actual, scope) == eval(expected, scope)
        for name, (actual, expected) in json.loads(checks).items()
    },
    "imported": [name for name in heavy if name in sys.modules],
}))
"""


type Reader = Callable[..., Any]


@pytest.fixture
def reader_file(rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig) -> Path:
    """The reader in a rendered demo hub."""
    return rendered_hub(demo_config) / READER


@pytest.fixture
def read(reader_file: Path, run_python: Callable[..., Any]) -> Reader:
    """Run ``READ`` on an interpreter: what the rendered reader makes of a ``hub.json`` path."""

    def run(
        python: str,
        hub_json: Path | str,
        *,
        mode: str = "import",
        checks: Mapping[str, tuple[str, str]] | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> Any:
        args = [mode, str(reader_file), str(hub_json), json.dumps(checks or {})]
        limit = {} if timeout is None else {"timeout": timeout}
        return run_python(python, READ, path=reader_file.parent, args=args, cwd=cwd, **limit)

    return run


def write_hub_file(directory: Path, document: object) -> Path:
    path = directory / "hub.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def value_at(data: Any, path: tuple[str | int, ...]) -> Any:
    for segment in path:
        data = data[segment]
    return data


def a_minimal_document() -> dict[str, Any]:
    """Required keys only: no ``$schema``, ``guard``, ``modules``, ``doctor``, ``repos[].role``."""
    document = a_hub_document()
    for key in ("$schema", "guard", "modules"):
        del document[key]
    return document


def test_returns_version_when_three_numbers(tmp_path: Path, hook_python: str, read: Reader) -> None:
    path = write_hub_file(tmp_path, a_hub_document() | {"platform": {"version": "0.2.0"}})

    hub_file = read(hook_python, path)["hub_file"]

    assert hub_file["platform"]["version"] == "0.2.0"
    assert hub_file["schema_version"] == 1
    assert hub_file["project"]["name"] == "demo"
    assert [repo["dir"] for repo in hub_file["repos"]] == ["demo-api"]


@pytest.mark.parametrize("version", ["1.2", "v1.2.3", "0.2.0\n", "０.2.0", "", "1.2.3.4"])
def test_reports_version_absent_when_not_three_numbers(
    tmp_path: Path, *, hook_python: str, read: Reader, version: str
) -> None:
    path = write_hub_file(tmp_path, a_hub_document() | {"platform": {"version": version}})

    hub_file = read(hook_python, path)["hub_file"]

    assert hub_file["platform"]["version"] is None
    assert hub_file["project"]["name"] == "demo"


def test_ignores_unknown_and_comment_keys_when_present(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    document = a_hub_document()
    document["_comment"] = "top"
    document["unknown"] = {"x": 1}
    document["project"]["_note"] = "p"
    document["project"]["extra"] = 1
    document["repos"][0]["_note"] = "r"
    document["modules"] = {"_comment": "m", "cloud": {"_note": "x", "region": "eu"}}
    document["doctor"] = {"_c": 1, "rules": {"_c": 2, "links.dead": {"_c": 3, "enabled": False}}}
    path = write_hub_file(tmp_path, document)

    reader = read(hook_python, path)["hub_file"]

    assert "unknown" not in reader
    assert "_comment" not in reader
    assert reader["project"]["name"] == "demo"
    assert "extra" not in reader["project"]
    assert "_note" not in reader["repos"][0]
    assert reader["modules"] == {"cloud": {"region": "eu"}}
    assert reader["doctor"] == {"rules": {"links.dead": {"enabled": False}}}


def test_matches_schema_defaults_when_hub_json_minimal(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    document = a_minimal_document()
    path = write_hub_file(tmp_path, document)

    model = HubConfig.model_validate(document).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    reader = read(hook_python, path)["hub_file"]

    for path_in_document in OPTIONAL_PATHS:
        assert value_at(reader, path_in_document) == value_at(model, path_in_document), (
            path_in_document
        )


def test_lists_every_optional_field_when_model_inspected() -> None:
    """``OPTIONAL_PATHS`` covers every key the model defaults, so a new one fails here first."""
    owners: tuple[tuple[tuple[str | int, ...], type[Any]], ...] = (
        ((), HubConfig),
        (("platform",), Platform),
        (("project",), Project),
        (("tracker",), Tracker),
        (("repos", 0), Repo),
        (("guard",), Guard),
        (("doctor",), Doctor),
    )
    defaulted = {
        (*prefix, field.alias or name)
        for prefix, model in owners
        for name, field in model.model_fields.items()
        if not field.is_required()
    }
    # ``$schema`` is an editor hint, not a default; ``guard`` and ``doctor`` are listed per field.
    containers = {("$schema",), ("guard",), ("doctor",)}

    assert defaulted - containers == set(OPTIONAL_PATHS)


def write_invalid_utf8(path: Path) -> None:
    path.write_bytes(b'{"project": {"name": "\xff"}}')


def write_json_syntax_error(path: Path) -> None:
    path.write_text('{"project": ', encoding="utf-8")


def write_top_level_array(path: Path) -> None:
    path.write_text(json.dumps([a_hub_document()]), encoding="utf-8")


def write_deep_nesting(path: Path) -> None:
    path.write_text("[" * 100_000, encoding="utf-8")


def make_directory(path: Path) -> None:
    path.mkdir()


def leave_missing(path: Path) -> None:
    del path


@pytest.mark.parametrize(
    "make_hub_file",
    [
        leave_missing,
        make_directory,
        write_invalid_utf8,
        write_json_syntax_error,
        write_top_level_array,
        write_deep_nesting,
    ],
)
def test_returns_defaults_when_file_unreadable_or_malformed(
    tmp_path: Path,
    *,
    hook_python: str,
    read: Reader,
    make_hub_file: Callable[[Path], None],
) -> None:
    hub_dir = tmp_path / "demo-hub"
    hub_dir.mkdir()
    path = hub_dir / "hub.json"
    make_hub_file(path)

    checks = {"defaults": ("hub_file", "HubFile(project=ProjectSection(name='demo-hub'))")}
    loaded = read(hook_python, path, checks=checks)

    assert loaded["equal"] == {"defaults": True}, loaded["hub_file"]


def test_keeps_other_fields_when_one_field_has_wrong_type(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    document = a_hub_document()
    document["tracker"]["ready_label"] = 5
    document["guard"]["deny_hosts"] = ["example.com", 7]
    document["platform"]["version"] = 2
    document["modules"] = {"cloud": True, "bench": {}}
    path = write_hub_file(tmp_path, document)

    checks = {
        "ready_label": ("hub_file.tracker.ready_label", "TrackerSection().ready_label"),
        "deny_hosts": ("hub_file.guard.deny_hosts", "()"),
        "ask_before_edit": ("hub_file.guard.ask_before_edit", "('demo-api/docs/adr',)"),
    }
    loaded = read(hook_python, path, checks=checks)
    hub_file = loaded["hub_file"]

    assert hub_file["modules"] == {"bench": {}}
    assert loaded["equal"]["ready_label"] is True
    assert hub_file["tracker"]["team"] == "DEM"
    assert loaded["equal"]["deny_hosts"] is True
    assert loaded["equal"]["ask_before_edit"] is True
    assert hub_file["platform"]["version"] is None
    assert hub_file["schema_version"] == 1

    document["repos"] = {}
    document["schema_version"] = True
    path = write_hub_file(tmp_path, document)
    loaded = read(hook_python, path, checks={"repos": ("hub_file.repos", "()")})
    hub_file = loaded["hub_file"]

    assert loaded["equal"]["repos"] is True
    assert hub_file["schema_version"] is None
    assert hub_file["project"]["name"] == "demo"


def test_falls_back_when_required_keys_missing(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    hub_dir = tmp_path / "acme-hub"
    hub_dir.mkdir()
    document = {
        "project": {"name": "", "hub_repo": 3},
        "tracker": [],
        "repos": [{"github": "acme/a"}, {"dir": ""}, {"dir": 5}, "b", {"dir": "b"}],
    }
    path = write_hub_file(hub_dir, document)

    checks = {
        "project": ("hub_file.project", "ProjectSection(name='acme-hub', hub_repo='')"),
        "tracker": ("hub_file.tracker", "TrackerSection()"),
        "repos": ("hub_file.repos", "(RepoEntry(dir='b'),)"),
    }
    loaded = read(hook_python, path, checks=checks)
    hub_file = loaded["hub_file"]

    assert loaded["equal"]["project"] is True
    assert loaded["equal"]["tracker"] is True
    assert hub_file["tracker"]["team"] == ""
    assert loaded["equal"]["repos"] is True
    assert hub_file["schema_version"] is None


def test_names_project_hub_when_directory_has_no_name(hook_python: str, read: Reader) -> None:
    hub_file = read(hook_python, "/hub.json")["hub_file"]

    assert hub_file["project"]["name"] == "hub"


def test_names_project_hub_when_working_directory_gone(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    # The child removes its own working directory, so a relative path cannot be resolved.
    gone = tmp_path / "gone"
    gone.mkdir()

    checks = {"defaults": ("hub_file", "HubFile()")}
    loaded = read(hook_python, "hub.json", mode="cwd_gone", checks=checks, cwd=gone)

    assert not gone.exists()
    assert loaded["equal"] == {"defaults": True}, loaded["hub_file"]


def make_fifo(path: Path) -> None:
    os.mkfifo(path)


def link_to_fifo(path: Path) -> None:
    fifo = path.with_name("hub.fifo")
    os.mkfifo(fifo)
    path.symlink_to(fifo)


@pytest.mark.parametrize("make_hub_file", [make_fifo, link_to_fifo])
def test_returns_defaults_when_path_not_regular_file(
    tmp_path: Path,
    *,
    hook_python: str,
    read: Reader,
    make_hub_file: Callable[[Path], None],
) -> None:
    hub_dir = tmp_path / "demo-hub"
    hub_dir.mkdir()
    path = hub_dir / "hub.json"
    make_hub_file(path)

    # Opening a FIFO with no writer blocks forever: the child's timeout shows the reader returned.
    checks = {"defaults": ("hub_file", "HubFile(project=ProjectSection(name='demo-hub'))")}
    loaded = read(hook_python, path, mode="by_path", checks=checks, timeout=10)

    assert loaded["equal"] == {"defaults": True}, loaded["hub_file"]


def test_parses_as_python39_when_source_checked(reader_file: Path) -> None:
    source = reader_file.read_text(encoding="utf-8")

    ast.parse(source, filename=str(reader_file), feature_version=(3, 9))


def test_imports_only_stdlib_when_source_checked(reader_file: Path) -> None:
    tree = ast.parse(reader_file.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import"
            imported.append(node.module or "")

    assert imported
    assert {name.split(".")[0] for name in imported} <= sys.stdlib_module_names


def test_loads_without_pydantic_when_imported_by_path(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    path = write_hub_file(tmp_path, a_minimal_document())

    loaded = read(hook_python, path, mode="by_path")

    assert loaded["imported"] == []
    assert loaded["hub_file"] == read(hook_python, path)["hub_file"]


def test_reads_same_values_when_run_on_python39(
    tmp_path: Path, python39: str, read: Reader
) -> None:
    document = a_hub_document()
    document["_comment"] = "x"
    document["doctor"] = {"rules": {"links.dead": {"enabled": False}}}
    valid = write_hub_file(tmp_path, document)
    malformed = tmp_path / "malformed" / "hub.json"
    malformed.parent.mkdir()
    malformed.write_text("[" * 100_000, encoding="utf-8")

    for path in (valid, malformed, tmp_path / "missing" / "hub.json"):
        loaded = read(python39, path, mode="by_path")

        assert loaded["imported"] == []
        assert loaded["hub_file"] == read(sys.executable, path)["hub_file"], path
