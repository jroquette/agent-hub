import dataclasses
from collections import Counter
from collections.abc import Iterator
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.schema import SCHEMA_FILE, SCHEMA_PACKAGE
from agent_hub.core.hub_files.rendered_file import Kind, Ownership, RenderedFile
from agent_hub.generator.json_form import JsonValue
from agent_hub.generator.registry import REGISTRY, TemplateEntry, TemplateSource

GENERATOR_PACKAGE = "agent_hub.generator"
TEMPLATES_FOLDER = "templates"

# AC-3.11: the D5 path set, transcribed from docs/design/hub-generator.md § Classification and
# rendering. Each row cites the table row it comes from; every entry has no module (AC-3.12).
EXPECTED: dict[str, tuple[Kind, Ownership, str | None]] = {
    # Row "`.claude/settings.json` (merged with a seeded `.claude/settings.project.json`), …":
    # generic (+ project-owned), managed (+ seeded). AGH-19 spec D2: the seeded, project-owned part.
    ".claude/settings.project.json": (Kind.PROJECT_OWNED, Ownership.SEEDED, None),
    # Row "`hub.schema.json`, `AGENTS.md` and `CLAUDE.md` (base rules), `Makefile`, …,
    # `.pre-commit-config.yaml`, `.github/workflows/ci.yml`": generic, managed.
    ".github/workflows/ci.yml": (Kind.GENERIC, Ownership.MANAGED, None),
    ".pre-commit-config.yaml": (Kind.GENERIC, Ownership.MANAGED, None),
    "AGENTS.md": (Kind.GENERIC, Ownership.MANAGED, None),
    "CLAUDE.md": (Kind.GENERIC, Ownership.MANAGED, None),
    "Makefile": (Kind.GENERIC, Ownership.MANAGED, None),
    "hub.schema.json": (Kind.GENERIC, Ownership.MANAGED, None),
    # Row "`AGENTS.project.md` (project rules, created empty); `Makefile.project`; `README.md`;
    # `.gitignore` (base entries)": project-owned (`README.md`, `.gitignore` generic), seeded.
    ".gitignore": (Kind.GENERIC, Ownership.SEEDED, None),
    "AGENTS.project.md": (Kind.PROJECT_OWNED, Ownership.SEEDED, None),
    "Makefile.project": (Kind.PROJECT_OWNED, Ownership.SEEDED, None),
    "README.md": (Kind.GENERIC, Ownership.SEEDED, None),
    # Row "Brain skeleton: `brain/index.md`, `brain/now.md`, `brain/decisions/index.md`, folder
    # `.gitkeep`s, journal template": generic, seeded (the folders and template are spec Q9).
    "brain/_inbox/.gitkeep": (Kind.GENERIC, Ownership.SEEDED, None),
    "brain/decisions/index.md": (Kind.GENERIC, Ownership.SEEDED, None),
    "brain/domain/.gitkeep": (Kind.GENERIC, Ownership.SEEDED, None),
    "brain/features/.gitkeep": (Kind.GENERIC, Ownership.SEEDED, None),
    "brain/index.md": (Kind.GENERIC, Ownership.SEEDED, None),
    "brain/journal/.gitkeep": (Kind.GENERIC, Ownership.SEEDED, None),
    "brain/journal/_template.md": (Kind.GENERIC, Ownership.SEEDED, None),
    "brain/learnings/.gitkeep": (Kind.GENERIC, Ownership.SEEDED, None),
    "brain/now.md": (Kind.GENERIC, Ownership.SEEDED, None),
    "brain/playbooks/.gitkeep": (Kind.GENERIC, Ownership.SEEDED, None),
    # Row "`plugin/<project>/**` (project agents, skills, guard extension; empty folders hold a
    # `.gitkeep`)": project-owned, seeded (AGH-19 spec D2, "The rendered set").
    "plugin/@@{project_name}/.claude-plugin/plugin.json": (
        Kind.PROJECT_OWNED,
        Ownership.SEEDED,
        None,
    ),
    "plugin/@@{project_name}/agents/.gitkeep": (Kind.PROJECT_OWNED, Ownership.SEEDED, None),
    "plugin/@@{project_name}/hooks/project_guard.py": (Kind.PROJECT_OWNED, Ownership.SEEDED, None),
    "plugin/@@{project_name}/skills/.gitkeep": (Kind.PROJECT_OWNED, Ownership.SEEDED, None),
    # Row "`plugin/hub-workflow/**` (base agents, skills, hooks)": generic, managed (AGH-19 spec
    # "The rendered set"; the manifest and NOTICE are Q-10's).
    "plugin/hub-workflow/.claude-plugin/plugin.json": (Kind.GENERIC, Ownership.MANAGED, None),
    "plugin/hub-workflow/LICENSES/Apache-2.0.txt": (Kind.GENERIC, Ownership.MANAGED, None),
    "plugin/hub-workflow/LICENSES/MIT-compound-engineering-plugin.txt": (
        Kind.GENERIC,
        Ownership.MANAGED,
        None,
    ),
    "plugin/hub-workflow/NOTICE": (Kind.GENERIC, Ownership.MANAGED, None),
    "plugin/hub-workflow/agents/architect.md": (Kind.GENERIC, Ownership.MANAGED, None),
    "plugin/hub-workflow/agents/evaluator.md": (Kind.GENERIC, Ownership.MANAGED, None),
    "plugin/hub-workflow/agents/planner.md": (Kind.GENERIC, Ownership.MANAGED, None),
    "plugin/hub-workflow/agents/quality-reviewer.md": (Kind.GENERIC, Ownership.MANAGED, None),
    "plugin/hub-workflow/agents/requirements-analyst.md": (Kind.GENERIC, Ownership.MANAGED, None),
    "plugin/hub-workflow/agents/researcher.md": (Kind.GENERIC, Ownership.MANAGED, None),
    "plugin/hub-workflow/agents/spec-reviewer.md": (Kind.GENERIC, Ownership.MANAGED, None),
}

