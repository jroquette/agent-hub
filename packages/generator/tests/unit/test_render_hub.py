import inspect
import subprocess
import sys
from collections.abc import Iterator, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.rendered_file import Kind, Ownership, RenderedFile
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.errors import TemplateError
from agent_hub.generator.registry import REGISTRY, TemplateEntry, TemplateSource
from agent_hub.generator.render_hub import render_entries, render_hub

# AC-3.13: the D5 path set of docs/design/hub-generator.md, in code-point order.
DESIGN_PATHS = (
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


def render_digest(rendered: Sequence[RenderedFile]) -> str:
    """SHA-256 of a canonical dump: per file its fields, its content length, then its bytes.

    Self-contained (imports inside), because the subprocess tests send its source to children.
    """
    import hashlib
    import json

    digest = hashlib.sha256()
    for file in rendered:
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


def a_fixture_entry(package: Path, path: str, text: str) -> TemplateEntry:
    name = f"{path}.tmpl"
    (package / name).write_text(text, encoding="utf-8", newline="")
    return a_template_entry(path, name, source=TemplateSource(FIXTURE_PACKAGE, name))


def test_returns_design_paths_sorted_when_demo_rendered(demo_config: HubConfig) -> None:
    rendered = render_hub(demo_config)

    assert isinstance(rendered, tuple)
    assert tuple(file.path for file in rendered) == DESIGN_PATHS


def test_copies_registry_classification_when_demo_rendered(demo_config: HubConfig) -> None:
    entries = {entry.path: entry for entry in REGISTRY}

    for file in render_hub(demo_config):
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

    assert [(file.path, file.kind, file.module) for file in rendered] == [
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

    assert [file.path for file in rendered] == ["mk/contract-sync.mk"]


def test_skips_module_entry_when_module_unselected(variant_config: HubConfig) -> None:
    readme = a_template_entry("README.md", "templates/README.md.tmpl")

    rendered = render_entries(variant_config, [a_bench_entry(), readme])

    assert [file.path for file in rendered] == ["README.md"]


def test_copies_core_schema_bytes_when_schema_rendered(demo_config: HubConfig) -> None:
    core_schema = files("agent_hub.core.hub_config").joinpath("hub.schema.json").read_bytes()

    schema = {file.path: file for file in render_hub(demo_config)}["hub.schema.json"]

    assert schema.content == core_schema


def test_substitutes_config_values_when_template_rendered(
    demo_config: HubConfig, fixture_templates: Path
) -> None:
    entry = a_fixture_entry(
        fixture_templates, "NAME.md", "# @@{project_name} hub\r\n$HOME @@@@ é\n"
    )

    (rendered,) = render_entries(demo_config, [entry])

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
