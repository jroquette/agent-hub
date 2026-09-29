import ast
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

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.versions import PINNED_RELEASE_COMMAND
from agent_hub.core.hub_files.rendered_file import Kind, Ownership, RenderedFile
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.rendered_link import RenderedLink
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.errors import GeneratorError, TemplateError
from agent_hub.generator.hub_template import render_template
from agent_hub.generator.json_form import JsonValue
from agent_hub.generator.placeholders import PLATFORM_REPOSITORY, substitution_mapping
from agent_hub.generator.registry import REGISTRY, TemplateEntry, TemplateSource
from agent_hub.generator.render_hub import render_entries, render_hub

# AC-3.13: the D5 path set of docs/design/hub-generator.md, in code-point order; AC-4.1 adds
# AGH-19's rendered set (spec "The rendered set", for project `demo`).
DESIGN_PATHS = (
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
    "hub.schema.json",
    "plugin/demo/.claude-plugin/plugin.json",
    "plugin/demo/agents/.gitkeep",
    "plugin/demo/hooks/project_guard.py",
    "plugin/demo/skills/.gitkeep",
)

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
    assert rendered.links == ()


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

    rendered = render_entries(a_config_with_modules({"contract-sync": {}}), [entry])

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


def test_takes_no_project_entry_input_when_signature_read() -> None:
    assert list(inspect.signature(render_hub).parameters) == ["config"]


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
        "$(HUB) run $(call hub_quote,ISSUE) --repo $(call hub_quote,REPO) $(if $(LIVE),--live)",
    ]
    assert recipe_lines(makefile, "check")[0] == "@$(HUB) doctor"
    assert "@if [ -d tests ]; then python3 -m unittest discover -s tests -q; fi" in (
        recipe_lines(makefile, "check")
    )
    assert recipe_lines(makefile, "agent") == ["./agent"]
    assert "HUB = hub() {" in makefile


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


# AC-3.19 (Q7, O4): the hygiene hooks of the pinned pre-commit-hooks release.
HYGIENE_HOOKS = ("trailing-whitespace", "end-of-file-fixer", "check-json", "check-yaml")
PLACEHOLDER = re.compile(r"@@(?:\{[A-Za-z_][A-Za-z0-9_]*\}|[A-Za-z_][A-Za-z0-9_]*)")
PINNED_SETUP_UV = re.compile(
    r'- uses: astral-sh/setup-uv@v\d+\n\s+with:\n\s+version: "\d+\.\d+\.\d+"\n'
)


