import hashlib
import json
import os
import shutil
import sys
import zipfile
from collections.abc import Callable, Iterable
from importlib.resources import files
from pathlib import Path
from subprocess import CompletedProcess

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.rendered_file import RenderedFile
from agent_hub.core.hub_files.rendered_link import RenderedLink
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.registry import REGISTRY
from agent_hub.generator.render_hub import render_hub

SHIPPED_SCHEMA = "agent_hub/core/hub_config/hub.schema.json"
GENERATOR_PACKAGE = "agent_hub.generator"
INSTALL_TIMEOUT_SECONDS = 300

# Run by the scratch venv's python, from a cwd outside the repo: renders the demo config with the
# installed wheels and prints where core and the generator were imported from, one row per file
# and one row per link.
RENDER_SCRIPT = """
import hashlib, json
import agent_hub.core, agent_hub.generator
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

rendered = render_hub(HubConfig.model_validate(a_hub_document()))
rows = [
    [f.path, f.kind.value, f.ownership.value, f.module, f.executable,
     hashlib.sha256(f.content).hexdigest()]
    for f in rendered.files
]
links = [
    [link.path, link.target, link.kind.value, link.ownership.value, link.module]
    for link in rendered.links
]
origins = [*agent_hub.core.__path__, *agent_hub.generator.__path__]
print(json.dumps({"origins": origins, "files": rows, "links": links}))
"""


def test_ships_hub_schema_when_core_wheel_built(
    tmp_path: Path, run: Callable[..., CompletedProcess[str]]
) -> None:
    uv = _uv()
    command = [uv, "build", "--package", "agent-hub-core", "--wheel", "--out-dir", str(tmp_path)]

    result = run(command)

    assert result.returncode == 0, result.stderr
    [wheel] = tmp_path.glob("agent_hub_core-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        assert SHIPPED_SCHEMA in archive.namelist()


def test_ships_every_template_when_generator_wheel_built(
    tmp_path: Path, run: Callable[..., CompletedProcess[str]]
) -> None:
    uv = _uv()
    # Generator-built entries have no source (spec Q-9): nothing to ship for them.
    sources = [
        e.source.name
        for e in REGISTRY
        if e.source is not None and e.source.package == GENERATOR_PACKAGE
    ]
    command = [uv, "build", "--package", "agent-hub-generator", "--wheel"]

    result = run([*command, "--out-dir", str(tmp_path)])

    assert result.returncode == 0, result.stderr
    [wheel] = tmp_path.glob("agent_hub_generator-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        shipped = {
            name: archive.read(f"agent_hub/generator/{name}")
            for name in sources
            if f"agent_hub/generator/{name}" in names
        }
    assert "templates/AGENTS.md.tmpl" in sources
    assert sorted(set(sources) - shipped.keys()) == []
    # Byte for byte, the empty .gitkeep sources included.
    assert shipped == {name: _source_bytes(name) for name in sources}
    assert any(content == b"" for content in shipped.values())
    # agent_hub is an implicit namespace shared by every distribution.
    assert "agent_hub/__init__.py" not in names


def test_renders_same_files_when_installed_wheels_run_outside_repo(
    tmp_path: Path, run: Callable[..., CompletedProcess[str]]
) -> None:
    uv = _uv()
    wheels = tmp_path / "wheels"
    for package in ("agent-hub-core", "agent-hub-generator"):
        built = run([uv, "build", "--package", package, "--wheel", "--out-dir", str(wheels)])
        assert built.returncode == 0, built.stderr
    env = {**os.environ}
    # The scratch venv must see only the installed wheels, never the workspace sources.
    for name in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(name, None)
    constraints = tmp_path / "constraints.txt"
    export = [uv, "export", "--locked", "--package", "agent-hub-generator", "--no-emit-workspace"]
    exported = run([*export, "--no-hashes", "-o", str(constraints)], env=env)
    assert exported.returncode == 0, exported.stderr
    venv = tmp_path / "venv"
    created = run([uv, "venv", "--python", sys.executable, str(venv)], env=env)
    assert created.returncode == 0, created.stderr
    python = venv / "bin" / "python"
    install = [uv, "pip", "install", "--python", str(python), "-c", str(constraints)]
    installed = run(
        [*install, *map(str, sorted(wheels.glob("*.whl")))],
        env=env,
        timeout=INSTALL_TIMEOUT_SECONDS,
    )
    assert installed.returncode == 0, installed.stderr
    outside = tmp_path / "outside"
    outside.mkdir()

    result = run([str(python), "-I", "-c", RENDER_SCRIPT], env=env, cwd=outside)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert len(report["origins"]) == 2, report["origins"]
    assert all(Path(origin).is_relative_to(venv) for origin in report["origins"]), report["origins"]
    in_repo = render_hub(HubConfig.model_validate(a_hub_document()))
    assert report["files"] == _rows(in_repo.files)
    assert report["links"] == _link_rows(in_repo.links)
    assert "hub.schema.json" in {row[0] for row in report["files"]}
    # A known link anchors the comparison: a render that lost every link on both sides fails.
    assert ".claude/agents/architect.md" in {row[0] for row in report["links"]}


def _uv() -> str:
    uv = os.environ.get("UV") or shutil.which("uv")
    assert uv is not None, "uv must be on PATH (run the tests with uv run)"
    return uv


def _source_bytes(name: str) -> bytes:
    return files(GENERATOR_PACKAGE).joinpath(*name.split("/")).read_bytes()


def _rows(rendered: Iterable[RenderedFile]) -> list[list[object]]:
    return [
        [
            file.path,
            file.kind.value,
            file.ownership.value,
            file.module,
            file.executable,
            hashlib.sha256(file.content).hexdigest(),
        ]
        for file in rendered
    ]


def _link_rows(links: Iterable[RenderedLink]) -> list[list[object]]:
    return [
        [link.path, link.target, link.kind.value, link.ownership.value, link.module]
        for link in links
    ]
