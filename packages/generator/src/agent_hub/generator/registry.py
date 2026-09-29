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


REGISTRY: Final[tuple[TemplateEntry, ...]] = (
    _generic_managed(".github/workflows/ci.yml", "github/workflows/ci.yml.tmpl"),
    _generic_seeded(".gitignore", "gitignore.tmpl"),
    _generic_managed(".pre-commit-config.yaml", "pre-commit-config.yaml.tmpl"),
    _generic_managed("AGENTS.md", "AGENTS.md.tmpl"),
    _project_seeded("AGENTS.project.md", "AGENTS.project.md.tmpl"),
    _generic_managed("CLAUDE.md", "CLAUDE.md.tmpl"),
    _generic_managed("Makefile", "Makefile.tmpl"),
    _project_seeded("Makefile.project", "Makefile.project.tmpl"),
    _generic_seeded("README.md", "README.md.tmpl"),
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
    TemplateEntry(
        path="hub.schema.json",
        source=TemplateSource(SCHEMA_PACKAGE, SCHEMA_FILE),
        kind=Kind.GENERIC,
        ownership=Ownership.MANAGED,
        verbatim=True,
    ),
)
