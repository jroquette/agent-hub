"""The classification registry: every file the generator renders, and where its text comes from.

One entry per output path, sorted by path, classified as in docs/design/hub-generator.md
§ Classification and rendering. Template sources are package data under ``templates/``, named
without a leading dot and with a ``.tmpl`` suffix, so no tool takes a template for a live config
file. ``hub.schema.json`` is core's shipped schema, copied verbatim: the generator holds no copy.
A JSON file whose value comes from the config is built in code instead (spec Q-9): its entry names
a builder and has no source file.
"""

from dataclasses import dataclass
from typing import Final, NamedTuple

from agent_hub.core.hub_config.schema import SCHEMA_FILE, SCHEMA_PACKAGE
from agent_hub.core.hub_files.rendered_file import Kind, Ownership
from agent_hub.generator.built_json import (
    managed_settings,
    marketplace,
    marketplace_project,
    project_manifest,
    project_settings,
)
from agent_hub.generator.json_form import JsonBuilder

_PACKAGE: Final = "agent_hub.generator"


class TemplateSource(NamedTuple):
    """A package data file, read with ``importlib.resources``.

    ``name`` is POSIX, relative to ``package``: ``templates/AGENTS.md.tmpl``.
    """

    package: str
    name: str


@dataclass(frozen=True, kw_only=True)
class TemplateEntry:
    """One output file of a hub: its path, where its bytes come from and its classification.

    Exactly one of ``source`` (a template) and ``build`` (a JSON builder, rendered in the JSON
    byte form) is set. ``verbatim`` sources are copied byte for byte, never substituted; a built
    entry is never verbatim.
    """

    path: str
    source: TemplateSource | None = None
    build: JsonBuilder | None = None
    kind: Kind
    ownership: Ownership
    module: str | None = None
    executable: bool = False
    verbatim: bool = False

    def __post_init__(self) -> None:
        if self.source is None and self.build is None:
            msg = f"{self.path}: neither a source nor a builder"
            raise ValueError(msg)
        if self.source is not None and self.build is not None:
            msg = f"{self.path}: both a source and a builder"
            raise ValueError(msg)
        if self.build is not None and self.verbatim:
            msg = f"{self.path}: a built entry cannot be verbatim"
            raise ValueError(msg)


def _template(name: str) -> TemplateSource:
    return TemplateSource(_PACKAGE, f"templates/{name}")


def _generic_managed(path: str, template: str) -> TemplateEntry:
    return TemplateEntry(
        path=path, source=_template(template), kind=Kind.GENERIC, ownership=Ownership.MANAGED
    )


def _generic_seeded(path: str, template: str) -> TemplateEntry:
    return TemplateEntry(
        path=path, source=_template(template), kind=Kind.GENERIC, ownership=Ownership.SEEDED
    )


def _project_seeded(path: str, template: str) -> TemplateEntry:
    return TemplateEntry(
        path=path, source=_template(template), kind=Kind.PROJECT_OWNED, ownership=Ownership.SEEDED
    )


def _project_built(path: str, build: JsonBuilder) -> TemplateEntry:
    return TemplateEntry(
        path=path, build=build, kind=Kind.PROJECT_OWNED, ownership=Ownership.SEEDED
    )


def _module_managed(path: str, template: str, module: str) -> TemplateEntry:
    """A file of ``module`` (its closed JSON id): rendered only while ``hub.json`` selects it."""
    return TemplateEntry(
        path=path,
        source=_template(template),
        kind=Kind.MODULE,
        ownership=Ownership.MANAGED,
        module=module,
    )


def _module_entry_point(path: str, module: str) -> TemplateEntry:
    """A module script with a `#!` line: managed, executable, from `<path>.tmpl`."""
    return TemplateEntry(
        path=path,
        source=_template(f"{path}.tmpl"),
        kind=Kind.MODULE,
        ownership=Ownership.MANAGED,
        module=module,
        executable=True,
    )


def _module_built(
    path: str, build: JsonBuilder, module: str, *, ownership: Ownership
) -> TemplateEntry:
    """A JSON file of ``module`` built from the config: rendered only while it is selected."""
    return TemplateEntry(
        path=path, build=build, kind=Kind.MODULE, ownership=ownership, module=module
    )


def _module_makefile(module: str) -> TemplateEntry:
    """``mk/<id>.mk``: the module's make targets, which the base ``Makefile`` includes (D5)."""
    return _module_managed(f"mk/{module}.mk", f"mk/{module}.mk.tmpl", module)


