import ast
import hashlib
import inspect
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.doctor.snapshot import module_makefiles
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.versions import PINNED_RELEASE_COMMAND
from agent_hub.core.hub_files.extension_inputs import NO_EXTENSIONS, ExtensionInputs
from agent_hub.core.hub_files.rendered_file import Kind, Ownership, RenderedFile
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.rendered_link import RenderedLink
from agent_hub.core.testing import builders
from agent_hub.core.testing.builders import a_conventions_document, a_hub_document, a_second_repo
from agent_hub.generator.built_json import managed_settings
from agent_hub.generator.errors import GeneratorError, TemplateError
from agent_hub.generator.hub_template import render_template
from agent_hub.generator.json_form import JsonValue
from agent_hub.generator.json_merge import MergeError, merge_json
from agent_hub.generator.placeholders import (
    MODULE_MAKEFILE_PATTERN,
    PLATFORM_REPOSITORY,
    substitution_mapping,
)
from agent_hub.generator.registry import REGISTRY, TemplateEntry, TemplateSource
from agent_hub.generator.render_hub import project_json_siblings, render_entries, render_hub

# AC-3.13: the D5 path set of docs/design/hub-generator.md, in code-point order; AC-4.1 adds
# AGH-19's rendered set (spec "The rendered set", for project `demo`).
DESIGN_PATHS = (
    ".claude/settings.json",
    ".claude/settings.project.json",
    ".github/workflows/ci.yml",
    ".gitignore",
    ".pre-commit-config.yaml",
    "AGENTS.md",
    "AGENTS.project.md",
    "CLAUDE.md",
    "Makefile",
    "Makefile.project",
    "README.md",
    "agent",
    "brain/_inbox/.gitkeep",
    "brain/decisions/index.md",
    "brain/domain/.gitkeep",
    "brain/features/.gitkeep",
    "brain/index.md",
    "brain/journal/.gitkeep",
    "brain/journal/_template.md",
    "brain/learnings/.gitkeep",
    "brain/now.md",
    "brain/playbooks/.gitkeep",
    "hub",
    "hub.schema.json",
    # AGH-17 D5: the demo selects `bench` and `cloud`.
    "mk/bench.mk",
    "mk/cloud.mk",
    "plugin/demo/.claude-plugin/plugin.json",
    "plugin/demo/agents/.gitkeep",
    "plugin/demo/hooks/project_guard.py",
    "plugin/demo/skills/.gitkeep",
    "plugin/hub-workflow/.claude-plugin/plugin.json",
    "plugin/hub-workflow/LICENSES/Apache-2.0.txt",
    "plugin/hub-workflow/LICENSES/MIT-compound-engineering-plugin.txt",
    "plugin/hub-workflow/NOTICE",
    "plugin/hub-workflow/agents/architect.md",
    "plugin/hub-workflow/agents/evaluator.md",
    "plugin/hub-workflow/agents/planner.md",
    "plugin/hub-workflow/agents/quality-reviewer.md",
    "plugin/hub-workflow/agents/requirements-analyst.md",
    "plugin/hub-workflow/agents/researcher.md",
    "plugin/hub-workflow/agents/spec-reviewer.md",
    "plugin/hub-workflow/hooks/guard.py",
    "plugin/hub-workflow/hooks/hooks.json",
    "plugin/hub-workflow/hooks/hubhooks.py",
    "plugin/hub-workflow/hooks/post_edit.py",
    "plugin/hub-workflow/hooks/pre_compact.py",
    "plugin/hub-workflow/hooks/project_guard_runner.py",
    "plugin/hub-workflow/hooks/session_end.py",
    "plugin/hub-workflow/hooks/session_start.py",
    "plugin/hub-workflow/hooks/stdlib_reader.py",
    "plugin/hub-workflow/hooks/stop_gate.py",
    "plugin/hub-workflow/skills/create-plan/SKILL.md",
    "plugin/hub-workflow/skills/feature/SKILL.md",
    "plugin/hub-workflow/skills/handoff/SKILL.md",
    "plugin/hub-workflow/skills/kickoff/SKILL.md",
    "plugin/hub-workflow/skills/learn/SKILL.md",
    "plugin/hub-workflow/skills/recall/SKILL.md",
    "plugin/hub-workflow/skills/research/SKILL.md",
    "scripts/cloud-setup.sh",
    "scripts/mine_transcripts.py",
    "scripts/recall_transcripts.py",
    "scripts/retro_metrics.py",
)
# AGH-19 spec "The rendered set": the base plugin's agents, by file stem, and its skills, by
# folder name.
BASE_AGENTS = (
    "architect",
    "evaluator",
    "planner",
    "quality-reviewer",
    "requirements-analyst",
    "researcher",
    "spec-reviewer",
)
BASE_SKILLS = ("create-plan", "feature", "handoff", "kickoff", "learn", "recall", "research")

GENERATOR_PACKAGE = "agent_hub.generator"
# A synthetic package of test templates, importable only while a test's fixture puts it on sys.path.
FIXTURE_PACKAGE = "render_hub_fixture_templates"

# Run in a child interpreter: renders the builder's demo config and prints ``render_digest``.
CHILD_SCRIPT = """\
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

{digest_source}

print(render_digest(render_hub(HubConfig.model_validate(a_hub_document()))))
"""


def render_digest(rendered: RenderedHub) -> str:
    """SHA-256 of a canonical dump: per file its fields, content length and bytes, then per link
    its path, target and classification (AC-4.28).

    Self-contained (imports inside), because the subprocess tests send its source to children.
    """
    import hashlib
    import json

    digest = hashlib.sha256()
    for file in rendered.files:
        fields = [
            file.path,
            file.kind.value,
            file.ownership.value,
            file.module,
            file.executable,
            len(file.content),
        ]
        digest.update(json.dumps(fields).encode("utf-8"))
        digest.update(file.content)
    for link in rendered.links:
        row = [link.path, link.target, link.kind.value, link.ownership.value, link.module]
        digest.update(json.dumps(row).encode("utf-8"))
    return digest.hexdigest()


def a_template_entry(path: str, name: str, **overrides: Any) -> TemplateEntry:
    fields: dict[str, Any] = {
        "path": path,
        "source": TemplateSource(GENERATOR_PACKAGE, name),
        "kind": Kind.GENERIC,
        "ownership": Ownership.SEEDED,
    }
    fields.update(overrides)
    return TemplateEntry(**fields)


def a_bench_entry() -> TemplateEntry:
    return a_template_entry(
        "mk/bench.mk",
        "templates/Makefile.project.tmpl",
        kind=Kind.MODULE,
        ownership=Ownership.MANAGED,
        module="bench",
    )


def a_config_with_modules(modules: dict[str, Any]) -> HubConfig:
    document = a_hub_document()
    document["modules"] = modules
    return HubConfig.model_validate(document)


@pytest.fixture
def fixture_templates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An importable package folder for test templates; tests add ``*.tmpl`` files to it."""
    package = tmp_path / "packages" / FIXTURE_PACKAGE
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path / "packages"))
    yield package
    sys.modules.pop(FIXTURE_PACKAGE, None)


def a_fixture_entry(
    package: Path, path: str, text: str, *, source_name: str | None = None
) -> TemplateEntry:
    """An entry for ``path`` whose source holds ``text``; ``source_name`` when ``path`` nests."""
    name = source_name or f"{path}.tmpl"
    (package / name).write_text(text, encoding="utf-8", newline="")
    return a_template_entry(path, name, source=TemplateSource(FIXTURE_PACKAGE, name))


def test_returns_design_paths_sorted_when_demo_rendered(demo_config: HubConfig) -> None:
    rendered = render_hub(demo_config)

    assert isinstance(rendered.files, tuple)
    assert tuple(file.path for file in rendered.files) == DESIGN_PATHS


def test_returns_rendered_hub_when_demo_rendered(demo_config: HubConfig) -> None:
    rendered = render_hub(demo_config)

    assert isinstance(rendered, RenderedHub)
    assert isinstance(rendered.links, tuple)
    assert all(type(link) is RenderedLink for link in rendered.links)
    # AC-4.6: exactly the 14 links of spec "The rendered set", sorted by path.
    assert [link.path for link in rendered.links] == [
        *(f".claude/agents/{name}.md" for name in BASE_AGENTS),
        *(f".claude/skills/{name}" for name in BASE_SKILLS),
    ]
    assert len(rendered.links) == 14
    assert all(
        (link.kind, link.ownership) == (Kind.GENERIC, Ownership.MANAGED) for link in rendered.links
    )
    assert {file.path for file in rendered.files}.isdisjoint(link.path for link in rendered.links)


def test_links_seven_agents_when_demo_rendered(demo_config: HubConfig) -> None:
    rendered = render_hub(demo_config)

    agent_links = [link for link in rendered.links if link.path.startswith(".claude/agents/")]
    assert [(link.path, link.target) for link in agent_links] == [
        (f".claude/agents/{name}.md", f"../../plugin/hub-workflow/agents/{name}.md")
        for name in BASE_AGENTS
    ]
    file_paths = {file.path for file in rendered.files}
    for link in agent_links:
        assert (link.kind, link.ownership, link.module) == (Kind.GENERIC, Ownership.MANAGED, None)
        # The target, read from the link's folder, is a rendered agent file.
        resolved = os.path.normpath(os.path.join(os.path.dirname(link.path), link.target))
        assert resolved in file_paths, link.path


def test_links_seven_skills_when_demo_rendered(demo_config: HubConfig) -> None:
    rendered = render_hub(demo_config)

    skill_links = [link for link in rendered.links if link.path.startswith(".claude/skills/")]
    # One link per skill folder, not per file.
    assert [(link.path, link.target) for link in skill_links] == [
        (f".claude/skills/{name}", f"../../plugin/hub-workflow/skills/{name}")
        for name in BASE_SKILLS
    ]
    file_paths = {file.path for file in rendered.files}
    for link in skill_links:
        assert (link.kind, link.ownership, link.module) == (Kind.GENERIC, Ownership.MANAGED, None)
        # The target, read from the link's folder, is a folder that holds the rendered SKILL.md.
        resolved = os.path.normpath(os.path.join(os.path.dirname(link.path), link.target))
        assert f"{resolved}/SKILL.md" in file_paths, link.path


def test_raises_generator_error_when_project_named_hub_workflow() -> None:
    # Spec Q-16 (AC-4.4): the project plugin's manifest lands on the base plugin's.
    with pytest.raises(GeneratorError) as raised:
        render_hub(a_config_named("hub-workflow"))

    assert type(raised.value) is GeneratorError
    assert str(raised.value).startswith("plugin/hub-workflow/.claude-plugin/plugin.json: ")


def test_copies_registry_classification_when_demo_rendered(demo_config: HubConfig) -> None:
    # An entry path may hold `@@{project_name}` (AGH-19 D2): look entries up by rendered path.
    name = demo_config.project.name
    entries = {entry.path.replace("@@{project_name}", name): entry for entry in REGISTRY}

    for file in render_hub(demo_config).files:
        entry = entries[file.path]
        assert type(file) is RenderedFile
        assert type(file.kind) is Kind
        assert type(file.ownership) is Ownership
        assert (file.kind, file.ownership, file.module, file.executable) == (
            entry.kind,
            entry.ownership,
            entry.module,
            entry.executable,
        )


def test_writes_nothing_when_rendered_in_empty_cwd(
    demo_config: HubConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    render_hub(demo_config)

    assert list(tmp_path.iterdir()) == []


def test_renders_module_entry_when_module_selected(demo_config: HubConfig) -> None:
    readme = a_template_entry("README.md", "templates/README.md.tmpl")

    rendered = render_entries(demo_config, [a_bench_entry(), readme])

    assert [(file.path, file.kind, file.module) for file in rendered.files] == [
        ("README.md", Kind.GENERIC, None),
        ("mk/bench.mk", Kind.MODULE, "bench"),
    ]


def test_renders_module_entry_when_aliased_module_selected() -> None:
    entry = a_template_entry(
        "mk/contract-sync.mk",
        "templates/Makefile.project.tmpl",
        kind=Kind.MODULE,
        ownership=Ownership.MANAGED,
        module="contract-sync",
    )

    document = a_hub_document()
    document["repos"].append(a_second_repo())
    document["modules"] = {"contract-sync": {"source": "demo-api", "target": "demo-web"}}

    rendered = render_entries(HubConfig.model_validate(document), [entry])

    assert [file.path for file in rendered.files] == ["mk/contract-sync.mk"]


def test_skips_module_entry_when_module_unselected(variant_config: HubConfig) -> None:
    readme = a_template_entry("README.md", "templates/README.md.tmpl")

    rendered = render_entries(variant_config, [a_bench_entry(), readme])

    assert [file.path for file in rendered.files] == ["README.md"]


def test_copies_core_schema_bytes_when_schema_rendered(demo_config: HubConfig) -> None:
    core_schema = files("agent_hub.core.hub_config").joinpath("hub.schema.json").read_bytes()

    schema = {file.path: file for file in render_hub(demo_config).files}["hub.schema.json"]

    assert schema.content == core_schema


def test_substitutes_config_values_when_template_rendered(
    demo_config: HubConfig, fixture_templates: Path
) -> None:
    entry = a_fixture_entry(
        fixture_templates, "NAME.md", "# @@{project_name} hub\r\n$HOME @@@@ é\n"
    )

    (rendered,) = render_entries(demo_config, [entry]).files

    # Strict UTF-8, no newline translation: a \r stays visible to the byte-form checks.
    assert rendered.content == "# demo hub\r\n$HOME @@ é\n".encode()


def test_returns_nothing_when_template_fails(
    demo_config: HubConfig, fixture_templates: Path
) -> None:
    good = a_fixture_entry(fixture_templates, "good.md", "@@{project_name}\n")
    broken = a_fixture_entry(fixture_templates, "broken.md", "@@{project_nmae}\n")

    with pytest.raises(TemplateError) as raised:
        render_entries(demo_config, [good, broken])

    assert raised.value.source == "broken.md.tmpl"
    assert raised.value.placeholder == "project_nmae"


def a_config_named(name: str) -> HubConfig:
    document = a_hub_document()
    document["project"]["name"] = name
    return HubConfig.model_validate(document)


def plugin_entries(package: Path, paths: Iterable[str]) -> list[TemplateEntry]:
    """One fixture entry per path; flat sources with no placeholder, so only the path renders."""
    return [
        a_fixture_entry(package, path, f"entry {index}\n", source_name=f"{index}.tmpl")
        for index, path in enumerate(paths)
    ]


def test_adds_one_link_when_entry_list_gains_agent_or_skill(
    demo_config: HubConfig, fixture_templates: Path
) -> None:
    base = (
        "plugin/hub-workflow/agents/architect.md",
        "plugin/hub-workflow/agents/.gitkeep",
        "plugin/hub-workflow/skills/recall/SKILL.md",
        "plugin/hub-workflow/skills/.gitkeep",
    )
    extra = (
        "plugin/demo/agents/reviewer.md",
        "plugin/demo/skills/deploy/SKILL.md",
        "plugin/demo/skills/deploy/reference.md",
    )

    before = render_entries(demo_config, plugin_entries(fixture_templates, base))
    after = render_entries(demo_config, plugin_entries(fixture_templates, base + extra))

    assert [(link.path, link.target) for link in before.links] == [
        (".claude/agents/architect.md", "../../plugin/hub-workflow/agents/architect.md"),
        (".claude/skills/recall", "../../plugin/hub-workflow/skills/recall"),
    ]
    added = set(after.links) - set(before.links)
    assert sorted((link.path, link.target) for link in added) == [
        (".claude/agents/reviewer.md", "../../plugin/demo/agents/reviewer.md"),
        (".claude/skills/deploy", "../../plugin/demo/skills/deploy"),
    ]
    assert len(after.links) == len(before.links) + 2
    assert {file.path for file in after.files}.isdisjoint(link.path for link in after.links)


@pytest.mark.parametrize("project_name", ["demo", "acme-tools"])
def test_substitutes_project_name_when_path_holds_placeholder(
    project_name: str, fixture_templates: Path
) -> None:
    entries = plugin_entries(
        fixture_templates,
        ("plugin/@@{project_name}/agents/reviewer.md", "plugin/@@{project_name}/skills/.gitkeep"),
    )

    rendered = render_entries(a_config_named(project_name), entries)

    assert [file.path for file in rendered.files] == [
        f"plugin/{project_name}/agents/reviewer.md",
        f"plugin/{project_name}/skills/.gitkeep",
    ]
    assert [(link.path, link.target) for link in rendered.links] == [
        (".claude/agents/reviewer.md", f"../../plugin/{project_name}/agents/reviewer.md"),
    ]


@pytest.mark.parametrize("placeholder", ["tracker_team", "project_nmae"])
def test_raises_template_error_when_path_holds_other_placeholder(
    placeholder: str, demo_config: HubConfig, fixture_templates: Path
) -> None:
    # ``tracker_team`` is a key of the text mapping: paths take ``project_name`` only.
    path = f"plugin/@@{{{placeholder}}}/agents/reviewer.md"
    entries = plugin_entries(fixture_templates, (path,))

    with pytest.raises(TemplateError) as raised:
        render_entries(demo_config, entries)

    assert raised.value.source == path
    assert raised.value.placeholder == placeholder


@pytest.mark.parametrize(
    ("project_name", "paths", "colliding"),
    [
        (
            "hub-workflow",
            (
                "plugin/hub-workflow/.claude-plugin/plugin.json",
                "plugin/@@{project_name}/.claude-plugin/plugin.json",
            ),
            "plugin/hub-workflow/.claude-plugin/plugin.json",
        ),
        (
            "demo",
            ("plugin/demo/agents/reviewer.md", ".claude/agents/reviewer.md"),
            ".claude/agents/reviewer.md",
        ),
        (
            "demo",
            ("plugin/hub-workflow/skills/recall/SKILL.md", "plugin/demo/skills/recall/SKILL.md"),
            ".claude/skills/recall",
        ),
        (
            "demo",
            ("plugin/demo/skills/recall/SKILL.md", ".claude/skills/recall/extra.md"),
            ".claude/skills/recall/extra.md",
        ),
    ],
    ids=["file-and-file", "file-and-link", "link-and-link", "file-under-link"],
)
def test_raises_generator_error_when_paths_collide(
    *, project_name: str, paths: tuple[str, ...], colliding: str, fixture_templates: Path
) -> None:
    entries = plugin_entries(fixture_templates, paths)

    with pytest.raises(GeneratorError) as raised:
        render_entries(a_config_named(project_name), entries)

    assert type(raised.value) is GeneratorError
    assert str(raised.value).startswith(f"{colliding}: ")


def a_manifest(config: HubConfig) -> dict[str, JsonValue]:
    return {"version": "0.1.0", "name": config.project.name, "note": "d\u00e9j\u00e0"}


@pytest.mark.parametrize("project_name", ["demo", "acme-tools"])
def test_writes_json_form_when_entry_built(project_name: str, fixture_templates: Path) -> None:
    built = TemplateEntry(
        path="plugin/@@{project_name}/.claude-plugin/plugin.json",
        build=a_manifest,
        kind=Kind.PROJECT_OWNED,
        ownership=Ownership.SEEDED,
    )
    entries = [built, *plugin_entries(fixture_templates, ("plugin/x/agents/a.md",))]

    rendered = render_entries(a_config_named(project_name), entries)

    file = rendered.files[0]
    assert file.path == f"plugin/{project_name}/.claude-plugin/plugin.json"
    # Spec Q-9: sorted keys, two-space indent, non-ASCII as UTF-8, final newline.
    lines = [
        "{",
        f'  "name": "{project_name}",',
        '  "note": "d\u00e9j\u00e0",',
        '  "version": "0.1.0"',
        "}",
    ]
    assert file.content == ("\n".join(lines) + "\n").encode()
    assert json.loads(file.content) == a_manifest(a_config_named(project_name))
    assert (file.kind, file.ownership, file.module, file.executable) == (
        Kind.PROJECT_OWNED,
        Ownership.SEEDED,
        None,
        False,
    )
    assert [other.path for other in rendered.files[1:]] == ["plugin/x/agents/a.md"]


# AGH-19 spec "The rendered set": the seeded, project-owned files, for project `<project>`.
SEEDED_PROJECT_PATHS = (
    ".claude/settings.project.json",
    "plugin/{project}/.claude-plugin/plugin.json",
    "plugin/{project}/agents/.gitkeep",
    "plugin/{project}/hooks/project_guard.py",
    "plugin/{project}/skills/.gitkeep",
)


@pytest.mark.parametrize("project_name", ["demo", "acme-tools"])
def test_seeds_project_paths_when_config_named(project_name: str) -> None:
    rendered = {file.path: file for file in render_hub(a_config_named(project_name)).files}

    seeded = sorted(
        path
        for path, file in rendered.items()
        if (file.kind, file.ownership) == (Kind.PROJECT_OWNED, Ownership.SEEDED)
        and path.startswith(("plugin/", ".claude/"))
    )
    assert seeded == [path.format(project=project_name) for path in SEEDED_PROJECT_PATHS]
    # No other project's folder: every plugin path outside the base plugin is this project's.
    project_plugin = [
        path
        for path in rendered
        if path.startswith("plugin/") and not path.startswith("plugin/hub-workflow/")
    ]
    assert project_plugin == [
        path.format(project=project_name) for path in SEEDED_PROJECT_PATHS[1:]
    ]
    manifest = json.loads(rendered[f"plugin/{project_name}/.claude-plugin/plugin.json"].content)
    assert manifest["name"] == project_name


def test_writes_empty_object_when_project_settings_rendered(
    demo_render: dict[str, RenderedFile],
) -> None:
    # Spec AC-4.8: the JSON byte form of `{}`.
    assert demo_render[".claude/settings.project.json"].content == b"{}\n"


# AGH-19 D2 and hub-generator.md § Hooks and plugin wiring: the extension's protocol words.
STUB_PROTOCOL_WORDS = ("check(event, cfg)", "None", '("deny", reason)', '("ask", reason)')


def test_defines_check_returning_none_when_stub_parsed(
    demo_render: dict[str, RenderedFile],
) -> None:
    stub = demo_render["plugin/demo/hooks/project_guard.py"].content.decode("utf-8")

    # The system python3 may be 3.9: the stub parses with 3.9's grammar.
    module = ast.parse(stub, feature_version=(3, 9))

    docstring = ast.get_docstring(module)
    assert docstring is not None
    for word in STUB_PROTOCOL_WORDS:
        assert word in docstring, word
    functions = [node for node in module.body if isinstance(node, ast.FunctionDef)]
    assert [function.name for function in functions] == ["check"]
    arguments = functions[0].args
    assert [argument.arg for argument in arguments.args] == ["event", "cfg"]
    assert (arguments.posonlyargs, arguments.kwonlyargs, arguments.defaults) == ([], [], [])
    assert (arguments.vararg, arguments.kwarg) == (None, None)
    body = functions[0].body
    if ast.get_docstring(functions[0]) is not None:
        body = body[1:]
    assert [ast.dump(statement) for statement in body] == [
        ast.dump(ast.parse("return None", feature_version=(3, 9)).body[0])
    ]


# AC-4.24 (Q-1): every rendered `.py` runs on the system python3, which may be 3.9. The scripts
# load the hooks' reader by path; the guard's runner loads the project extension by path (AC-4.14).
READER_PATH = "plugin/hub-workflow/hooks/stdlib_reader.py"
READER_MODULE = "hub_stdlib_reader"
EXTENSION_RUNNER = "plugin/hub-workflow/hooks/project_guard_runner.py"
# `sys.stdlib_module_names` is the running 3.14's: these stdlib modules came after 3.9 (What's New
# in Python 3.11 and 3.14), so a rendered file that imports one fails on the system python3.
POST_39_STDLIB = frozenset(
    {
        "annotationlib",
        "compression",
        "concurrent.interpreters",
        "string.templatelib",
        "tomllib",
        "wsgiref.types",
    }
)


def rendered_python(render: Mapping[str, RenderedFile]) -> dict[str, ast.Module]:
    """Every rendered `.py`, by output path, parsed with 3.9's grammar."""
    return {
        path: ast.parse(file.content, filename=path, feature_version=(3, 9))
        for path, file in render.items()
        if path.endswith(".py")
    }