def pre_commit_entry(text: str) -> str:
    """The ``entry: |-`` block scalar of the one hook that has one, dedented."""
    lines = text.splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == "entry: |-")
    key_indent = len(lines[start]) - len(lines[start].lstrip())
    block = []
    for line in lines[start + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= key_indent:
            break
        block.append(line)
    content_indent = min(len(line) - len(line.lstrip()) for line in block if line.strip())
    return "\n".join(line[content_indent:] for line in block)


@pytest.mark.parametrize(("config_name", "branch"), [("demo", "main"), ("variant", "trunk")])
def test_limits_workflow_when_ci_rendered(
    config_name: str, branch: str, request: pytest.FixtureRequest
) -> None:
    config = request.getfixturevalue(f"{config_name}_config")

    ci = text_of(config, ".github/workflows/ci.yml")

    assert "\npermissions:\n  contents: read\n" in ci
    triggers = ci[ci.index("\non:\n") : ci.index("\npermissions:")]
    assert f'  pull_request:\n    branches: ["{branch}"]\n' in triggers
    assert f'  push:\n    branches: ["{branch}"]\n' in triggers
    steps = re.findall(r"^\s+- (?:uses|name|run): .*$", ci, re.MULTILINE)
    assert [step.strip() for step in steps] == [
        "- uses: actions/checkout@v7",
        "- uses: astral-sh/setup-uv@v7",
        "- name: make check",
    ]
    assert PINNED_SETUP_UV.search(ci)
    assert "run: make check" in ci
    assert not re.search(r"(?:version: \"?|@)latest", ci)
    assert "@main" not in ci
    assert "secrets." not in ci
    jobs = ci[ci.index("\njobs:\n") :]
    assert re.findall(r"^  ([a-z][a-z0-9-]*):$", jobs, re.MULTILINE) == ["check"]


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
    # pre-commit splits a `language: system` entry with shlex, then runs it without a shell.
    command = shlex.split(pre_commit_entry(text_of(variant_config, ".pre-commit-config.yaml")))
    bash = shutil.which("bash")
    assert bash is not None, "the pre-commit entry runs bash: install it"
    assert command[0] == "bash"

    completed = subprocess.run(  # noqa: S603 - absolute bash, the rendered entry, no shell
        [bash, *command[1:]],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        cwd=root,
        env=run_env(fake_uv_bin),
    )

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
    for name, text in yaml_texts.items():
        found = 0
        for line in text.splitlines():
            for match in PLACEHOLDER.finditer(line):
                found += 1
                before, after = line[: match.start()], line[match.end() :]
                assert before.count('"') % 2 == 1, f"{name}: {line!r}"
                assert '"' in after, f"{name}: {line!r}"
        assert found, f"{name} has no placeholder"


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
    """A PATH folder holding only what the shims need besides uv: python3 and bash."""
    folder = tmp_path / "no-uv-bin"
    folder.mkdir()
    for tool in ("python3", "bash"):
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
    command = shlex.split(pre_commit_entry(text_of(config, ".pre-commit-config.yaml")))
    bash = shutil.which("bash")
    assert bash is not None, "the pre-commit entry runs bash: install it"
    return subprocess.run(  # noqa: S603 - absolute bash, the rendered entry, no shell
        [bash, *command[1:]],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        cwd=root,
        env=run_env(fake_uv_bin, env_overrides),
    )


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


def test_writes_empty_file_when_gitkeep_or_project_rules_rendered(
    demo_render: dict[str, RenderedFile],
) -> None:
    for path in EMPTY_PATHS:
        assert demo_render[path].content == b"", path


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
# as the Makefile and the pre-commit hook spell it). A longer name sharing its prefix (the owner's
# own hub repository) is not the carrier and stays flagged.
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
    assert carriers == {".pre-commit-config.yaml", "Makefile"}


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


def test_references_created_brain_paths_when_markdown_rendered(demo_config: HubConfig) -> None:
    rendered = render_hub(demo_config).files
    created = rendered_paths(rendered)
    texts = {file.path: file.content.decode("utf-8") for file in rendered}

    references = [
        (path, match.rstrip(".,:;"))
        for path, text in texts.items()
        for match in BRAIN_PATH.findall(text)
    ]
    assert references
    for path, reference in references:
        assert resolvable_path(reference) in created, f"{path} names {reference}"
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


def test_names_every_managed_path_when_agents_rendered(demo_config: HubConfig) -> None:
    agents = text_of(demo_config, "AGENTS.md")
    statements = MANAGED_FILES_STATEMENT.findall(agents)

    assert len(statements) == 1
    named = BACKTICKED.findall(statements[0])
    managed = [entry.path for entry in REGISTRY if entry.ownership is Ownership.MANAGED]
    assert managed
    assert sorted(named) == sorted(managed)


def test_points_to_agents_for_managed_files_when_readme_rendered(demo_config: HubConfig) -> None:
    readme = text_of(demo_config, "README.md")

    assert "`AGENTS.md`" in readme
    for entry in REGISTRY:
        if entry.ownership is Ownership.MANAGED and entry.path != "AGENTS.md":
            assert f"`{entry.path}`" not in readme, entry.path


def test_lists_repos_when_readme_rendered(variant_config: HubConfig) -> None:
    readme = text_of(variant_config, "README.md")

    assert "demo-api, demo-web" in readme