# The project plugin's folder; `render_entries` puts the project name in its placeholder.
_PROJECT_PLUGIN: Final = "plugin/@@{project_name}"
# The base plugin's folder, the same in every hub, and its agents (sorted).
_BASE_PLUGIN: Final = "plugin/hub-workflow"
_BASE_AGENTS: Final = (
    "architect",
    "evaluator",
    "planner",
    "quality-reviewer",
    "requirements-analyst",
    "researcher",
    "spec-reviewer",
)
# The base plugin's skills, one folder each (sorted).
_BASE_SKILLS: Final = (
    "create-plan",
    "feature",
    "fix",
    "handoff",
    "kickoff",
    "learn",
    "recall",
    "research",
)
# The upstream license files the base plugin's NOTICE names (sorted).
_LICENSE_TEXTS: Final = ("Apache-2.0.txt", "MIT-compound-engineering-plugin.txt")


def _entry_point(path: str) -> TemplateEntry:
    """An entry point with a `#!` line: managed, executable, from `<path>.tmpl`."""
    return TemplateEntry(
        path=path,
        source=_template(f"{path}.tmpl"),
        kind=Kind.GENERIC,
        ownership=Ownership.MANAGED,
        executable=True,
    )


def _hook_entry_point(name: str) -> TemplateEntry:
    """A base plugin hook that `hooks.json` runs."""
    return _entry_point(f"{_BASE_PLUGIN}/hooks/{name}.py")