# AC-3.12 (spec D5 "Out"): later issues generate these, never AGH-10's registry. AGH-19
# (AC-4.29) brings `plugin/` and `.claude/` into scope.
OUT_OF_SCOPE_FILES = ("hub.json", "hub.lock", "agent")
OUT_OF_SCOPE_FOLDERS = (".claude-plugin/", "scripts/", "mk/")


def generator_sources() -> list[str]:
    return [
        entry.source.name
        for entry in REGISTRY
        if entry.source is not None and entry.source.package == GENERATOR_PACKAGE
    ]


def an_empty_object(config: HubConfig) -> JsonValue:
    return {}


def an_entry(**overrides: Any) -> TemplateEntry:
    fields: dict[str, Any] = {
        "path": "settings.json",
        "kind": Kind.GENERIC,
        "ownership": Ownership.MANAGED,
    }
    fields.update(overrides)
    return TemplateEntry(**fields)


# A project path segment's name in the templates folder (plan design 2: `plugin/project/…`).
PROJECT_SEGMENT = ("@@{project_name}", "project")


def source_name_of(path: str) -> str:
    """The template name the naming rule gives ``path``: ``@@{project_name}`` → ``project``,
    leading dots dropped (AGH-10 P2), ``.tmpl`` added.
    """
    segments = [PROJECT_SEGMENT[1] if s == PROJECT_SEGMENT[0] else s for s in path.split("/")]
    return f"{TEMPLATES_FOLDER}/" + "/".join(s.removeprefix(".") for s in segments) + ".tmpl"


def walk_files(folder: Traversable, prefix: str) -> Iterator[str]:
    for child in folder.iterdir():
        name = f"{prefix}/{child.name}"
        if child.is_dir():
            yield from walk_files(child, name)
        else:
            yield name


def test_describes_every_field_when_registry_walked() -> None:
    names = {field.name for field in dataclasses.fields(TemplateEntry)}

    assert names == {
        "path",
        "source",
        "build",
        "kind",
        "ownership",
        "module",
        "executable",
        "verbatim",
    }
    assert REGISTRY
    for entry in REGISTRY:
        # Spec Q-9: an entry has a template source or is built in code, never both or neither.
        assert (entry.source is None) == (entry.build is not None), entry.path
        if entry.source is not None:
            assert isinstance(entry.source, TemplateSource)
            assert entry.source.package
            assert entry.source.name
        else:
            assert callable(entry.build)
        assert isinstance(entry.path, str)
        assert isinstance(entry.kind, Kind)
        assert isinstance(entry.ownership, Ownership)
        assert entry.module is None or isinstance(entry.module, str)
        assert isinstance(entry.executable, bool)
        assert isinstance(entry.verbatim, bool)