def imported_names(module: ast.Module) -> Iterator[tuple[str, int]]:
    """Each imported module name with its relative level (0 for an absolute import)."""
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, 0
        elif isinstance(node, ast.ImportFrom):
            yield node.module or "", node.level


def string_constants(node: ast.AST) -> Iterator[str]:
    """The string constants under ``node`` in source order (``ast.walk`` is breadth-first)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    for child in ast.iter_child_nodes(node):
        yield from string_constants(child)


def by_path_loads(module: ast.Module) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "spec_from_file_location"
    ]


def test_parses_as_python39_when_rendered(demo_render: dict[str, RenderedFile]) -> None:
    parsed = rendered_python(demo_render)

    assert {path.rsplit("/", 1)[0] for path in parsed} == {
        "plugin/demo/hooks",
        "plugin/hub-workflow/hooks",
        "scripts",
    }


def test_imports_stdlib_or_siblings_when_rendered(demo_render: dict[str, RenderedFile]) -> None:
    parsed = rendered_python(demo_render)
    siblings: dict[str, set[str]] = {}
    for path in parsed:
        folder, name = path.rsplit("/", 1)
        siblings.setdefault(folder, set()).add(name.removesuffix(".py"))
    reader_loads = 0

    for path, module in parsed.items():
        folder = path.rsplit("/", 1)[0]
        for name, level in imported_names(module):
            assert level == 0, f"{path}: relative import of {name!r}"
            top = name.split(".")[0]
            assert top in sys.stdlib_module_names | siblings[folder], f"{path} imports {name}"
            newer = {added for added in POST_39_STDLIB if f"{name}.".startswith(f"{added}.")}
            assert not newer, f"{path} imports {name}, added after 3.9"
        for call in by_path_loads(module):
            if path == EXTENSION_RUNNER:
                continue
            assert folder == "scripts", f"{path} loads a module by path"
            [name, location] = call.args
            parts = list(string_constants(location))
            assert ast.literal_eval(name) == READER_MODULE, path
            assert "/".join(parts) == READER_PATH, path
            reader_loads += 1

    assert READER_PATH in demo_render
    assert reader_loads >= 1


def function_imports(module: ast.Module) -> Iterator[tuple[str, int]]:
    """Each import inside a function or lambda, with its line: it runs only when called."""
    for scope in ast.walk(module):
        if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            for node in ast.walk(scope):
                if isinstance(node, ast.Import | ast.ImportFrom):
                    yield ast.unparse(node), node.lineno


# The real-3.9 import test executes module-level imports only (class bodies included); an import
# inside a function would reach 3.9 untested. One exception, closed: the extension runner imports
# its sibling reader inside `answer`, so a missing or broken reader ends the run with exit 3 and a
# one-line cause (its docstring's protocol), and the guard extension tests run that path on 3.9.
FUNCTION_IMPORTS = {EXTENSION_RUNNER: ["from stdlib_reader import load_hub_file"]}


def test_imports_at_module_level_when_rendered(demo_render: dict[str, RenderedFile]) -> None:
    found = {
        path: [statement for statement, _ in function_imports(module)]
        for path, module in rendered_python(demo_render).items()
    }

    assert {path: imports for path, imports in found.items() if imports} == FUNCTION_IMPORTS


def test_takes_config_and_extensions_when_signature_read() -> None:
    parameters = inspect.signature(render_hub).parameters

    assert list(parameters) == ["config", "extensions"]
    assert parameters["extensions"].default is NO_EXTENSIONS


def test_renders_same_bytes_when_extensions_empty(demo_config: HubConfig) -> None:
    empty = ExtensionInputs(project_json={}, agents=(), skills=())

    rendered = render_hub(demo_config, empty)

    # Every file (bytes, bit, classification) and every link as the one-argument render.
    assert rendered == render_hub(demo_config)
    assert render_digest(rendered) == render_digest(render_entries(demo_config, REGISTRY))


def test_merges_settings_when_sibling_given(demo_config: HubConfig) -> None:
    sibling = b'{"permissions": {"allow": ["Bash(make *)"]}, "env": {"X": "1"}}'
    extensions = ExtensionInputs(
        project_json={".claude/settings.project.json": sibling}, agents=(), skills=()
    )
    plain = {file.path: file for file in render_hub(demo_config).files}

    rendered = render_hub(demo_config, extensions)

    files = {file.path: file for file in rendered.files}
    settings = files[".claude/settings.json"]
    assert settings.content == merge_json(
        managed_settings(demo_config), sibling, path=".claude/settings.project.json"
    )
    value = json.loads(settings.content)
    assert value["permissions"]["allow"][-1] == "Bash(make *)"
    assert value["env"] == {"X": "1"}
    assert settings.model_copy(update={"content": b""}) == plain[
        ".claude/settings.json"
    ].model_copy(update={"content": b""})
    # Only the merged file changes: the seeded sibling keeps its template bytes.
    assert {path: file for path, file in files.items() if path != ".claude/settings.json"} == {
        path: file for path, file in plain.items() if path != ".claude/settings.json"
    }
    assert rendered.links == render_hub(demo_config).links


def test_raises_merge_error_when_sibling_refused(demo_config: HubConfig) -> None:
    extensions = ExtensionInputs(
        project_json={".claude/settings.project.json": b'{"disableAllHooks": true}'},
        agents=(),
        skills=(),
    )

    with pytest.raises(MergeError, match=r"^\.claude/settings\.project\.json: disableAllHooks: "):
        render_hub(demo_config, extensions)


@pytest.mark.parametrize(
    ("config_name", "expected"),
    [
        ("demo_config", (".claude/settings.project.json",)),
        ("variant_config", (".claude/settings.project.json",)),
        (
            "all_modules_config",
            (".claude-plugin/marketplace.project.json", ".claude/settings.project.json"),
        ),
    ],
    ids=["demo", "no-module", "all-modules"],
)
def test_lists_marketplace_sibling_only_when_marketplace_selected(
    config_name: str, expected: tuple[str, ...], request: pytest.FixtureRequest
) -> None:
    # AGH-17 D4: the marketplace pair renders, and merges, only with the module selected.
    assert project_json_siblings(request.getfixturevalue(config_name)) == expected


@pytest.mark.parametrize(
    "path", ["AGENTS.project.json", ".claude/other.project.json", "plugin/demo/x.project.json"]
)
def test_raises_value_error_when_sibling_not_rendered_pair(
    demo_config: HubConfig, path: str
) -> None:
    extensions = ExtensionInputs(project_json={path: b"{}"}, agents=(), skills=())

    # A caller bug: only a seeded built ``X.project.json`` next to a managed built ``X.json``.
    with pytest.raises(ValueError, match=re.escape(path)):
        render_hub(demo_config, extensions)


def a_json_pair(
    *, sibling: Ownership, target: Ownership, sibling_built: bool = True, target_built: bool = True
) -> list[TemplateEntry]:
    """A ``x.project.json`` and ``x.json`` entry pair: each built or from a template source."""

    def entry(path: str, ownership: Ownership, *, built: bool) -> TemplateEntry:
        if built:
            return TemplateEntry(
                path=path, build=lambda _: {"a": 1}, kind=Kind.GENERIC, ownership=ownership
            )
        return a_template_entry(path, "templates/Makefile.project.tmpl", ownership=ownership)

    return [
        entry("x.project.json", sibling, built=sibling_built),
        entry("x.json", target, built=target_built),
    ]


def test_merges_custom_pair_when_sibling_seeded_and_target_managed(
    demo_config: HubConfig,
) -> None:
    entries = a_json_pair(sibling=Ownership.SEEDED, target=Ownership.MANAGED)
    extensions = ExtensionInputs(project_json={"x.project.json": b'{"b": 2}'}, agents=(), skills=())

    rendered = {file.path: file for file in render_entries(demo_config, entries, extensions).files}

    assert json.loads(rendered["x.json"].content) == {"a": 1, "b": 2}


@pytest.mark.parametrize(
    "entries",
    [
        a_json_pair(sibling=Ownership.MANAGED, target=Ownership.MANAGED),
        a_json_pair(sibling=Ownership.SEEDED, target=Ownership.SEEDED),
        a_json_pair(sibling=Ownership.SEEDED, target=Ownership.MANAGED, sibling_built=False),
        a_json_pair(sibling=Ownership.SEEDED, target=Ownership.MANAGED, target_built=False),
        a_json_pair(sibling=Ownership.SEEDED, target=Ownership.MANAGED)[:1],
    ],
    ids=[
        "sibling-managed",
        "target-seeded",
        "sibling-from-template",
        "target-from-template",
        "target-not-rendered",
    ],
)
def test_raises_value_error_when_custom_pair_not_seeded_and_managed_built(
    demo_config: HubConfig, entries: list[TemplateEntry]
) -> None:
    extensions = ExtensionInputs(project_json={"x.project.json": b"{}"}, agents=(), skills=())

    with pytest.raises(ValueError, match=r"^x\.project\.json: not a seeded sibling "):
        render_entries(demo_config, entries, extensions)


def test_links_project_entries_when_extensions_name_them(demo_config: HubConfig) -> None:
    extensions = ExtensionInputs(
        project_json={}, agents=("planner.md", "reviewer.md"), skills=("review",)
    )
    plain = render_hub(demo_config)

    rendered = render_hub(demo_config, extensions)

    links = {link.path: link for link in rendered.links}
    assert [link.path for link in rendered.links] == sorted(links)
    assert set(links) - {link.path for link in plain.links} == {
        ".claude/agents/reviewer.md",
        ".claude/skills/review",
    }
    assert links[".claude/agents/reviewer.md"].target == "../../plugin/demo/agents/reviewer.md"
    assert links[".claude/skills/review"].target == "../../plugin/demo/skills/review"
    # A name the base plugin also has keeps the base link (the planner reports the clash).
    assert links[".claude/agents/planner.md"].target == (
        "../../plugin/hub-workflow/agents/planner.md"
    )
    assert rendered.files == plain.files


def test_renders_same_bytes_when_rendered_twice(demo_config: HubConfig) -> None:
    first = render_hub(demo_config)
    second = render_hub(demo_config)

    assert first == second
    assert render_digest(first) == render_digest(second)


def test_renders_same_digest_when_hash_seed_and_timezone_differ(
    demo_config: HubConfig, tmp_path: Path
) -> None:
    script = CHILD_SCRIPT.format(digest_source=inspect.getsource(render_digest))
    digests = []
    for hash_seed, timezone in (("1", "UTC"), ("2", "Asia/Tokyo")):
        # A cleaned environment: only the two inputs under test reach the child.
        completed = subprocess.run(  # noqa: S603 - this interpreter, a fixed script, no shell
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            cwd=tmp_path,
            env={"PYTHONHASHSEED": hash_seed, "TZ": timezone},
        )
        assert completed.returncode == 0, completed.stderr
        digests.append(completed.stdout.strip())

    assert digests == [render_digest(render_hub(demo_config))] * 2


def test_renders_same_bytes_when_module_order_differs() -> None:
    bench_first = a_config_with_modules({"bench": {}, "cloud": {}})
    cloud_first = a_config_with_modules({"cloud": {}, "bench": {}})

    assert render_hub(bench_first) == render_hub(cloud_first)
    assert render_digest(render_hub(bench_first)) == render_digest(render_hub(cloud_first))


def test_renders_same_bytes_when_module_keys_reordered(all_modules_config: HubConfig) -> None:
    document = all_modules_config.model_dump(mode="json", by_alias=True, exclude_none=True)
    document["modules"] = dict(reversed(document["modules"].items()))
    reordered = HubConfig.model_validate(document)

    renders = [render_hub(config) for config in (all_modules_config, reordered) for _ in range(2)]

    assert all(render == renders[0] for render in renders)
    assert {render_digest(render) for render in renders} == {render_digest(renders[0])}


# AGH-17 AC-17.13 (Q-10): constructs of bash 4 or later, which macOS's /bin/bash (3.2) rejects or
# runs differently, and tracing (``set -x`` would print a token a command line holds). The list is
# partial: a pattern scan of the commonest forms, not a parser; `bash -n` on bash 5 cannot catch
# them, and AC-17.24 runs the scripts on a real 3.2.
BASH_FOUR = {
    "declare -A": re.compile(r"\b(?:declare|typeset|local)\s+-[a-zA-Z]*A"),
    "declare -n": re.compile(r"\b(?:declare|typeset|local)\s+-[a-zA-Z]*n"),
    "declare -g": re.compile(r"\b(?:declare|typeset)\s+-[a-zA-Z]*g"),
    "mapfile": re.compile(r"\bmapfile\b"),
    "readarray": re.compile(r"\breadarray\b"),
    "coproc": re.compile(r"\bcoproc\b"),
    "case modification": re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*(?:\[[^]]*\])?(?:,|\^)"),
    "[[ -v": re.compile(r"\[\[\s+-v\b"),
    "&>>": re.compile(r"&>>"),
    "|&": re.compile(r"\|&"),
    ";& or ;;&": re.compile(r";;?&"),
    "negative index": re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\[\s*-[0-9]"),
    "negative length": re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*(?:\[[^]]*\])?:[^}:]*:\s*-[0-9]"),
    "${var@op}": re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*(?:\[[^]]*\])?@[A-Za-z]\}"),
    "shopt -s globstar": re.compile(r"\bshopt\s+-s\b[^\n;]*\bglobstar\b"),
    "wait -n": re.compile(r"\bwait\s+-n\b"),
    "EPOCHSECONDS": re.compile(r"\bEPOCH(?:SECONDS|REALTIME)\b"),
    "printf %(...)T": re.compile(r"%\([^)]*\)T"),
    "read -i or -N": re.compile(r"\bread\b[^\n;|&]*\s-[a-zA-Z]*[iN]\b"),
    "set -x": re.compile(r"\bset\s+(?:-[a-wyzA-Z]*x|-o\s+xtrace)"),
}


def test_finds_each_construct_when_bash_four_list_read() -> None:
    samples = {
        "declare -A": "declare -A seen=()",
        "declare -n": "local -n ref=name",
        "declare -g": "declare -g name=x",
        "mapfile": "mapfile -t lines < f",
        "readarray": "readarray -t lines < f",
        "coproc": "coproc cat",
        "case modification": 'echo "${name,,}" "${name^^}"',
        "[[ -v": "[[ -v name ]]",
        "&>>": "cmd &>> log",
        "|&": "cmd |& tee log",
        ";& or ;;&": "case $x in a) echo a ;& b) echo b ;;& esac",
        "negative index": 'echo "${items[-1]}"',
        "negative length": 'echo "${name:0:-1}"',
        "${var@op}": 'echo "${name@Q}"',
        "shopt -s globstar": "shopt -s nullglob globstar",
        "wait -n": "wait -n",
        "EPOCHSECONDS": 'echo "$EPOCHSECONDS" "$EPOCHREALTIME"',
        "printf %(...)T": "printf '%(%Y-%m-%d)T' -1",
        "read -i or -N": "read -e -i default name; read -N 1 key",
        "set -x": "set -eux",
    }

    assert {
        name: bool(BASH_FOUR[name].search(text)) for name, text in samples.items()
    } == dict.fromkeys(BASH_FOUR, True)
    # Bash 3.2 forms that look alike stay allowed.
    for text in (
        'echo "${name:-a,b}" "${#items[@]}" "${name%,*}" "${name: -1}" "${name:1:2}"',
        "set -euo pipefail",
        "a || b && c 2>&1",
        "case $x in a) echo a ;; esac",
        'read -r -n 1 key; wait "$pid"; declare -r name=x; shopt -s nullglob',
        "printf '%s\\n' x",
    ):
        assert not [name for name, pattern in BASH_FOUR.items() if pattern.search(text)], text


def test_uses_no_bash_four_construct_when_module_scripts_rendered(
    all_modules_config: HubConfig,
    shell_scripts: Callable[[Iterable[RenderedFile]], list[str]],
) -> None:
    rendered = render_hub(all_modules_config).files
    # Scripts only: make runs the recipes of `Makefile` and `mk/*.mk` on /bin/sh, not bash.
    paths = shell_scripts(rendered)
    assert {"scripts/cloud-setup.sh", "scripts/contract-sync.sh", "hub", "agent"} <= set(paths)

    found = [
        (file.path, name)
        for file in rendered
        if file.path in paths
        for name, pattern in BASH_FOUR.items()
        if pattern.search(file.content.decode("utf-8"))
    ]

    assert found == []


def test_changes_digest_when_link_target_or_ownership_differs() -> None:
    link = RenderedLink(
        path=".claude/agents/a.md",
        target="../../plugin/hub-workflow/agents/a.md",
        kind=Kind.GENERIC,
        ownership=Ownership.MANAGED,
        module=None,
    )
    other_target = link.model_copy(update={"target": "../../plugin/demo/agents/a.md"})
    other_ownership = link.model_copy(update={"ownership": Ownership.SEEDED})

    digests = [
        render_digest(RenderedHub(files=(), links=links))
        for links in ((), (link,), (other_target,), (other_ownership,))
    ]

    assert len(set(digests)) == len(digests)


# AC-3.18 (Q5): the base Makefile's targets; `bench` and `bench-validate` go to mk/bench.mk.
BASE_TARGETS = (
    "brain-brief",
    "agent",
    "worktree",
    "worktree-remove",
    "next",
    "run-issue",
    "usage",
    "mine",
    "retro",
    "check",
    "help",
)
# AC-3.18: the hub scripts that become `hub` commands or doctor rules; no template names them.
PORTED_SCRIPTS = (
    "scripts/hubconfig.py",
    "scripts/worktree.sh",
    "scripts/brief.py",
    "scripts/agent_runner.py",
    "scripts/bench.py",
    "scripts/agent_config_lint.py",
    "scripts/features_check.py",
)
MAKE_TARGET = re.compile(r"^([a-z][a-z0-9-]*):", re.MULTILINE)
# The version a synthetic hub.json pins for the run tests; the shims must read it at run time.
RUN_VERSION = "4.5.6"
# Make variables the outer `make check-fast` exports (or a user sets); they would leak into the
# make under test.
MAKE_ENV_LEAKS = ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "GNUMAKEFLAGS", "MAKEFILES")


def text_of(config: HubConfig, path: str) -> str:
    return {file.path: file for file in render_hub(config).files}[path].content.decode("utf-8")


def template_texts() -> Iterator[tuple[str, str]]:
    """``(path, text)`` of every file under the templates data folder, walked recursively.

    ``path`` is relative to ``templates/`` (``brain/decisions/index.md.tmpl``), so files sharing
    a name in different folders are all scanned.
    """
    pending = [(files(GENERATOR_PACKAGE).joinpath("templates"), "")]
    while pending:
        folder, prefix = pending.pop()
        for child in folder.iterdir():
            if child.is_dir():
                pending.append((child, f"{prefix}{child.name}/"))
            else:
                yield f"{prefix}{child.name}", child.read_text(encoding="utf-8")


def recipe_lines(makefile: str, target: str) -> list[str]:
    """The recipe lines of ``target`` (tab-indented, after its rule line), tab stripped."""
    lines = makefile.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith(f"{target}:"))
    recipe = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        recipe.append(line[1:])
    return recipe


def pinned_source(version: str) -> str:
    """The ``--from`` source inside core's pinned-release command for ``version``."""
    command = PINNED_RELEASE_COMMAND.format(version=version).split()
    return command[command.index("--from") + 1]