REGISTRY: Final[tuple[TemplateEntry, ...]] = (
    # Module marketplace (AGH-17 D4): the managed part from `project.*`; the project's pins go in
    # the seeded sibling, merged after it.
    _module_built(
        ".claude-plugin/marketplace.json", marketplace, "marketplace", ownership=Ownership.MANAGED
    ),
    _module_built(
        ".claude-plugin/marketplace.project.json",
        marketplace_project,
        "marketplace",
        ownership=Ownership.SEEDED,
    ),
    # The rules base (spec D5); the project's own settings go in the seeded sibling.
    TemplateEntry(
        path=".claude/settings.json",
        build=managed_settings,
        kind=Kind.GENERIC,
        ownership=Ownership.MANAGED,
    ),
    _project_built(".claude/settings.project.json", project_settings),
    _generic_managed(".github/workflows/ci.yml", "github/workflows/ci.yml.tmpl"),
    _generic_seeded(".gitignore", "gitignore.tmpl"),
    _generic_managed(".pre-commit-config.yaml", "pre-commit-config.yaml.tmpl"),
    _generic_managed("AGENTS.md", "AGENTS.md.tmpl"),
    _project_seeded("AGENTS.project.md", "AGENTS.project.md.tmpl"),
    _generic_managed("CLAUDE.md", "CLAUDE.md.tmpl"),
    _generic_managed("Makefile", "Makefile.tmpl"),
    _project_seeded("Makefile.project", "Makefile.project.tmpl"),
    _generic_seeded("README.md", "README.md.tmpl"),
    # The launcher and the shim every hub command goes through (D-shim).
    _entry_point("agent"),
    # Each .gitkeep has its own empty source: every template file is used by exactly one entry.
    _generic_seeded("brain/_inbox/.gitkeep", "brain/_inbox/gitkeep.tmpl"),
    _generic_seeded("brain/decisions/index.md", "brain/decisions/index.md.tmpl"),
    _generic_seeded("brain/domain/.gitkeep", "brain/domain/gitkeep.tmpl"),
    _generic_seeded("brain/features/.gitkeep", "brain/features/gitkeep.tmpl"),
    _generic_seeded("brain/index.md", "brain/index.md.tmpl"),
    _generic_seeded("brain/journal/.gitkeep", "brain/journal/gitkeep.tmpl"),
    _generic_seeded("brain/journal/_template.md", "brain/journal/_template.md.tmpl"),
    _generic_seeded("brain/learnings/.gitkeep", "brain/learnings/gitkeep.tmpl"),
    _generic_seeded("brain/now.md", "brain/now.md.tmpl"),
    _generic_seeded("brain/playbooks/.gitkeep", "brain/playbooks/gitkeep.tmpl"),
    _entry_point("hub"),
    TemplateEntry(
        path="hub.schema.json",
        source=TemplateSource(SCHEMA_PACKAGE, SCHEMA_FILE),
        kind=Kind.GENERIC,
        ownership=Ownership.MANAGED,
        verbatim=True,
    ),
    # Each selected module's make targets (AGH-17 D5); `Makefile` includes them in id order.
    _module_makefile("bench"),
    _module_makefile("cloud"),
    _module_makefile("contract-sync"),
    _module_makefile("marketplace"),
    _project_built(f"{_PROJECT_PLUGIN}/.claude-plugin/plugin.json", project_manifest),
    _project_seeded(f"{_PROJECT_PLUGIN}/agents/.gitkeep", "plugin/project/agents/gitkeep.tmpl"),
    _project_seeded(
        f"{_PROJECT_PLUGIN}/hooks/project_guard.py", "plugin/project/hooks/project_guard.py.tmpl"
    ),
    _project_seeded(f"{_PROJECT_PLUGIN}/skills/.gitkeep", "plugin/project/skills/gitkeep.tmpl"),
    # The base plugin (spec D1): its manifest has no `author` (Q-10); `render_entries` links each
    # agent into `.claude/agents/`.
    _generic_managed(
        f"{_BASE_PLUGIN}/.claude-plugin/plugin.json",
        f"{_BASE_PLUGIN}/claude-plugin/plugin.json.tmpl",
    ),
    # Upstream license texts, byte for byte; the NOTICE points to each.
    *(
        _generic_managed(f"{_BASE_PLUGIN}/LICENSES/{name}", f"{_BASE_PLUGIN}/LICENSES/{name}.tmpl")
        for name in _LICENSE_TEXTS
    ),
    _generic_managed(f"{_BASE_PLUGIN}/NOTICE", f"{_BASE_PLUGIN}/NOTICE.tmpl"),
    *(
        _generic_managed(
            f"{_BASE_PLUGIN}/agents/{name}.md", f"{_BASE_PLUGIN}/agents/{name}.md.tmpl"
        )
        for name in _BASE_AGENTS
    ),
    # The hooks, copied from the hub as they are (spec D4); only the entry points `hooks.json` runs
    # are executable (Q-3): `hubhooks.py` and the reader are their shared modules.
    _hook_entry_point("guard"),
    _generic_managed(f"{_BASE_PLUGIN}/hooks/hooks.json", f"{_BASE_PLUGIN}/hooks/hooks.json.tmpl"),
    _generic_managed(f"{_BASE_PLUGIN}/hooks/hubhooks.py", f"{_BASE_PLUGIN}/hooks/hubhooks.py.tmpl"),
    _hook_entry_point("post_edit"),
    _hook_entry_point("pre_compact"),
    # Runs the project's guard extension in a child for `guard.py` (spec Q-2, Q-5).
    _generic_managed(
        f"{_BASE_PLUGIN}/hooks/project_guard_runner.py",
        f"{_BASE_PLUGIN}/hooks/project_guard_runner.py.tmpl",
    ),
    _hook_entry_point("session_end"),
    _hook_entry_point("session_start"),
    # The hooks' `hub.json` reader: stdlib only, Python 3.9 (spec Q-2).
    _generic_managed(
        f"{_BASE_PLUGIN}/hooks/stdlib_reader.py", f"{_BASE_PLUGIN}/hooks/stdlib_reader.py.tmpl"
    ),
    _hook_entry_point("stop_gate"),
    # `render_entries` links each skill folder into `.claude/skills/`.
    *(
        _generic_managed(
            f"{_BASE_PLUGIN}/skills/{name}/SKILL.md", f"{_BASE_PLUGIN}/skills/{name}/SKILL.md.tmpl"
        )
        for name in _BASE_SKILLS
    ),
    # Module cloud: git identity, fetch or clone the repos in a cloud session (spec D3).
    _module_entry_point("scripts/cloud-setup.sh", "cloud"),
    # Module contract-sync: export in the source repo, then import in the target (spec D1).
    _module_entry_point("scripts/contract-sync.sh", "contract-sync"),
    # The generic scripts the base `mine`/`retro` targets and the `recall` skill run, copied from
    # the hub; they read `hub.json` through the hooks' reader, loaded by path (spec Q-2).
    _entry_point("scripts/mine_transcripts.py"),
    _entry_point("scripts/recall_transcripts.py"),
    _entry_point("scripts/retro_metrics.py"),
)