def test_uses_unique_valid_paths_when_registry_walked() -> None:
    paths = [entry.path for entry in REGISTRY]

    assert len(paths) == len(set(paths))
    assert paths == sorted(paths)
    for entry in REGISTRY:
        rendered = RenderedFile(
            path=entry.path,
            content=b"",
            executable=entry.executable,
            kind=entry.kind,
            ownership=entry.ownership,
            module=entry.module,
        )
        assert rendered.path == entry.path


def test_finds_every_source_when_package_data_read() -> None:
    for entry in REGISTRY:
        if entry.source is None:
            # Spec Q-9: a generator-built JSON entry has no source at all.
            assert entry.build is not None, entry.path
            assert not entry.verbatim, entry.path
            continue
        package, name = entry.source
        if entry.path == "hub.schema.json":
            # Spec Q2: core's shipped schema, copied verbatim, never a second copy here.
            assert (package, name) == (SCHEMA_PACKAGE, SCHEMA_FILE)
            assert entry.verbatim
        else:
            assert package == GENERATOR_PACKAGE
            assert name.startswith(f"{TEMPLATES_FOLDER}/")
            assert not entry.verbatim
        assert files(package).joinpath(*name.split("/")).is_file(), name


def test_names_no_dotted_source_when_registry_walked() -> None:
    for entry in REGISTRY:
        if entry.source is None:
            continue
        segments = entry.source.name.split("/")
        assert not any(segment.startswith(".") for segment in segments), entry.source.name


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({}, "neither a source nor a builder"),
        (
            {
                "source": TemplateSource(GENERATOR_PACKAGE, "templates/x.tmpl"),
                "build": an_empty_object,
            },
            "both a source and a builder",
        ),
        ({"build": an_empty_object, "verbatim": True}, "a built entry cannot be verbatim"),
    ],
)
def test_requires_one_of_source_or_build_when_entry_built(
    fields: dict[str, Any], reason: str
) -> None:
    with pytest.raises(ValueError, match=reason) as raised:
        an_entry(**fields)

    assert "settings.json" in str(raised.value)


def test_accepts_entry_when_source_or_build_alone_given() -> None:
    source = TemplateSource(GENERATOR_PACKAGE, "templates/x.tmpl")

    built = an_entry(build=an_empty_object)
    templated = an_entry(source=source, verbatim=True)

    assert (built.source, built.build, built.verbatim) == (None, an_empty_object, False)
    assert (templated.source, templated.build, templated.verbatim) == (source, None, True)


def test_has_no_source_file_when_entry_built() -> None:
    folder = files(GENERATOR_PACKAGE)
    on_disk = set(walk_files(folder.joinpath(TEMPLATES_FOLDER), TEMPLATES_FOLDER))
    assert source_name_of(".github/workflows/ci.yml") in on_disk
    assert source_name_of("plugin/@@{project_name}/.claude-plugin/plugin.json") == (
        f"{TEMPLATES_FOLDER}/plugin/project/claude-plugin/plugin.json.tmpl"
    )

    for entry in REGISTRY:
        if entry.build is not None:
            assert entry.source is None, entry.path
            assert source_name_of(entry.path) not in on_disk, entry.path


def test_uses_every_template_file_once_when_data_folder_walked() -> None:
    sources = generator_sources()
    folder = files(GENERATOR_PACKAGE).joinpath(TEMPLATES_FOLDER)

    on_disk = set(walk_files(folder, TEMPLATES_FOLDER))

    assert [name for name, count in Counter(sources).items() if count > 1] == []
    assert set(sources) == on_disk


def test_matches_design_classification_when_compared() -> None:
    actual = {entry.path: (entry.kind, entry.ownership, entry.module) for entry in REGISTRY}

    assert actual == EXPECTED
    assert all(not entry.executable for entry in REGISTRY)


def test_excludes_out_of_scope_paths_when_outputs_listed() -> None:
    for entry in REGISTRY:
        assert entry.path not in OUT_OF_SCOPE_FILES
        assert not entry.path.startswith(OUT_OF_SCOPE_FOLDERS), entry.path


def test_has_no_module_entry_when_registry_walked() -> None:
    assert all(entry.kind is not Kind.MODULE for entry in REGISTRY)
    assert all(entry.module is None for entry in REGISTRY)