def test_writes_links_as_symlinks_when_tree_written(
    rendered_tree: Callable[[RenderedHub], Path],
) -> None:
    agent = RenderedFile(
        path="plugin/p/agents/a.md",
        content=b"# a\n",
        executable=False,
        kind=Kind.GENERIC,
        ownership=Ownership.MANAGED,
        module=None,
    )
    link = RenderedLink(
        path=".claude/agents/a.md",
        target="../../plugin/p/agents/a.md",
        kind=Kind.GENERIC,
        ownership=Ownership.MANAGED,
        module=None,
    )

    root = rendered_tree(RenderedHub(files=(agent,), links=(link,)))

    written = root / ".claude" / "agents" / "a.md"
    assert written.is_symlink()
    assert os.readlink(written) == "../../plugin/p/agents/a.md"
    assert written.read_bytes() == b"# a\n"


def a_hub_tree(config: HubConfig, rendered_tree: Callable[[RenderedHub], Path]) -> Path:
    """The render written to disk, next to a synthetic hub.json pinned to ``RUN_VERSION``."""
    root = rendered_tree(render_hub(config))
    document = a_hub_document()
    document["platform"]["version"] = RUN_VERSION
    (root / "hub.json").write_text(json.dumps(document), encoding="utf-8")
    return root


def run_env(fake_uv_bin: Path, overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """This environment minus the make leaks, fake uv first on PATH, then ``overrides``."""
    env = {name: value for name, value in os.environ.items() if name not in MAKE_ENV_LEAKS}
    env["PATH"] = f"{fake_uv_bin}{os.pathsep}{env.get('PATH', '')}"
    env.update(overrides or {})
    return env


def run_make(
    root: Path,
    fake_uv_bin: Path,
    *arguments: str,
    env_overrides: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    make = shutil.which("make")
    assert make is not None, "AC-3.18 runs the rendered Makefile: install GNU make"
    return subprocess.run(  # noqa: S603 - absolute make, fixed arguments, no shell
        [make, "-f", "Makefile", *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        cwd=root,
        env=run_env(fake_uv_bin, env_overrides),
    )


def logged_calls(fake_uv_bin: Path) -> list[str]:
    log = fake_uv_bin / "uvx.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_defines_base_targets_when_makefile_rendered(demo_config: HubConfig) -> None:
    targets = MAKE_TARGET.findall(text_of(demo_config, "Makefile"))

    assert sorted(targets) == sorted(BASE_TARGETS)
    assert "bench" not in targets
    assert "bench-validate" not in targets


def test_calls_hub_through_shim_when_recipes_read(demo_config: HubConfig) -> None:
    makefile = text_of(demo_config, "Makefile")

    assert "@$(HUB) brief" in recipe_lines(makefile, "brain-brief")
    assert "@$(HUB) next" in recipe_lines(makefile, "next")
    # Names are checked, then passed single-quoted (never re-expanded by make).
    assert recipe_lines(makefile, "worktree")[1:] == [
        "@$(call hub_check_name,worktree,NAME); $(call hub_check_name,worktree,ONLY); \\",
        "$(HUB) worktree $(call hub_quote,NAME) $(if $(value ONLY),--only $(call hub_quote,ONLY))",
    ]
    assert recipe_lines(makefile, "worktree-remove")[1:] == [
        "@$(call hub_check_name,worktree-remove,NAME); "
        "$(call hub_check_name,worktree-remove,ONLY); \\",
        "$(HUB) worktree --remove $(call hub_quote,NAME) "
        "$(if $(value ONLY),--only $(call hub_quote,ONLY))",
    ]
    assert recipe_lines(makefile, "run-issue")[1:] == [
        "@$(call hub_check_name,run-issue,ISSUE); $(call hub_check_name,run-issue,REPO); \\",
        "$(call hub_check_name,run-issue,BUDGET); $(call hub_check_name,run-issue,FROM); \\",
        "$(HUB) run $(call hub_quote,ISSUE) --repo $(call hub_quote,REPO) $(if $(LIVE),--live)"
        " $(if $(value BUDGET),--budget $(call hub_quote,BUDGET))"
        " $(if $(value FROM),--from $(call hub_quote,FROM))",
    ]
    assert recipe_lines(makefile, "check")[0] == "@$(HUB) doctor"
    assert "@if [ -d tests ]; then python3 -m unittest discover -s tests -q; fi" in (
        recipe_lines(makefile, "check")
    )
    assert recipe_lines(makefile, "agent") == ["./agent"]
    # The protocol is the ./hub shim's (test_hub_shim.py); the Makefile holds no copy of it.
    # The shim by the hub's absolute path, so a recipe that changes folder still finds it.
    assert "HUB := '$(subst ','\\'',$(CURDIR))/hub'" in makefile.splitlines()
    assert "uvx" not in makefile


def test_includes_modules_then_project_when_makefile_rendered(demo_config: HubConfig) -> None:
    lines = text_of(demo_config, "Makefile").splitlines()

    bench = lines.index("include mk/bench.mk")
    cloud = lines.index("include mk/cloud.mk")
    assert bench < cloud
    assert [line for line in lines if line.strip()][-1] == "-include Makefile.project"
    assert lines.index("-include Makefile.project") > cloud


def test_includes_no_module_when_none_selected(variant_config: HubConfig) -> None:
    lines = text_of(variant_config, "Makefile").splitlines()

    assert not [line for line in lines if "mk/" in line and "include" in line]
    assert [line for line in lines if line.strip()][-1] == "-include Makefile.project"


def test_names_no_ported_script_when_templates_read() -> None:
    texts = dict(template_texts())

    assert {"brain/index.md.tmpl", "brain/decisions/index.md.tmpl"} <= set(texts)
    for name, text in texts.items():
        for script in PORTED_SCRIPTS:
            assert script not in text, f"{name} names {script}"


# AC-4.10 (Q-2): the scripts and hooks read `hub.json` through the hooks' reader, so no template
# imports, loads or names the hub's own loader module.
def test_names_no_hubconfig_when_templates_read() -> None:
    texts = dict(template_texts())

    assert {
        "scripts/mine_transcripts.py.tmpl",
        "scripts/recall_transcripts.py.tmpl",
        "scripts/retro_metrics.py.tmpl",
    } <= set(texts)
    for name, text in texts.items():
        assert "hubconfig" not in text, name


# AC-4.19 (Q-15): the hub scripts that `hub` commands replace. No rendered agent or skill names
# one, with or without its folder (the hub's planner also named `features_check.py` bare).
HUB_SCRIPT_NAMES = ("brief.py", "features_check.py", "worktree.sh", "hubconfig")
FEATURE_CHECK_COMMAND = "./hub doctor --only features.tracker"
AGENT_FRONTMATTER_KEYS = ["name", "description", "tools", "model"]


def plugin_markdown(config: HubConfig) -> dict[str, str]:
    """The base plugin's rendered agent and skill text, by path."""
    return {
        path: text
        for path, text in rendered_texts(config).items()
        if path.startswith("plugin/hub-workflow/") and path.endswith(".md")
    }


def test_names_no_hub_script_when_plugin_rendered(demo_config: HubConfig) -> None:
    texts = plugin_markdown(demo_config)

    assert {f"plugin/hub-workflow/agents/{name}.md" for name in BASE_AGENTS} <= set(texts)
    assert {f"plugin/hub-workflow/skills/{name}/SKILL.md" for name in BASE_SKILLS} <= set(texts)
    for path, text in texts.items():
        for name in HUB_SCRIPT_NAMES:
            assert name not in text, f"{path} names {name}"


# The planner validates features.json and says what the check rejects; the evaluator runs it.
@pytest.mark.parametrize(("agent", "mentions"), [("planner", 2), ("evaluator", 1)])
def test_names_hub_doctor_when_planner_or_evaluator_rendered(
    agent: str, mentions: int, demo_render: dict[str, RenderedFile]
) -> None:
    text = demo_render[f"plugin/hub-workflow/agents/{agent}.md"].content.decode("utf-8")

    assert text.count(FEATURE_CHECK_COMMAND) == mentions
    assert "features_check" not in text


def test_keeps_frontmatter_when_agents_rendered(demo_render: dict[str, RenderedFile]) -> None:
    for name in BASE_AGENTS:
        text = demo_render[f"plugin/hub-workflow/agents/{name}.md"].content.decode("utf-8")

        lines = frontmatter_lines(text)

        assert [line.split(":", 1)[0] for line in lines] == AGENT_FRONTMATTER_KEYS, name
        fields = dict(line.split(": ", 1) for line in lines)
        assert fields["name"] == name
        assert fields["description"].strip(), name
        # The body follows the frontmatter.
        assert text.split("\n---\n", 1)[1].strip(), name


# AC-4.19 (Q-15, plan design 7): the `hub` command and the make target that runs it through the
# shim, where one exists; the tracker check has no target yet and stays bare.
SKILL_COMMANDS = {
    "kickoff": ("`./hub brief` (`make brain-brief`)",),
    "feature": (
        "`./hub worktree <team>-<n>-<slug> [--only <repo>]` (`make worktree NAME=…`)",
        f"`{FEATURE_CHECK_COMMAND}`",
    ),
}
MAKE_COMMAND = re.compile(r"`make ([a-z][a-z0-9-]*)")


def skill_text(render: dict[str, RenderedFile], name: str) -> str:
    return render[f"plugin/hub-workflow/skills/{name}/SKILL.md"].content.decode("utf-8")


@pytest.mark.parametrize("skill", sorted(SKILL_COMMANDS))
def test_names_hub_commands_when_kickoff_or_feature_rendered(
    skill: str, demo_render: dict[str, RenderedFile]
) -> None:
    text = skill_text(demo_render, skill)
    targets = MAKE_TARGET.findall(demo_render["Makefile"].content.decode("utf-8"))

    for command in SKILL_COMMANDS[skill]:
        assert text.count(command) == 1, command
    # Every make target the skill names is one the rendered Makefile defines.
    named = MAKE_COMMAND.findall(text)
    assert named
    assert set(named) <= set(targets), named


# AGH-16 inventory KO1, KO3: before any commit, kickoff checks the session's git identity against
# hub.json and names the branch to work on; the cloud-setup sentence (KO2) stays a project rule.
def test_checks_git_identity_when_kickoff_skill_rendered(
    demo_config: HubConfig, demo_render: dict[str, RenderedFile]
) -> None:
    text = " ".join(skill_text(demo_render, "kickoff").split())
    prefix = demo_config.project.branch_prefix
    identity = (
        "Check that `git config user.email` in the hub and in each repo equals `hub.json` →"
        " `project.author_email`"
    )
    branch = (
        "If the session was given a `claude/…` branch (cloud sessions), it is not a repo branch:"
        " work on"
        f" `{prefix}<team>-<n>-<desc>`."
    )

    assert text.count(identity) == 1
    assert text.count(branch) == 1
    # The check comes before the next item is proposed, and leaves cloud setup to the project.
    assert (
        text.index(identity) < text.index(branch) < text.index("Propose the next unfinished item")
    )
    assert "cloud-setup" not in text


def test_names_transcript_script_when_recall_rendered(
    demo_render: dict[str, RenderedFile],
) -> None:
    text = skill_text(demo_render, "recall")

    # The script ships with the hub (plan design 6), so the skill keeps naming it.
    assert "`python3 scripts/recall_transcripts.py <term> [<term>…] [--any]`" in text


# The hub's skill frontmatter, key by key; the skills without `disable-model-invocation` stay
# model-invocable.
SKILL_FRONTMATTER_KEYS = {
    "create-plan": ["name", "description", "argument-hint"],
    "feature": ["name", "description", "disable-model-invocation", "argument-hint"],
    "handoff": ["name", "description", "disable-model-invocation", "argument-hint"],
    "kickoff": ["name", "description", "disable-model-invocation"],
    "learn": ["name", "description", "disable-model-invocation", "argument-hint"],
    "recall": ["name", "description", "argument-hint"],
    "research": ["name", "description", "argument-hint"],
}


def test_keeps_frontmatter_when_skills_rendered(demo_render: dict[str, RenderedFile]) -> None:
    assert sorted(SKILL_FRONTMATTER_KEYS) == list(BASE_SKILLS)
    for name, keys in SKILL_FRONTMATTER_KEYS.items():
        text = skill_text(demo_render, name)

        lines = frontmatter_lines(text)

        assert [line.split(":", 1)[0] for line in lines] == keys, name
        fields = dict(line.split(": ", 1) for line in lines)
        assert fields["name"] == name
        assert fields["description"].strip(), name
        assert fields.get("disable-model-invocation", "true") == "true", name
        assert text.split("\n---\n", 1)[1].strip(), name


def test_has_no_author_when_base_manifest_rendered(demo_render: dict[str, RenderedFile]) -> None:
    content = demo_render["plugin/hub-workflow/.claude-plugin/plugin.json"].content

    manifest = json.loads(content)

    # Spec Q-10: the hub's manifest fields minus `author` (hub rule 5).
    assert sorted(manifest) == ["description", "license", "name", "version"]
    assert manifest["name"] == "hub-workflow"
    assert b"author" not in content.lower()


# `hooks.json` runs each hook as `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/<file>"`. A missing file
# makes `python3` exit 2, which blocks on PreToolUse and Stop: a missing `stop_gate.py` would
# block every stop.
HOOK_COMMAND = re.compile(r'python3 "\$\{CLAUDE_PLUGIN_ROOT\}/hooks/([^"/]+)"')


def test_names_rendered_script_when_hooks_json_command_read(
    demo_render: dict[str, RenderedFile],
) -> None:
    hooks = json.loads(demo_render["plugin/hub-workflow/hooks/hooks.json"].content)["hooks"]

    commands = [
        hook["command"] for groups in hooks.values() for group in groups for hook in group["hooks"]
    ]

    assert len(commands) == len(hooks) == 6
    for command in commands:
        match = HOOK_COMMAND.fullmatch(command)
        assert match, command
        assert f"plugin/hub-workflow/hooks/{match[1]}" in demo_render, command


# The upstream license texts the NOTICE's attributions point to, by SHA-256 of the official
# files: the Apache License 2.0 (apache.org) and the MIT license of the adapted plugin.
LICENSE_DIGESTS = {
    "LICENSES/Apache-2.0.txt": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    "LICENSES/MIT-compound-engineering-plugin.txt": (
        "61d89de7646effdaba2d0a4ab7bd0eba60b4094b83efe5bc73c7940e43e93fc6"
    ),
}


def test_copies_upstream_license_bytes_when_licenses_rendered(
    demo_render: dict[str, RenderedFile],
) -> None:
    rendered = {
        path.removeprefix("plugin/hub-workflow/"): file
        for path, file in demo_render.items()
        if path.startswith("plugin/hub-workflow/LICENSES/")
    }

    assert sorted(rendered) == sorted(LICENSE_DIGESTS)
    for name, digest in LICENSE_DIGESTS.items():
        assert hashlib.sha256(rendered[name].content).hexdigest() == digest, name


def test_points_to_each_license_when_notice_rendered(
    demo_render: dict[str, RenderedFile],
) -> None:
    notice = demo_render["plugin/hub-workflow/NOTICE"].content.decode("utf-8")

    for name in LICENSE_DIGESTS:
        assert notice.count(name) == 1, name
    assert "Copyright (c) 2024, humanlayer Authors" in notice
    assert "Copyright (c) 2025 Every" in notice
    # A generated hub never had the hub's removed skill.
    assert "validate-plan" not in notice


def test_keeps_author_name_out_when_makefile_rendered(
    demo_config: HubConfig, variant_config: HubConfig
) -> None:
    assert "Jane Doe" not in text_of(demo_config, "Makefile")
    assert "Sentinel Author Q7" not in text_of(variant_config, "Makefile")


def test_lists_help_when_make_dry_run(
    variant_config: HubConfig,
    rendered_tree: Callable[[RenderedHub], Path],
    fake_uv_bin: Path,
) -> None:
    root = a_hub_tree(variant_config, rendered_tree)

    completed = run_make(root, fake_uv_bin, "-n", "help")

    assert completed.returncode == 0, completed.stderr


def test_lists_each_base_target_once_when_help_run(
    variant_config: HubConfig,
    rendered_tree: Callable[[RenderedHub], Path],
    fake_uv_bin: Path,
) -> None:
    root = a_hub_tree(variant_config, rendered_tree)

    completed = run_make(root, fake_uv_bin, "help")

    assert completed.returncode == 0, completed.stderr
    names = [line.split()[0] for line in completed.stdout.splitlines() if line.strip()]
    for target in BASE_TARGETS:
        assert names.count(target) == 1, f"{target} in {names}"
    assert logged_calls(fake_uv_bin) == []


# AGH-17 D5 (AC-17.7): each module's make targets, in its `mk/<id>.mk`.
MODULE_TARGETS = {
    "mk/bench.mk": ("bench", "bench-validate"),
    "mk/cloud.mk": ("cloud-setup",),
    "mk/contract-sync.mk": ("contract-sync",),
    "mk/marketplace.mk": ("marketplace-validate",),
}
PHONY_LINE = re.compile(r"^\.PHONY:(.*)$", re.MULTILINE)


def help_names(stdout: str) -> list[str]:
    return [line.split()[0] for line in stdout.splitlines() if line.strip()]


def test_lists_module_targets_when_help_run_with_all_modules(
    all_modules_config: HubConfig,
    rendered_tree: Callable[[RenderedHub], Path],
    fake_uv_bin: Path,
) -> None:
    root = a_hub_tree(all_modules_config, rendered_tree)

    completed = run_make(root, fake_uv_bin, "help")

    assert completed.returncode == 0, completed.stderr
    module_targets = [name for names in MODULE_TARGETS.values() for name in names]
    assert sorted(help_names(completed.stdout)) == sorted([*BASE_TARGETS, *module_targets])
    # One column: every description starts at the same offset, past the longest name.
    rows = [line for line in completed.stdout.splitlines() if line.strip()]
    offsets = {len(row) - len(row.split(maxsplit=1)[1]) for row in rows}
    assert len(offsets) == 1, rows
    assert offsets.pop() > 2 + max(len(name) for name in help_names(completed.stdout))
    assert logged_calls(fake_uv_bin) == []


def test_lists_only_base_targets_when_no_module_selected(
    variant_config: HubConfig,
    rendered_tree: Callable[[RenderedHub], Path],
    fake_uv_bin: Path,
) -> None:
    root = a_hub_tree(variant_config, rendered_tree)

    completed = run_make(root, fake_uv_bin, "help")

    assert completed.returncode == 0, completed.stderr
    assert sorted(help_names(completed.stdout)) == sorted(BASE_TARGETS)
    assert not (root / "mk").exists()


def test_declares_phony_when_module_makefile_rendered(all_modules_config: HubConfig) -> None:
    rendered = {file.path: file for file in render_hub(all_modules_config).files}
    makefiles = {path: file for path, file in rendered.items() if path.startswith("mk/")}

    assert sorted(makefiles) == sorted(MODULE_TARGETS)
    for path, targets in MODULE_TARGETS.items():
        text = makefiles[path].content.decode("utf-8")
        assert MAKE_TARGET.findall(text) == list(targets), path
        phony = PHONY_LINE.findall(text)
        assert len(phony) == 1, path
        assert phony[0].split() == list(targets), path
        for target in targets:
            # Each target has a help text, so `make help` lists it.
            assert re.search(rf"^{re.escape(target)}:.*## \S", text, re.MULTILINE), target


def test_passes_check_when_hub_has_no_tests(
    variant_config: HubConfig,
    rendered_tree: Callable[[RenderedHub], Path],
    fake_uv_bin: Path,
) -> None:
    root = a_hub_tree(variant_config, rendered_tree)

    completed = run_make(root, fake_uv_bin, "check")

    assert completed.returncode == 0, completed.stderr
    assert logged_calls(fake_uv_bin)[-1].endswith(" hub doctor")


def test_fails_check_when_hub_test_fails(
    variant_config: HubConfig,
    rendered_tree: Callable[[RenderedHub], Path],
    fake_uv_bin: Path,
) -> None:
    root = a_hub_tree(variant_config, rendered_tree)
    (root / "tests").mkdir()
    (root / "tests" / "test_gate.py").write_text(
        "import unittest\n\n\nclass GateTest(unittest.TestCase):\n"
        "    def test_gate(self):\n        self.fail('the hub gate fails')\n",
        encoding="utf-8",
    )

    completed = run_make(root, fake_uv_bin, "check")

    assert completed.returncode != 0
    assert "the hub gate fails" in completed.stderr


def test_runs_shim_when_hub_folder_name_needs_quoting(
    variant_config: HubConfig,
    *,
    rendered_tree: Callable[..., Path],
    fake_uv_bin: Path,
    tmp_path: Path,
) -> None:
    # A folder name with a double quote, a dollar sign, an apostrophe and a space: the shim's
    # path must reach the shell as one word, unexpanded.
    root = rendered_tree(render_hub(variant_config), root=tmp_path / "d$HOME\"q it's")
    document = a_hub_document()
    document["platform"]["version"] = RUN_VERSION
    (root / "hub.json").write_text(json.dumps(document), encoding="utf-8")

    completed = run_make(root, fake_uv_bin, "brain-brief")

    assert completed.returncode == 0, completed.stderr
    source = pinned_source(RUN_VERSION)
    assert logged_calls(fake_uv_bin) == [
        f"uvx --from {source} hub --version",
        f"uvx --from {source} hub brief",
    ]


@pytest.mark.parametrize(
    ("arguments", "hub_call"),
    [
        (("brain-brief",), "hub brief"),
        (("next",), "hub next"),
        (("worktree", "NAME=dem-1-demo"), "hub worktree dem-1-demo"),
        (
            ("worktree", "NAME=dem-1_v1.2", "ONLY=demo-web"),
            "hub worktree dem-1_v1.2 --only demo-web",
        ),
        (("worktree-remove", "NAME=dem-1-demo"), "hub worktree --remove dem-1-demo"),
        (("run-issue", "ISSUE=DEM-1", "REPO=demo-api"), "hub run DEM-1 --repo demo-api"),
        (
            ("run-issue", "ISSUE=DEM-1", "REPO=demo-api", "LIVE=1"),
            "hub run DEM-1 --repo demo-api --live",
        ),
        (
            ("run-issue", "ISSUE=DEM-1", "REPO=demo-api", "LIVE=1", "BUDGET=2.5", "FROM=verify"),
            "hub run DEM-1 --repo demo-api --live --budget 2.5 --from verify",
        ),
        (("check",), "hub doctor"),
    ],
)
def test_runs_pinned_release_when_target_run(
    arguments: tuple[str, ...],
    hub_call: str,
    *,
    variant_config: HubConfig,
    rendered_tree: Callable[[RenderedHub], Path],
    fake_uv_bin: Path,
) -> None:
    root = a_hub_tree(variant_config, rendered_tree)

    completed = run_make(root, fake_uv_bin, *arguments)

    assert completed.returncode == 0, completed.stderr
    # The version is the one hub.json pins when the recipe runs (R7), not a rendered value.
    source = pinned_source(RUN_VERSION)
    assert logged_calls(fake_uv_bin) == [
        f"uvx --from {source} hub --version",
        f"uvx --from {source} {hub_call}",
    ]


def test_imports_both_rule_files_when_claude_rendered(demo_config: HubConfig) -> None:
    lines = text_of(demo_config, "CLAUDE.md").splitlines()

    assert lines[:2] == ["@AGENTS.md", "@AGENTS.project.md"]
    assert sum("`./agent` (`make agent`)" in line for line in lines) == 1


# AC-3.19 (Q7, O4): the hygiene hooks of the pinned pre-commit-hooks release.
HYGIENE_HOOKS = ("trailing-whitespace", "end-of-file-fixer", "check-json", "check-yaml")
PLACEHOLDER = re.compile(r"@@(?:\{[A-Za-z_][A-Za-z0-9_]*\}|[A-Za-z_][A-Za-z0-9_]*)")
# AGH-16 Q-11: an action is pinned by its 40-hex commit SHA, the release named in a comment.
ACTION_PIN = r"@[0-9a-f]{40}  # v\d+\.\d+\.\d+"
PINNED_SETUP_UV = re.compile(
    rf'- uses: astral-sh/setup-uv{ACTION_PIN}\n\s+with:\n\s+version: "\d+\.\d+\.\d+"\n'
)
PINNED_USES = re.compile(rf"^\s+-?\s*uses: [\w.-]+(?:/[\w.-]+)+{ACTION_PIN}$")


# The hub-doctor hook's entry: the shim, run from the hub root (pre-commit's cwd).
HUB_DOCTOR_ENTRY = "./hub doctor"


def pre_commit_entry(text: str) -> str:
    """The value of the one ``entry:`` key, as written."""
    entries = [line.strip() for line in text.splitlines() if line.strip().startswith("entry:")]
    assert len(entries) == 1, entries
    return entries[0].removeprefix("entry:").strip()


def run_pre_commit_entry(
    config: HubConfig, root: Path, env: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run the hub-doctor entry as pre-commit runs a ``language: system`` hook: split, no shell."""
    command = shlex.split(pre_commit_entry(text_of(config, ".pre-commit-config.yaml")))
    assert command == ["./hub", "doctor"]
    return subprocess.run(  # noqa: S603 - the rendered shim by absolute path, no shell
        [str(root / "hub"), *command[1:]],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        cwd=root,
        env=dict(env),
    )


# AGH-16 D3/D4: the workflow's steps, in order; a step is the list item at the job's step indent.
CI_STEP_START = "      - "
CREDENTIAL_STEP = "Platform read credential"
GOLDEN_STEP = "Golden (hub sync --check)"
MAKE_CHECK_STEP = "make check"
READ_REFERENCE = "secrets.AGENT_HUB_READ_TOKEN"


def ci_steps(ci: str) -> list[str]:
    """Each step of the one job as written, from its ``- `` line to the next step's."""
    body = ci[ci.index("\n    steps:\n") + len("\n    steps:\n") :]
    steps: list[str] = []
    for line in body.splitlines(keepends=True):
        if line.startswith(CI_STEP_START):
            steps.append("")
        if steps and line.startswith((CI_STEP_START, "        ")):
            steps[-1] += line
    return steps


def ci_step(ci: str, name: str) -> str:
    """The one step whose ``- name:`` is ``name``."""
    found = [step for step in ci_steps(ci) if step.startswith(f"{CI_STEP_START}name: {name}\n")]
    assert len(found) == 1, ci
    return found[0]


def run_block(step: str) -> str:
    """The lines of the step's ``run: |`` block, as written."""
    head = "        run: |\n"
    assert head in step, step
    return step[step.index(head) + len(head) :]


class TestCiWorkflow:
    @pytest.mark.parametrize(("config_name", "branch"), [("demo", "main"), ("variant", "trunk")])
    def test_limits_workflow_when_ci_rendered(
        self, config_name: str, branch: str, request: pytest.FixtureRequest
    ) -> None:
        config = request.getfixturevalue(f"{config_name}_config")

        ci = text_of(config, ".github/workflows/ci.yml")

        assert "\npermissions:\n  contents: read\n" in ci
        triggers = ci[ci.index("\non:\n") : ci.index("\npermissions:")]
        assert f'  pull_request:\n    branches: ["{branch}"]\n' in triggers
        assert f'  push:\n    branches: ["{branch}"]\n' in triggers
        steps = re.findall(r"^\s+- (?:uses|name|run): .*$", ci, re.MULTILINE)
        assert [step.strip() for step in steps] == [
            "- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1",
            "- uses: astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78  # v7.6.0",
            f"- name: {CREDENTIAL_STEP}",
            f"- name: {GOLDEN_STEP}",
            f"- name: {MAKE_CHECK_STEP}",
        ]
        assert PINNED_SETUP_UV.search(ci)
        assert "run: make check" in ci
        assert not re.search(r"(?:version: \"?|@)latest", ci)
        assert "@main" not in ci
        assert re.findall(r"secrets\.\w*", ci) == [READ_REFERENCE]
        jobs = ci[ci.index("\njobs:\n") :]
        assert re.findall(r"^  ([a-z][a-z0-9-]*):$", jobs, re.MULTILINE) == ["check"]

    @pytest.mark.parametrize("config_name", ["demo", "variant"])
    def test_runs_golden_before_make_check_when_ci_rendered(
        self, config_name: str, request: pytest.FixtureRequest
    ) -> None:
        ci = text_of(request.getfixturevalue(f"{config_name}_config"), ".github/workflows/ci.yml")

        steps = ci_steps(ci)
        golden = ci_step(ci, GOLDEN_STEP)
        make_check = ci_step(ci, MAKE_CHECK_STEP)

        assert golden == f"{CI_STEP_START}name: {GOLDEN_STEP}\n        run: ./hub sync --check\n"
        assert make_check == f"{CI_STEP_START}name: {MAKE_CHECK_STEP}\n        run: make check\n"
        # Q-10: the same job, the golden step right before make check, after the credential.
        assert steps[-2:] == [golden, make_check]
        assert steps.index(ci_step(ci, CREDENTIAL_STEP)) < steps.index(golden)

    @pytest.mark.parametrize("config_name", ["demo", "variant"])
    def test_names_secret_only_by_expression_when_ci_rendered(
        self, config_name: str, request: pytest.FixtureRequest
    ) -> None:
        ci = text_of(request.getfixturevalue(f"{config_name}_config"), ".github/workflows/ci.yml")

        credential = ci_step(ci, CREDENTIAL_STEP)
        block = run_block(credential)

        assert ci.count("secrets.") == 1
        assert f"        env:\n          TOKEN: ${{{{ {READ_REFERENCE} }}}}\n" in credential
        # The token reaches git only through the job's environment, set by the run block.
        assert "x-access-token" in block
        assert "x-access-token" not in ci.replace(block, "")
        assert '>> "$GITHUB_ENV"' in block
        assert "--dangerously-skip-permissions" not in ci

    @pytest.mark.parametrize("config_name", ["demo", "variant"])
    def test_pins_actions_by_sha_when_ci_rendered(
        self, config_name: str, request: pytest.FixtureRequest
    ) -> None:
        ci = text_of(request.getfixturevalue(f"{config_name}_config"), ".github/workflows/ci.yml")

        uses = [line for line in ci.splitlines() if re.match(r"^\s+-?\s*uses:", line)]

        assert uses
        assert [line for line in uses if not PINNED_USES.match(line)] == []


# AGH-46 D-agents: the two branch mentions of AGENTS.md, as rendered before the repo key existed.
WORKTREE_MENTION = "   fetched {base}.\n"
PUSH_RULE = (
    "2. No push to {branches}, no force-push, no production deploys. Everything lands through a PR"
    " the\n"
)


def ci_trigger_branches(ci: str) -> list[str]:
    """The ``branches:`` values of the workflow's triggers, in file order."""
    return re.findall(r'^    branches: \["([^"]+)"\]$', ci, re.MULTILINE)


def test_renders_agents_and_ci_as_before_when_no_repo_sets_branch(
    variant_config: HubConfig,
) -> None:
    agents = text_of(variant_config, "AGENTS.md")
    ci = text_of(variant_config, ".github/workflows/ci.yml")

    assert WORKTREE_MENTION.format(base="`origin/trunk`") in agents
    assert PUSH_RULE.format(branches="`trunk`") in agents
    assert "<the repo's default branch>" not in agents
    assert ci_trigger_branches(ci) == ["trunk", "trunk"]


def test_names_repo_branches_in_agents_when_repo_sets_one(variant_config: HubConfig) -> None:
    document = variant_config.model_dump(mode="json", by_alias=True, exclude_none=True)
    document["repos"][0]["default_branch"] = "master"
    config = HubConfig.model_validate(document)

    agents = text_of(config, "AGENTS.md")
    ci = text_of(config, ".github/workflows/ci.yml")

    base = "`origin/<the repo's default branch>` (demo-api: `master`, demo-web: `trunk`)"
    assert WORKTREE_MENTION.format(base=base) in agents
    assert PUSH_RULE.format(branches="`main`, `master` or `trunk`") in agents
    assert "`origin/trunk`" not in agents
    # The hub's own CI keeps the project branch.
    assert ci_trigger_branches(ci) == ["trunk", "trunk"]


# AGH-65 AC-65.7: sha256 of the files as rendered on main (4346e52) before the identity keys became
# optional; a hub that sets them in hub.json keeps these bytes.
# AGH-59: re-pinned when rule 4 named the script variables.
DEMO_AGENTS_SHA256 = "fd0949e3a6f09c58089cbb5f4fcfcb86d9859128b6c5ea4c9827cec65f9ce655"
ALL_MODULES_SHA256 = {
    "AGENTS.md": "e641cdafe7fe9fc7f098c119eea03b34d48a2fd2fdc65239ed92fa25df5fd8ea",
    ".claude-plugin/marketplace.json": (
        "f7324911e70a0f3255274721636821a9b65a5716f04c5f6e3e470e74dc7b8ac7"
    ),
}
USER_RULE = (
    "1. Commits and PRs are authored by the user (`hub.json` → `project.author_name`,"
    " `project.author_email`). No AI\n"
)
# AGH-65 AC-65.8 (plan E14): rule 1 of a team hub's AGENTS.md, from its first line to rule 2.
TEAM_RULE = (
    "1. Commits and PRs are authored by the developer running the session (`hub.local.json` →"
    " `project.author_name`,\n"
    "   `project.author_email`, else their `git config user.name`, `user.email`). No AI\n"
    '   co-author trailer, no "Generated with" line, no emoji or other sign that an agent did the'
    " work, and no branch named\n"
    "   after an agent (e.g. `claude/…`). Branch: `<prefix><team>-<n>-<desc>`, where `<team>` is"
    " the\n"
    "   tracker team DEM in lowercase.\n"
    "   `<prefix>` is `hub.local.json` → `project.branch_prefix`, else the local part of your"
    " author email plus `/`.\n"
    "2. No push"
)


def a_team_config() -> HubConfig:
    """The demo with every module and no identity key: each developer brings their own."""
    document = a_hub_document()
    document["modules"] = {**document["modules"], "marketplace": {}}
    for key in ("branch_prefix", "author_name", "author_email"):
        del document["project"][key]
    return HubConfig.model_validate(document)


# AGH-65 with AGH-16 KO1: on a team hub kickoff checks the session's git email against the
# developer's own address, never a hub.json key the hub does not hold.
def test_checks_developer_email_when_team_kickoff_rendered() -> None:
    render = {file.path: file for file in render_hub(a_team_config()).files}
    raw = skill_text(render, "kickoff")
    text = " ".join(raw.split())

    check = (
        "Check that `git config user.email` in the hub and in each repo equals your author"
        " email (`hub.local.json` → `project.author_email`, else your own address, not an"
        " agent's or the container's); if it differs, say so before any commit."
    )
    assert text.count(check) == 1
    assert "`hub.json` → `project.author_email`" not in text
    assert "work on `<prefix><team>-<n>-<desc>`." in text
    step = raw.split("\n4. ", 1)[1].split("\n5. ", 1)[0]
    assert all(len(line) <= 120 for line in f"4. {step}".splitlines())


def test_renders_team_rules_when_identity_absent(demo_config: HubConfig) -> None:
    config = a_team_config()

    rendered = render_hub(config)
    agents = text_of(config, "AGENTS.md")

    assert agents[agents.index("1. Commits") : agents.index("2. No push") + len("2. No push")] == (
        TEAM_RULE
    )
    assert all(len(line) <= 120 for line in agents.splitlines())
    # No placeholder left, and no absent value spelled out: a file holds `None` or `null` only
    # where the identity-setting demo's does (Python code, JSON).
    demo = {file.path: file.content for file in render_hub(demo_config).files}
    for file in rendered.files:
        content = file.content or b""
        assert b"@@" not in content, file.path
        for word in (b"None", b"null"):
            assert content.count(word) == (demo.get(file.path) or b"").count(word), file.path
    assert render_hub(config) == rendered


def test_keeps_lines_within_width_when_team_key_long() -> None:
    config = a_team_config()
    config = config.model_copy(
        update={"tracker": config.tracker.model_copy(update={"team": "LONGTEAMKEY1"})}
    )

    agents = text_of(config, "AGENTS.md")

    assert "tracker team LONGTEAMKEY1 in lowercase." in agents
    assert [line for line in agents.splitlines() if len(line) > 120] == []


# AGH-56 (plan § Design 7): the plugin files that name the tracker team, and the hub with two.
TEAM_KEY_PLUGIN_FILES = (
    "plugin/hub-workflow/skills/feature/SKILL.md",
    "plugin/hub-workflow/agents/planner.md",
    "plugin/hub-workflow/agents/requirements-analyst.md",
)


def a_config_with_teams(keys: list[str]) -> HubConfig:
    document = a_hub_document()
    document["tracker"] = {"kind": "linear", "teams": keys}
    return HubConfig.model_validate(document)


def test_names_every_team_in_agents_when_tracker_lists_teams() -> None:
    config = a_config_with_teams(["APP", "OPS"])

    rendered = render_hub(config)
    texts = rendered_texts(config)
    agents = texts["AGENTS.md"]

    assert "team APP, OPS (default APP)" in agents
    assert "where `<team>` is one of the tracker teams APP, OPS in lowercase" in " ".join(
        agents.split()
    )
    assert [line for line in agents.splitlines() if len(line) > 120] == []
    for file in rendered.files:
        assert b"@@" not in (file.content or b""), file.path
    assert render_hub(config) == rendered
    for path in TEAM_KEY_PLUGIN_FILES:
        assert "`tracker.teams`" in texts[path], path
        assert "`tracker.team`" not in texts[path], path


def test_keeps_lines_within_width_when_many_teams_listed() -> None:
    # 8 keys: with the suffix ignored, the last line of both team values would pass 120 characters.
    keys = [f"TEAMKEY{chr(65 + n // 26)}{chr(65 + n % 26)}" for n in range(8)]

    agents = text_of(a_config_with_teams(keys), "AGENTS.md")

    assert ", ".join(keys) in " ".join(agents.split())
    assert [line for line in agents.splitlines() if len(line) > 120] == []


def test_names_tracker_team_key_when_one_team_rendered(demo_config: HubConfig) -> None:
    texts = rendered_texts(demo_config)

    for path in TEAM_KEY_PLUGIN_FILES:
        assert "`tracker.team`" in texts[path], path
        assert "teams" not in texts[path], path


def test_keeps_agents_bytes_when_identity_in_hub_json(
    demo_config: HubConfig, variant_config: HubConfig, all_modules_config: HubConfig
) -> None:
    def digest(config: HubConfig, path: str) -> str:
        return hashlib.sha256(text_of(config, path).encode("utf-8")).hexdigest()

    assert digest(demo_config, "AGENTS.md") == DEMO_AGENTS_SHA256
    assert {path: digest(all_modules_config, path) for path in ALL_MODULES_SHA256} == (
        ALL_MODULES_SHA256
    )
    # Another author in hub.json renders the same user wording, never the author's name.
    variant = text_of(variant_config, "AGENTS.md")
    assert USER_RULE in variant
    assert "hub.local.json" not in variant


# AGH-57 (plan § Design 7, E11): the mixed hub's AGENTS.md and kickoff show its conventions.
KICKOFF_PATH = "plugin/hub-workflow/skills/kickoff/SKILL.md"
FEATURE_PATH = "plugin/hub-workflow/skills/feature/SKILL.md"


def without_conventions(document: dict[str, Any]) -> dict[str, Any]:
    """``document`` with neither ``project.conventions`` nor any ``repos[].conventions``."""
    document["project"].pop("conventions", None)
    for repo in document["repos"]:
        repo.pop("conventions", None)
    return document


def rule_one(agents: str) -> str:
    return agents[agents.index("1. Commits") : agents.index("2. No push")]


def test_shows_conventions_in_agents_when_hub_sets_them() -> None:
    config = HubConfig.model_validate(a_conventions_document())
    plain = rendered_texts(HubConfig.model_validate(without_conventions(a_conventions_document())))

    rendered = render_hub(config)
    texts = rendered_texts(config)
    agents = texts["AGENTS.md"]

    assert agents.count("## Conventions") == 1
    block = agents.split("## Conventions\n", 1)[1].split("\n## ", 1)[0]
    for label in ("- Branch: ", "- Commit title: ", "- PR title: "):
        (line,) = [line for line in block.splitlines() if line.startswith(label)]
        assert line.count("e.g.") == 1, label
    assert [line for line in block.splitlines() if "`demo-api`" in line] == [
        "- `demo-api` overrides branch `feature/{issue_lower}/{slug}`."
    ]
    assert "`jdoe/{ISSUE}-{slug}`" in rule_one(agents)
    assert "<team>-<n>-<desc>" not in rule_one(agents)
    assert "work on `jdoe/{ISSUE}-{slug}`" in texts[KICKOFF_PATH]
    assert "<team>-<n>-<desc>" not in texts[KICKOFF_PATH]
    assert "`make worktree NAME=<team>-<n>-<desc>`" in agents
    assert texts[FEATURE_PATH] == plain[FEATURE_PATH]
    assert [line for line in agents.splitlines() if len(line) > 120] == []
    for file in rendered.files:
        assert b"@@" not in (file.content or b""), file.path
    assert render_hub(config) == rendered


def an_80_character_pattern(head: str, tail: str) -> str:
    pattern = head + "x" * (80 - len(head) - len(tail)) + tail
    assert len(pattern) == 80
    return pattern


def test_keeps_lines_within_width_when_conventions_long() -> None:
    branch = an_80_character_pattern("{prefix}", "/{ISSUE}-{slug}")
    title = an_80_character_pattern("{ISSUE}: {type}({scope}): {summary} -- ", "")
    long_conventions = {"branch": branch, "commit_title": title, "pr_title": title}
    document = a_conventions_document()
    document["project"]["conventions"] = long_conventions
    document["repos"][0]["conventions"] = long_conventions
    for no_prefix in (False, True):
        if no_prefix:
            del document["project"]["branch_prefix"]

        agents = text_of(HubConfig.model_validate(document), "AGENTS.md")

        # The rule, the three shapes and their examples, and the three repo overrides.
        assert agents.count("x" * 40) == 10, no_prefix
        assert [line for line in agents.splitlines() if len(line) > 120] == [], no_prefix


def test_shows_prefix_placeholder_when_hub_leaves_prefix_to_developers() -> None:
    document = a_conventions_document()
    del document["project"]["branch_prefix"]
    config = HubConfig.model_validate(document)

    texts = rendered_texts(config)

    assert "Branch: `<prefix>{ISSUE}-{slug}`, or the repo's own" in rule_one(texts["AGENTS.md"])
    assert (
        "- Branch: `<prefix>{ISSUE}-{slug}`, e.g. `<prefix>DEM-7-collector`." in texts["AGENTS.md"]
    )
    assert "work on `<prefix>{ISSUE}-{slug}`" in texts[KICKOFF_PATH]


# AGH-16 inventory A6b: the per-repo setup scripts `hub worktree` runs, named in the workflow step
# that creates the worktree.
def test_names_worktree_setup_scripts_when_agents_rendered(demo_config: HubConfig) -> None:
    agents = text_of(demo_config, "AGENTS.md")
    workflow = agents.split("## Workflow", 1)[1].split("\n## ", 1)[0]
    step = " ".join(workflow.split("\n4. ", 1)[1].split("\n5. ", 1)[0].split())

    assert step.count("`<repo>/scripts/worktree-setup.sh`") == 1
    assert step.count("`<repo>/scripts/worktree-teardown.sh`") == 1
    assert "`make worktree NAME=<team>-<n>-<desc>`" in step
    assert "(env files, databases, ports)" in step
    for name in WORKTREE_VARIABLES:
        assert step.count(f"`{name}`") == 1, name
    # AGH-59: the dirs are the main checkouts, not the worktree; the offset is not unique per task.
    assert "(the repo's and the hub's main checkouts)" in step
    assert "two tasks can share a slot" in step


# AGH-59: the variables the repo's worktree scripts get, as literals (the generator may not
# import cli).
WORKTREE_VARIABLES = (
    "HUB_WORKTREE_NAME",
    "HUB_WORKTREE_BRANCH",
    "HUB_REPO_DIR",
    "HUB_HUB_DIR",
    "HUB_WORKTREE_SLOT",
    "HUB_PORT_OFFSET",
)


@pytest.mark.parametrize(
    "document",
    [builders.a_hub_document, builders.a_two_team_document, builders.a_conventions_document],
    ids=["demo", "two_teams", "conventions"],
)
def test_keeps_worktree_step_within_width_when_hubs_rendered(
    document: Callable[[], dict[str, Any]],
) -> None:
    config = HubConfig.model_validate(document())
    first = {file.path: file.content for file in render_hub(config).files}["AGENTS.md"]
    second = {file.path: file.content for file in render_hub(config).files}["AGENTS.md"]
    agents = first.decode("utf-8")
    workflow = agents.split("## Workflow", 1)[1].split("\n## ", 1)[0]
    step = " ".join(workflow.split("\n4. ", 1)[1].split("\n5. ", 1)[0].split())

    assert [line for line in agents.splitlines() if len(line) > 120] == []
    assert first == second
    for name in WORKTREE_VARIABLES:
        assert step.count(f"`{name}`") == 1, name


def test_pins_hygiene_hooks_when_pre_commit_rendered(demo_config: HubConfig) -> None:
    pre_commit = text_of(demo_config, ".pre-commit-config.yaml")

    assert "  - repo: https://github.com/pre-commit/pre-commit-hooks\n    rev: v6.0.0\n" in (
        pre_commit
    )
    assert re.findall(r"^\s+rev: (.*)$", pre_commit, re.MULTILINE) == ["v6.0.0"]
    hook_ids = re.findall(r"^\s+- id: (.*)$", pre_commit, re.MULTILINE)
    assert hook_ids == [*HYGIENE_HOOKS, "hub-doctor"]
    assert pre_commit.count("- repo: local\n") == 1


def test_runs_hub_doctor_through_shim_when_pre_commit_entry_run(
    variant_config: HubConfig,
    rendered_tree: Callable[[RenderedHub], Path],
    fake_uv_bin: Path,
) -> None:
    root = a_hub_tree(variant_config, rendered_tree)
    assert pre_commit_entry(text_of(variant_config, ".pre-commit-config.yaml")) == HUB_DOCTOR_ENTRY

    completed = run_pre_commit_entry(variant_config, root, run_env(fake_uv_bin))

    assert completed.returncode == 0, completed.stderr
    source = pinned_source(RUN_VERSION)
    assert logged_calls(fake_uv_bin) == [
        f"uvx --from {source} hub --version",
        f"uvx --from {source} hub doctor",
    ]


def test_names_no_config_lint_when_ci_files_rendered(
    demo_config: HubConfig, variant_config: HubConfig
) -> None:
    for config in (demo_config, variant_config):
        for path in (".github/workflows/ci.yml", ".pre-commit-config.yaml"):
            assert "agent_config_lint" not in text_of(config, path)


def test_quotes_placeholders_when_yaml_template_read() -> None:
    # R-5a: a valid value such as `on`, `NO` or `1.0` parses as another type when unquoted.
    yaml_texts = {
        name: text for name, text in template_texts() if name.endswith((".yml.tmpl", ".yaml.tmpl"))
    }

    assert set(yaml_texts) == {"github/workflows/ci.yml.tmpl", "pre-commit-config.yaml.tmpl"}
    found = dict.fromkeys(yaml_texts, 0)
    for name, text in yaml_texts.items():
        for line in text.splitlines():
            for match in PLACEHOLDER.finditer(line):
                found[name] += 1
                before, after = line[: match.start()], line[match.end() :]
                assert before.count('"') % 2 == 1, f"{name}: {line!r}"
                assert '"' in after, f"{name}: {line!r}"
    # The pre-commit entry is ./hub doctor: the pinned source lives in the shim (AGH-15).
    assert found["github/workflows/ci.yml.tmpl"] > 0
    assert found["pre-commit-config.yaml.tmpl"] == 0


def test_quotes_values_when_variant_yaml_rendered() -> None:
    document = a_hub_document()
    document["tracker"]["team"] = "NO"
    document["project"]["default_branch"] = "1.0"

    ci = text_of(HubConfig.model_validate(document), ".github/workflows/ci.yml")

    assert ci.count('branches: ["1.0"]') == 2
    assert "branches: [1.0]" not in ci


# A name that would run `echo INJ` if a recipe passed it to the shell unquoted or unchecked.
@pytest.mark.parametrize(
    "arguments",
    [
        ("worktree", "NAME=x;echo INJ"),
        ("worktree", "NAME=x;echo${IFS}INJ"),
        ("worktree", "NAME=dem-1;INJ"),
        ("worktree", "NAME=x';echo INJ;'"),
        ("worktree", 'NAME=x";echo INJ;"'),
        ("worktree", "NAME=dem-1", "ONLY=demo-web;echo INJ"),
        ("worktree-remove", "NAME=x;echo INJ"),
        ("run-issue", "ISSUE=DEM-1;echo INJ", "REPO=demo-api"),
        ("run-issue", "ISSUE=DEM-1", "REPO=`echo INJ`"),
        ("run-issue", "ISSUE=DEM-1", "REPO=demo-api", "BUDGET=1;echo INJ"),
        ("run-issue", "ISSUE=DEM-1", "REPO=demo-api", "FROM=x y;echo INJ"),
    ],
)
def test_rejects_name_when_target_given_shell_syntax(
    arguments: tuple[str, ...],
    *,
    variant_config: HubConfig,
    rendered_tree: Callable[[RenderedHub], Path],
    fake_uv_bin: Path,
) -> None:
    root = a_hub_tree(variant_config, rendered_tree)

    completed = run_make(root, fake_uv_bin, *arguments)

    assert completed.returncode != 0
    assert "Error 1" in completed.stderr
    assert f"ERROR {arguments[0]}: " in completed.stderr
    assert "Fix: " in completed.stderr
    assert "INJ" not in completed.stdout
    assert logged_calls(fake_uv_bin) == []


# Shim failures (docs/design/hub-generator.md § Commands), for the Makefile shim (run through the
# brain-brief target) and the pre-commit hub-doctor entry.
SHIM_RUNNERS = ("make", "pre-commit")
SHIM_CALL = {"make": "hub brief", "pre-commit": "hub doctor"}
# The fake uv tools' exit codes (conftest.fake_uv_bin): the resolve call, then any other call.
FAKE_UVX_RESOLVE_RC = "FAKE_UVX_RESOLVE_RC"
FAKE_UVX_RC = "FAKE_UVX_RC"


@pytest.fixture
def no_uv_path(tmp_path: Path) -> str:
    """A PATH folder holding only what the shims need besides uv: python3 and sh."""
    folder = tmp_path / "no-uv-bin"
    folder.mkdir()
    for tool in ("python3", "sh"):
        found = shutil.which(tool)
        assert found is not None, f"the shim tests need {tool} on PATH"
        (folder / tool).symlink_to(found)
    return str(folder)


def run_shim(
    runner: str,
    config: HubConfig,
    root: Path,
    *,
    fake_uv_bin: Path,
    env_overrides: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the Makefile shim (``make brain-brief``) or the pre-commit hub-doctor entry."""
    if runner == "make":
        return run_make(root, fake_uv_bin, "brain-brief", env_overrides=env_overrides)
    return run_pre_commit_entry(config, root, run_env(fake_uv_bin, env_overrides))


def assert_shim_exit(runner: str, completed: subprocess.CompletedProcess[str], code: int) -> None:
    """The entry exits ``code``; make itself exits 2 and names the recipe's code on stderr."""
    if runner == "make":
        assert completed.returncode == 2, completed.stderr
        assert f"Error {code}" in completed.stderr
    else:
        assert completed.returncode == code, completed.stderr


@pytest.mark.parametrize("runner", SHIM_RUNNERS)
def test_names_missing_access_when_release_unresolved(
    runner: str,
    *,
    variant_config: HubConfig,
    rendered_tree: Callable[[RenderedHub], Path],
    fake_uv_bin: Path,
) -> None:
    root = a_hub_tree(variant_config, rendered_tree)

    completed = run_shim(
        runner,
        variant_config,
        root,
        fake_uv_bin=fake_uv_bin,
        env_overrides={FAKE_UVX_RESOLVE_RC: "1", FAKE_UVX_RC: "0"},
    )

    assert_shim_exit(runner, completed, 1)
    source = pinned_source(RUN_VERSION)
    assert f"hub: cannot run agent-hub {RUN_VERSION} from {source}" in completed.stderr
    assert "check read access to the repository" in completed.stderr
    assert logged_calls(fake_uv_bin) == [f"uvx --from {source} hub --version"]


@pytest.mark.parametrize("runner", SHIM_RUNNERS)
def test_passes_exit_code_through_when_hub_call_fails(
    runner: str,
    *,
    variant_config: HubConfig,
    rendered_tree: Callable[[RenderedHub], Path],
    fake_uv_bin: Path,
) -> None:
    root = a_hub_tree(variant_config, rendered_tree)

    completed = run_shim(
        runner, variant_config, root, fake_uv_bin=fake_uv_bin, env_overrides={FAKE_UVX_RC: "3"}
    )

    assert_shim_exit(runner, completed, 3)
    source = pinned_source(RUN_VERSION)
    assert logged_calls(fake_uv_bin) == [
        f"uvx --from {source} hub --version",
        f"uvx --from {source} {SHIM_CALL[runner]}",
    ]


@pytest.mark.parametrize("runner", SHIM_RUNNERS)
def test_prints_install_hint_when_uv_missing(
    runner: str,
    *,
    variant_config: HubConfig,
    rendered_tree: Callable[[RenderedHub], Path],
    fake_uv_bin: Path,
    no_uv_path: str,
) -> None:
    root = a_hub_tree(variant_config, rendered_tree)

    completed = run_shim(
        runner, variant_config, root, fake_uv_bin=fake_uv_bin, env_overrides={"PATH": no_uv_path}
    )

    assert_shim_exit(runner, completed, 127)
    assert "hub: uv is not installed; see https://docs.astral.sh/uv/" in completed.stderr
    assert logged_calls(fake_uv_bin) == []


@pytest.mark.parametrize("runner", SHIM_RUNNERS)
@pytest.mark.parametrize("hub_json", ["bad-version", "missing"])
def test_calls_no_uvx_when_pinned_version_unreadable(
    runner: str,
    hub_json: str,
    *,
    variant_config: HubConfig,
    rendered_tree: Callable[[RenderedHub], Path],
    fake_uv_bin: Path,
) -> None:
    root = a_hub_tree(variant_config, rendered_tree)
    if hub_json == "missing":
        (root / "hub.json").unlink()
    else:
        document = a_hub_document()
        document["platform"]["version"] = "1.2.3; x"
        (root / "hub.json").write_text(json.dumps(document), encoding="utf-8")

    completed = run_shim(runner, variant_config, root, fake_uv_bin=fake_uv_bin)

    assert completed.returncode != 0
    assert_shim_exit(runner, completed, 1)
    if hub_json == "bad-version":
        assert "hub: platform.version in hub.json must be X.Y.Z" in completed.stderr
    assert logged_calls(fake_uv_bin) == []


# AC-3.15 (Q9): byte form and seeded brain text of every rendered file.
# ADR 0011: any `@@name` or `@@{…}` left after rendering is an unresolved placeholder.
UNRESOLVED_PLACEHOLDER = re.compile(r"@@(?:[A-Za-z_][A-Za-z0-9_]*|\{[^}]*\})")
EMPTY_PATHS = (
    "AGENTS.project.md",
    "brain/_inbox/.gitkeep",
    "brain/domain/.gitkeep",
    "brain/features/.gitkeep",
    "brain/journal/.gitkeep",
    "brain/learnings/.gitkeep",
    "brain/playbooks/.gitkeep",
    "plugin/demo/agents/.gitkeep",
    "plugin/demo/skills/.gitkeep",
)
BRAIN_FRONTMATTER_PATHS = (
    "brain/decisions/index.md",
    "brain/index.md",
    "brain/journal/_template.md",
    "brain/now.md",
)
REAL_DATE = re.compile(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}")
JOURNAL_FIELDS = ("**Context:**", "**Learning:**", "**Action:**", "**Links:**")
PORTUGUESE_JOURNAL_WORDS = ("contexto", "aprendizado", "acao", "titulo")
CONFIG_NAMES = ("demo", "variant")


def rendered_texts(config: HubConfig) -> dict[str, str]:
    """Every rendered file by path, decoded as strict UTF-8."""
    return {file.path: file.content.decode("utf-8") for file in render_hub(config).files}


def frontmatter_lines(text: str) -> list[str]:
    """The lines between a leading ``---`` line and the next one; empty without frontmatter."""
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return []
    return lines[1 : lines.index("---", 1)]


@pytest.mark.parametrize("config_name", CONFIG_NAMES)
def test_leaves_no_placeholder_when_config_rendered(
    config_name: str, request: pytest.FixtureRequest
) -> None:
    config = request.getfixturevalue(f"{config_name}_config")

    for path, text in rendered_texts(config).items():
        assert not UNRESOLVED_PLACEHOLDER.search(text), f"{path}: {text!r}"


@pytest.mark.parametrize("config_name", CONFIG_NAMES)
def test_writes_utf8_lf_final_newline_when_text_rendered(
    config_name: str, request: pytest.FixtureRequest
) -> None:
    config = request.getfixturevalue(f"{config_name}_config")

    for file in render_hub(config).files:
        if file.path in EMPTY_PATHS:
            continue
        text = file.content.decode("utf-8")
        assert "\r" not in text, file.path
        assert text.endswith("\n"), file.path
        assert not text.endswith("\n\n"), file.path


# The rendered hub's pre-commit runs `trailing-whitespace` and `end-of-file-fixer`: a managed file
# they would rewrite on the hub's first commit drifts from what `hub sync` renders.
@pytest.mark.parametrize("config_name", CONFIG_NAMES)
def test_passes_whitespace_hooks_when_config_rendered(
    config_name: str, request: pytest.FixtureRequest
) -> None:
    config = request.getfixturevalue(f"{config_name}_config")

    for file in render_hub(config).files:
        text = file.content.decode("utf-8")
        assert "\r" not in text, file.path
        assert text == "" or (text.endswith("\n") and not text.endswith("\n\n")), file.path
        for number, line in enumerate(text.split("\n"), start=1):
            assert not line.endswith((" ", "\t")), f"{file.path}:{number}"


def test_writes_empty_file_when_gitkeep_or_project_rules_rendered(
    demo_render: dict[str, RenderedFile],
) -> None:
    for path in EMPTY_PATHS:
        assert demo_render[path].content == b"", path


# Spec AC-4.7 (D5, Q-5, Q-11), AGH-16 D2 (E14): the managed `.claude/settings.json` is the rules
# base: the base denies and sandbox, nothing more.
SETTINGS_KEYS = ["$schema", "attribution", "hooks", "includeCoAuthoredBy", "permissions", "sandbox"]
SETTINGS_SCHEMA = "https://json.schemastore.org/claude-code-settings.json"
SETTINGS_ALLOW = ["Bash(git status *)", "Bash(git diff *)", "Bash(git log *)", "Bash(git show *)"]
SETTINGS_DENY_READS = ["Read(**/*.pem)", "Read(**/*.key)"]
# The branches the guard protects (`main`, `master`, the project's and each repo's), sorted.
PROTECTED_BRANCHES = {"demo": ["main", "master"], "variant": ["main", "master", "trunk"]}


def settings_deny(config_name: str) -> list[str]:
    """AGH-16 inventory rows S4a-S4j (E14), the push rows per protected branch: no force or
    protected-branch push, no infra or keychain tools, no ssh, no shell fed by a pipe.
    """
    pushes = [
        rule
        for branch in PROTECTED_BRANCHES[config_name]
        for rule in (f"Bash(git push * {branch})", f"Bash(git push origin HEAD:{branch}*)")
    ]
    return [
        *SETTINGS_DENY_READS,
        "Bash(git push --force*)",
        "Bash(git push -f *)",
        *pushes,
        "Bash(terraform *)",
        "Bash(aws *)",
        "Bash(security *)",
        "Bash(ssh *)",
        "Bash(sh)",
        "Bash(bash)",
    ]


# AGH-16 inventory row S6a (E14): the base sandbox; a project adds its own hosts (row S6b) through
# `settings.project.json`.
SETTINGS_SANDBOX = {
    "enabled": True,
    "allowUnsandboxedCommands": False,
    "excludedCommands": [
        "docker *",
        "gh *",
        "git push *",
        "git fetch *",
        "git pull *",
        "git clone *",
        "git ls-remote *",
    ],
    "network": {
        "allowLocalBinding": True,
        "allowedDomains": [
            "localhost",
            "127.0.0.1",
            "[::1]",
            "pypi.org",
            "files.pythonhosted.org",
            "registry.npmjs.org",
            "*.npmjs.org",
            "github.com",
            "*.github.com",
            "*.githubusercontent.com",
        ],
    },
}
# The project's own keys (D5 "Out"): they come through the seeded `settings.project.json`.
PROJECT_ONLY_SETTINGS = (
    "extraKnownMarketplaces",
    "enabledPlugins",
    "env",
    "skillOverrides",
)
# Event → (matcher, hook file, timeout in seconds); `None`: the group has no matcher.
SETTINGS_HOOKS = {
    "SessionStart": ("startup|resume|clear|compact", "session_start.py", 20),
    "PreToolUse": (
        "Bash|Read|Grep|Glob|Edit|Write|MultiEdit|NotebookEdit|WebFetch",
        "guard.py",
        10,
    ),
    "PostToolUse": ("Edit|Write|MultiEdit", "post_edit.py", 60),
    "Stop": (None, "stop_gate.py", 180),
    "PreCompact": (None, "pre_compact.py", 20),
    "SessionEnd": (None, "session_end.py", 10),
}
SETTINGS_COMMAND = re.compile(
    r'python3 "\$CLAUDE_PROJECT_DIR/(plugin/hub-workflow/hooks/[^"/]+\.py)"'
)
REPO_DIRS = {"demo": ["demo-api"], "variant": ["demo-api", "demo-web"]}


def reject_constant(name: str) -> None:
    """``json.loads`` hook: ``NaN``, ``Infinity`` and ``-Infinity`` are not JSON."""
    msg = f"not JSON: {name}"
    raise ValueError(msg)


def strict_json(content: bytes) -> Any:
    """Parse ``content`` as strict UTF-8 JSON, refusing the non-JSON constants."""
    return json.loads(content.decode("utf-8"), parse_constant=reject_constant)


def hook_groups(hooks: Mapping[str, Any]) -> dict[str, tuple[str | None, str, int]]:
    """Each event's single group as (matcher, hook file name, timeout)."""
    rows = {}
    for event, groups in hooks.items():
        assert len(groups) == 1, event
        assert len(groups[0]["hooks"]) == 1, event
        hook = groups[0]["hooks"][0]
        assert hook["type"] == "command", event
        rows[event] = (groups[0].get("matcher"), hook["command"], hook["timeout"])
    return rows


def key_anywhere(value: Any, key: str) -> bool:
    """Whether ``key`` names a member of any object inside ``value``."""
    if isinstance(value, dict):
        return key in value or any(key_anywhere(child, key) for child in value.values())
    if isinstance(value, list):
        return any(key_anywhere(child, key) for child in value)
    return False


@pytest.mark.parametrize("config_name", CONFIG_NAMES)
def test_holds_rules_base_only_when_settings_rendered(
    config_name: str, request: pytest.FixtureRequest
) -> None:
    config = request.getfixturevalue(f"{config_name}_config")
    rendered = {file.path: file for file in render_hub(config).files}

    settings = strict_json(rendered[".claude/settings.json"].content)

    assert sorted(settings) == SETTINGS_KEYS
    assert settings["$schema"] == SETTINGS_SCHEMA
    assert settings["attribution"] == {"commit": "", "pr": ""}
    assert settings["includeCoAuthoredBy"] is False
    assert settings["permissions"] == {
        "allow": SETTINGS_ALLOW,
        "deny": settings_deny(config_name),
        "additionalDirectories": [f"../{repo_dir}" for repo_dir in REPO_DIRS[config_name]],
    }
    assert set(settings["hooks"]) == set(SETTINGS_HOOKS)
    for event, (matcher, command, timeout) in hook_groups(settings["hooks"]).items():
        expected_matcher, file, expected_timeout = SETTINGS_HOOKS[event]
        assert (matcher, timeout) == (expected_matcher, expected_timeout), event
        match = SETTINGS_COMMAND.fullmatch(command)
        assert match, command
        assert match[1] == f"plugin/hub-workflow/hooks/{file}", command
        # A missing hook file makes `python3` exit 2, which blocks on PreToolUse and Stop.
        assert match[1] in rendered, command
        assert rendered[match[1]].executable, command
    assert "matcher" not in settings["hooks"]["Stop"][0]
    for key in PROJECT_ONLY_SETTINGS:
        assert not key_anywhere(settings, key), key


@pytest.mark.parametrize("config_name", CONFIG_NAMES)
def test_denies_push_and_pipe_rules_when_settings_rendered(
    config_name: str, request: pytest.FixtureRequest
) -> None:
    config = request.getfixturevalue(f"{config_name}_config")
    rendered = {file.path: file for file in render_hub(config).files}

    settings = strict_json(rendered[".claude/settings.json"].content)

    # AGH-16 D2 (E14): the secret reads, then rows S4a-S4j in the inventory's order, exactly.
    assert settings["permissions"]["deny"] == settings_deny(config_name)
    # Claude Code matches each subcommand of a pipe on its own: `Bash(* | sh)` would never match.
    assert not [rule for rule in settings["permissions"]["deny"] if "|" in rule]


@pytest.mark.parametrize("config_name", CONFIG_NAMES)
def test_enables_sandbox_when_settings_rendered(
    config_name: str, request: pytest.FixtureRequest
) -> None:
    config = request.getfixturevalue(f"{config_name}_config")
    rendered = {file.path: file for file in render_hub(config).files}

    settings = strict_json(rendered[".claude/settings.json"].content)

    # AGH-16 D2 (E14), row S6a: the same base in every hub; no tracker or project host (row S6b).
    assert settings["sandbox"] == SETTINGS_SANDBOX
    hosts = set(settings["sandbox"]["network"]["allowedDomains"])
    assert not hosts & {"linear.app", "*.linear.app", "docs.python.org"}, hosts


def test_matches_plugin_hooks_when_settings_compared(demo_render: dict[str, RenderedFile]) -> None:
    settings = strict_json(demo_render[".claude/settings.json"].content)
    plugin = strict_json(demo_render["plugin/hub-workflow/hooks/hooks.json"].content)

    in_settings = hook_groups(settings["hooks"])
    in_plugin = hook_groups(plugin["hooks"])

    # The same hooks, wired two ways: the settings block for cloud sessions (which do not install
    # repo plugins), `hooks.json` for a plugin install. Only the command's root differs.
    assert set(in_settings) == set(in_plugin)
    for event, (matcher, command, timeout) in in_settings.items():
        plugin_matcher, plugin_command, plugin_timeout = in_plugin[event]
        assert (matcher, timeout) == (plugin_matcher, plugin_timeout), event
        assert command == plugin_command.replace(
            "${CLAUDE_PLUGIN_ROOT}", "$CLAUDE_PROJECT_DIR/plugin/hub-workflow"
        ), event


# Spec AC-4.8 (Q-9): the files the generator builds from the config.
BUILT_JSON_PATHS = (
    ".claude/settings.json",
    ".claude/settings.project.json",
    "plugin/{project}/.claude-plugin/plugin.json",
)
# Built too, rendered only when module `marketplace` is selected (AGH-17 D4).
MODULE_BUILT_JSON_PATHS = (
    ".claude-plugin/marketplace.json",
    ".claude-plugin/marketplace.project.json",
)
# Static JSON with no placeholder: rendered byte for byte from its template.
TEMPLATED_JSON_SOURCES = {
    "plugin/hub-workflow/.claude-plugin/plugin.json": (
        "templates/plugin/hub-workflow/claude-plugin/plugin.json.tmpl"
    ),
    "plugin/hub-workflow/hooks/hooks.json": "templates/plugin/hub-workflow/hooks/hooks.json.tmpl",
}


@pytest.mark.parametrize("config_name", CONFIG_NAMES)
def test_writes_json_form_when_generator_json_rendered(
    config_name: str, request: pytest.FixtureRequest
) -> None:
    config = request.getfixturevalue(f"{config_name}_config")
    rendered = {file.path: file for file in render_hub(config).files}
    built = {
        entry.path.replace("@@{project_name}", "{project}") for entry in REGISTRY if entry.build
    }

    assert built == {*BUILT_JSON_PATHS, *MODULE_BUILT_JSON_PATHS}
    assert not set(MODULE_BUILT_JSON_PATHS) & set(rendered)
    for pattern in BUILT_JSON_PATHS:
        content = rendered[pattern.format(project=config.project.name)].content
        value = strict_json(content)
        form = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        assert content == form.encode("utf-8"), pattern
    assert rendered[".claude/settings.project.json"].content == b"{}\n"
    for path, source in TEMPLATED_JSON_SOURCES.items():
        template = files(GENERATOR_PACKAGE).joinpath(*source.split("/")).read_bytes()
        assert rendered[path].content == template, path


def test_writes_json_form_when_marketplace_rendered(all_modules_config: HubConfig) -> None:
    rendered = {file.path: file for file in render_hub(all_modules_config).files}

    for path in MODULE_BUILT_JSON_PATHS:
        content = rendered[path].content
        form = json.dumps(strict_json(content), indent=2, sort_keys=True, ensure_ascii=False)
        assert content == (form + "\n").encode("utf-8"), path
    assert rendered[".claude-plugin/marketplace.project.json"].content == b"{}\n"


@pytest.mark.parametrize("config_name", CONFIG_NAMES)
def test_parses_every_json_when_rendered(config_name: str, request: pytest.FixtureRequest) -> None:
    config = request.getfixturevalue(f"{config_name}_config")

    json_files = [file for file in render_hub(config).files if file.path.endswith(".json")]

    # The two settings files, both manifests, `hooks.json` and the schema.
    assert len(json_files) == 6
    for file in json_files:
        strict_json(file.content)


@pytest.mark.parametrize("config_name", CONFIG_NAMES)
def test_keeps_literal_date_when_brain_seeded(
    config_name: str, request: pytest.FixtureRequest
) -> None:
    config = request.getfixturevalue(f"{config_name}_config")
    texts = rendered_texts(config)

    with_frontmatter = sorted(
        path
        for path, text in texts.items()
        if path.startswith("brain/") and path.endswith(".md") and frontmatter_lines(text)
    )
    assert with_frontmatter == sorted(BRAIN_FRONTMATTER_PATHS)
    for path in with_frontmatter:
        assert "last_verified: YYYY-MM-DD" in frontmatter_lines(texts[path]), path
    for path, text in texts.items():
        assert not REAL_DATE.search(text), f"{path}: {REAL_DATE.search(text)}"


def test_writes_english_journal_template_when_rendered(
    demo_render: dict[str, RenderedFile],
) -> None:
    journal = demo_render["brain/journal/_template.md"].content.decode("utf-8")

    assert not re.search(r"^\s*sources:", journal, re.MULTILINE)
    positions = [journal.index(field) for field in JOURNAL_FIELDS]
    assert positions == sorted(positions)
    assert "### YYYY-MM-DD — " in journal
    for word in PORTUGUESE_JOURNAL_WORDS:
        assert word not in journal.lower(), word


# AC-3.9 (O6): run-time values and the author name are never rendered.
VARIANT_RUN_TIME_VALUES = (
    "make sentinel-fast-q7",
    "make sentinel-full-q7",
    "9.8.7",
    "Sentinel Author Q7",
)


def test_renders_no_run_time_value_when_variant_rendered(
    demo_config: HubConfig, variant_config: HubConfig
) -> None:
    for path, text in rendered_texts(variant_config).items():
        for value in VARIANT_RUN_TIME_VALUES:
            assert value not in text, f"{path} holds {value}"
    for path, text in rendered_texts(demo_config).items():
        assert "Jane Doe" not in text, path


# AC-3.20 (hub rule 5): identifiers of the hubs the templates were split from. Substrings match
# anywhere; tokens match only whole (`AGH-10` matches, `block` does not). Case is ignored.
IDENTIFIER_SUBSTRINGS = ("agent-hub-hub", "jroquette", "roquette", "loki", "tradesentinel")
IDENTIFIER_TOKENS = re.compile(r"(?<![A-Za-z0-9_])(?:agh|lok)(?![A-Za-z0-9_])", re.IGNORECASE)


def project_identifiers(text: str) -> list[str]:
    """The denylisted identifiers found in ``text``, lowercased."""
    lowered = text.lower()
    found = [identifier for identifier in IDENTIFIER_SUBSTRINGS if identifier in lowered]
    return found + [match.lower() for match in IDENTIFIER_TOKENS.findall(text)]


# The one carrier: the platform repository as a pinned install source (`<repository>@v<version>`,
# as the Makefile, the pre-commit hook and the SessionStart hook spell it). A longer name sharing
# its prefix (the owner's own hub repository) is not the carrier and stays flagged.
PLATFORM_CARRIER = re.compile(re.escape(PLATFORM_REPOSITORY) + r"(?=@v)")


def rendered_identifiers(text: str) -> list[str]:
    """Identifiers in rendered text once the platform repository, their one carrier, is removed."""
    return project_identifiers(PLATFORM_CARRIER.sub("", text))


def test_holds_no_project_identifier_when_templates_read() -> None:
    texts = dict(template_texts())

    assert "AGENTS.md.tmpl" in texts
    for name, text in texts.items():
        assert project_identifiers(text) == [], name


def test_holds_no_project_identifier_when_demo_rendered(demo_config: HubConfig) -> None:
    texts = rendered_texts(demo_config)

    assert any(PLATFORM_REPOSITORY in text for text in texts.values())
    for path, text in texts.items():
        assert rendered_identifiers(text) == [], path
    carriers = {path for path, text in texts.items() if PLATFORM_CARRIER.search(text)}
    # The demo selects `cloud`: its setup script warms the pinned release. CI gives the pinned
    # release's repository a read credential (AGH-16 D4).
    assert carriers == {
        ".github/workflows/ci.yml",
        "hub",
        "plugin/hub-workflow/hooks/session_start.py",
        "scripts/cloud-setup.sh",
    }


def test_holds_no_project_identifier_when_demo_paths_and_links_listed(
    demo_config: HubConfig,
) -> None:
    rendered = render_hub(demo_config)

    # AC-4.25: every file path, link path and link target, not only file text.
    assert rendered.links
    names = [
        *(file.path for file in rendered.files),
        *(name for link in rendered.links for name in (link.path, link.target)),
    ]
    for name in names:
        assert project_identifiers(name) == [], name


def test_flags_identifier_when_template_carries_other_owner(demo_config: HubConfig) -> None:
    text = render_template(
        "@@{platform_repository}@v1.0.0\nhttps://github.com/jroquette/other\n",
        substitution_mapping(demo_config),
        source="synthetic.md.tmpl",
    )

    assert rendered_identifiers(f"{PLATFORM_REPOSITORY}@v1.0.0") == []
    assert rendered_identifiers(text) == ["jroquette", "roquette"]
    for suffix in ("-hub", "-hub.git"):
        assert rendered_identifiers(f"{PLATFORM_REPOSITORY}{suffix}@v1.0.0") == [
            "agent-hub-hub",
            "jroquette",
            "roquette",
        ], suffix
        assert rendered_identifiers(f"{PLATFORM_REPOSITORY}{suffix}") == [
            "agent-hub-hub",
            "jroquette",
            "roquette",
        ], suffix


# R10: the seeded brain names only paths the skeleton creates.
BRAIN_PATH = re.compile(r"(?<![\w/.-])brain/[\w./-]*")
DATE_SEGMENT = re.compile(r"YYYY|MM|DD")
BRAIN_INDEX_ENTRY = re.compile(r"`([\w.-]+(?:/[\w.-]+)*(?:/|\.md))`")


def resolvable_path(path: str) -> str:
    """``path`` up to its first date-pattern segment: ``journal/YYYY/MM/DD.md`` → ``journal``."""
    kept = []
    for segment in path.rstrip("/").split("/"):
        if DATE_SEGMENT.search(segment):
            break
        kept.append(segment)
    return "/".join(kept)


def rendered_paths(rendered: Iterable[RenderedFile]) -> set[str]:
    """Every rendered file path and every folder that holds one."""
    paths = set()
    for file in rendered:
        parts = file.path.split("/")
        paths.update("/".join(parts[:end]) for end in range(1, len(parts) + 1))
    return paths


# E4.11 (owner OK): brain paths that no render creates, because a rendered skill, hook or script
# creates them at run time. Closed: path → its producer; each must still be referenced.
RUN_TIME_BRAIN_PATHS = {
    "brain/_inbox/mining/": "scripts/mine_transcripts.py",
    "brain/_inbox/sessions/": "plugin/hub-workflow/hooks/session_end.py",
    "brain/auto/workspace/session-snapshot.md": "plugin/hub-workflow/hooks/pre_compact.py",
    # Written by `hub agent`, which the launcher runs.
    "brain/auto/agent-context.md": "agent",
    "brain/learnings/gotchas/": "plugin/hub-workflow/skills/learn/SKILL.md",
    # Written by `hub run`, which the run-issue target runs (AGH-27).
    "brain/_inbox/runs/": "Makefile",
}


def test_references_created_brain_paths_when_markdown_rendered(demo_config: HubConfig) -> None:
    rendered = render_hub(demo_config).files
    created = rendered_paths(rendered)
    texts = {file.path: file.content.decode("utf-8") for file in rendered}
    run_time = {resolvable_path(path) for path in RUN_TIME_BRAIN_PATHS}

    references = [
        (path, match.rstrip(".,:;"))
        for path, text in texts.items()
        for match in BRAIN_PATH.findall(text)
    ]
    assert references
    for path, reference in references:
        resolved = resolvable_path(reference)
        assert resolved in created or resolved in run_time, f"{path} names {reference}"
    for allowed, producer in RUN_TIME_BRAIN_PATHS.items():
        # Allowlisted only while no render creates it, and named by its producer.
        assert resolvable_path(allowed) not in created, allowed
        assert allowed in texts[producer], (allowed, producer)
    entries = BRAIN_INDEX_ENTRY.findall(texts["brain/index.md"])
    for entry in entries:
        assert resolvable_path(f"brain/{entry}") in created, f"brain/index.md names {entry}"
    brain_folders = {
        path.split("/")[1] for path in texts if path.startswith("brain/") and path.count("/") >= 2
    }
    assert brain_folders <= {resolvable_path(entry).split("/")[0] for entry in entries}


# The managed-files statement of the base AGENTS.md: the one place a hub names what `hub sync`
# rewrites (the seeded README points to it), kept equal to the registry's managed set.
MANAGED_FILES_STATEMENT = re.compile(r"rewrites these managed files: (.*?)\.(?:\s|$)", re.DOTALL)
BACKTICKED = re.compile(r"`([^`]+)`")


# AGH-17 D5: the statement names the selected modules' makefiles by one pattern.
MODULE_FILES_CLAUSE = re.compile(r"each selected module's files \((.*?)\)", re.DOTALL)
SEEDED_SIBLINGS_CLAUSE = re.compile(r"their seeded sibling \((.*?)\), which", re.DOTALL)


def selected_entries(config: HubConfig) -> list[TemplateEntry]:
    """The registry entries ``config`` renders: the base ones and its modules'."""
    selected = config.modules.model_dump(exclude_none=True).keys()
    return [entry for entry in REGISTRY if entry.module is None or entry.module in selected]


def expanded_paths(named: Iterable[str], config: HubConfig) -> list[str]:
    """``named`` with ``mk/<id>.mk`` read as the makefile of each module ``config`` selects."""
    return [
        path
        for item in named
        for path in (list(module_makefiles(config)) if item == MODULE_MAKEFILE_PATTERN else [item])
    ]


@pytest.mark.parametrize("config_name", ["variant_config", "demo_config", "all_modules_config"])
def test_names_every_managed_path_when_agents_rendered(
    request: pytest.FixtureRequest, config_name: str
) -> None:
    config: HubConfig = request.getfixturevalue(config_name)
    agents = text_of(config, "AGENTS.md")
    statements = MANAGED_FILES_STATEMENT.findall(agents)

    assert len(statements) == 1
    named = expanded_paths(BACKTICKED.findall(statements[0]), config)
    # The selected modules' files are named too (AGH-17 D5), and only theirs.
    entries = selected_entries(config)
    managed = [entry.path for entry in entries if entry.ownership is Ownership.MANAGED]
    assert managed
    assert len(named) == len(set(named))
    # E4.10: an item is a managed file, or a folder (`plugin/hub-workflow/`) that holds at least
    # one registry entry and only managed ones.
    for item in named:
        if item.endswith("/"):
            under = [entry for entry in entries if entry.path.startswith(item)]
            assert under, item
            assert all(entry.ownership is Ownership.MANAGED for entry in under), item
        else:
            assert item in managed, item
    # Every managed path is named exactly once: by itself or by one folder that holds it.
    for path in managed:
        covering = [
            item for item in named if item == path or (item.endswith("/") and path.startswith(item))
        ]
        assert len(covering) == 1, (path, covering)


@pytest.mark.parametrize(
    "modules",
    [
        {"bench": {}, "cloud": {}, "contract-sync": {}, "marketplace": {}},
        {"cloud": {}},
        {"marketplace": {}},
        {},
    ],
    ids=["all", "cloud", "marketplace", "none"],
)
def test_names_module_files_when_agents_rendered(modules: dict[str, dict[str, str]]) -> None:
    # A copy: the parametrize values are shared between runs.
    settings = {"contract-sync": {"source": "demo-api", "target": "demo-web"}}
    selected = {module: settings.get(module, value) for module, value in modules.items()}
    document = a_hub_document()
    document["repos"].append(a_second_repo())
    document["modules"] = selected
    config = HubConfig.model_validate(document)
    agents = text_of(config, "AGENTS.md")
    clauses = MODULE_FILES_CLAUSE.findall(agents)
    seeded_clauses = SEEDED_SIBLINGS_CLAUSE.findall(agents)

    module_entries = [entry for entry in REGISTRY if entry.module in modules]
    module_managed = [e.path for e in module_entries if e.ownership is Ownership.MANAGED]
    module_seeded = [e.path for e in module_entries if e.ownership is Ownership.SEEDED]
    assert len(seeded_clauses) == 1
    seeded_named = BACKTICKED.findall(seeded_clauses[0])
    if not modules:
        # A hub names only the files it holds: no module clause, no module sibling.
        assert clauses == []
        assert not [name for name in seeded_named if name.startswith(".claude-plugin/")]
        return
    assert len(clauses) == 1
    named = BACKTICKED.findall(clauses[0])
    # The makefiles by their pattern, first; then each other managed module file once.
    assert named[0] == MODULE_MAKEFILE_PATTERN
    assert sorted(expanded_paths(named, config)) == sorted(module_managed)
    assert [path for path in module_seeded if path not in seeded_named] == []
    assert [name for name in seeded_named if name.startswith(".claude-plugin/")] == module_seeded
    # The clauses keep the list's Markdown form: indented lines, none wider than the template's.
    statement = agents[agents.index("- `hub sync` rewrites") : agents.index("never touches.")]
    assert all(line.startswith("  ") for line in statement.splitlines()[1:]), statement
    assert max(len(line) for line in statement.splitlines()) <= 120, statement


# Owner decision on slice 16: `.claude/settings.json` wires the base plugin's hooks, so enabling
# `hub-workflow` from a marketplace too would run every hook twice (Claude Code merges only
# identical command strings). The base rules say so in one bullet.
DOUBLE_WIRING_RULE = "must not be enabled from a marketplace"


def test_forbids_marketplace_plugin_when_agents_rendered(demo_config: HubConfig) -> None:
    agents = text_of(demo_config, "AGENTS.md")

    bullets = [
        " ".join(bullet.split())
        for bullet in re.split(r"\n(?=- )", agents)
        if DOUBLE_WIRING_RULE in " ".join(bullet.split())
    ]

    assert len(bullets) == 1, bullets
    assert "`.claude/settings.json`" in bullets[0]
    assert "`hub-workflow`" in bullets[0]
    assert "twice" in bullets[0]


def test_points_to_agents_for_managed_files_when_readme_rendered(demo_config: HubConfig) -> None:
    readme = text_of(demo_config, "README.md")

    assert "`AGENTS.md`" in readme
    for entry in REGISTRY:
        if entry.ownership is Ownership.MANAGED and entry.path != "AGENTS.md":
            assert f"`{entry.path}`" not in readme, entry.path


def test_lists_repos_when_readme_rendered(variant_config: HubConfig) -> None:
    readme = text_of(variant_config, "README.md")

    assert "demo-api, demo-web" in readme


# AC-4.33 (Q-17): the seeded .gitignore keeps AGH-10's base entries and ignores what the hooks and
# `make mine` write into the hub at run time (the snapshot holds the last user prompt verbatim).
AGH10_GITIGNORE = (
    ".DS_Store",
    ".env",
    ".env.*",
    "!.env.example",
    ".claude/settings.local.json",
    ".claude/worktrees/",
    "__pycache__/",
    "*.pyc",
    ".venv/",
    "node_modules/",
    ".agent-runs/",
)
RUN_TIME_OUTPUTS = (
    "brain/auto/agent-context.md",
    "brain/_inbox/sessions/",
    "brain/auto/workspace/session-snapshot.md",
    "brain/_inbox/mining/",
)


def test_ignores_run_time_outputs_when_gitignore_rendered(
    demo_config: HubConfig, variant_config: HubConfig
) -> None:
    [demo, variant] = [
        next(file for file in render_hub(config).files if file.path == ".gitignore")
        for config in (demo_config, variant_config)
    ]
    lines = demo.content.decode("utf-8").splitlines()

    assert set(RUN_TIME_OUTPUTS) <= set(lines)
    assert set(AGH10_GITIGNORE) <= set(lines)
    assert len(lines) == len(set(lines))
    assert (demo.kind, demo.ownership) == (Kind.GENERIC, Ownership.SEEDED)
    assert variant.content == demo.content


# AGH-19's purity pattern (spec AC-12.26), verbatim: write, tree-read, clock and environment calls.
PURITY = re.compile(
    r"write_text|write_bytes|\bopen\(|os\.(replace|rename|remove|unlink|mkdir|makedirs|chmod|"
    r"symlink|walk|scandir|lstat|environ)|shutil|Path\.cwd|\bPath\(|"
    r"^\s*(import|from) (datetime|time|random|uuid|getpass|socket)\b"
)
ADAPTER_MODULES = frozenset({"hub_tree.py", "file_adapter.py", "doctor_tree.py"})
RENDERING_MODULES = frozenset(
    {
        "__init__.py",
        "built_json.py",
        "errors.py",
        "hub_template.py",
        "json_form.py",
        "json_merge.py",
        "links.py",
        "placeholders.py",
        "registry.py",
        "render_hub.py",
    }
)


def test_calls_no_io_when_rendering_modules_scanned() -> None:
    generator_root = Path(inspect.getfile(render_hub)).parent
    modules = {path.name: path for path in generator_root.glob("*.py")}
    adapters = [modules.get(name) for name in sorted(ADAPTER_MODULES)]
    assert all(
        path is not None
        and any(PURITY.search(line) for line in path.read_text(encoding="utf-8").splitlines())
        for path in adapters
    )
    assert set(modules) - ADAPTER_MODULES == RENDERING_MODULES

    hits = [
        f"{name}:{number}: {line}"
        for name in sorted(RENDERING_MODULES)
        for number, line in enumerate(
            modules[name].read_text(encoding="utf-8").splitlines(), start=1
        )
        if PURITY.search(line)
    ]

    assert hits == []


def test_passes_budget_and_from_when_run_issue_given(
    variant_config: HubConfig,
    rendered_tree: Callable[[RenderedHub], Path],
    fake_uv_bin: Path,
) -> None:
    root = a_hub_tree(variant_config, rendered_tree)
    hub = f"'{root}/hub'"

    issue = run_make(
        root,
        fake_uv_bin,
        "-n",
        "run-issue",
        "ISSUE=DEM-1",
        "REPO=demo-api",
        "LIVE=1",
        "BUDGET=2",
        "FROM=verify",
    )
    ready = run_make(root, fake_uv_bin, "-n", "next")

    assert issue.returncode == 0, issue.stderr
    assert (
        f"{hub} run 'DEM-1' --repo 'demo-api' --live --budget '2' --from 'verify'"
        in issue.stdout.splitlines()
    )
    assert ready.returncode == 0, ready.stderr
    assert ready.stdout.splitlines() == [f"{hub} next"]
    assert logged_calls(fake_uv_bin) == []


RUN_OUTPUTS = ("brain/_inbox/runs/", "artifacts/", ".agent-runs/")


def test_ignores_run_outputs_when_gitignore_rendered(demo_config: HubConfig) -> None:
    gitignore = next(file for file in render_hub(demo_config).files if file.path == ".gitignore")
    lines = gitignore.content.decode("utf-8").splitlines()

    assert set(RUN_OUTPUTS) <= set(lines)
    assert len(lines) == len(set(lines))


def test_ignores_local_file_when_gitignore_rendered(demo_config: HubConfig) -> None:
    # Each developer's hub.local.json stays out of the hub's commits (AC-65.15).
    gitignore = next(file for file in render_hub(demo_config).files if file.path == ".gitignore")

    assert "hub.local.json" in gitignore.content.decode("utf-8").splitlines()
