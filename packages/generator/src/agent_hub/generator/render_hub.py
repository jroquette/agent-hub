"""``render_hub``: every file and link of a hub, rendered in memory from a validated ``HubConfig``.

Pure and deterministic: sources are package data read through ``importlib.resources``, or JSON
values built from the config; nothing is written, and no clock, environment, working directory or
hub tree is read. What the project adds (its ``*.project.json`` siblings and its agent and skill
names) comes in as ``ExtensionInputs``, which the caller builds from the tree it read (spec D2).
The same config and inputs render the same bytes on any machine (docs/design/hub-generator.md).
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from importlib.resources import files
from typing import cast

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.extension_inputs import (
    NO_EXTENSIONS,
    PROJECT_JSON_SUFFIX,
    ExtensionInputs,
)
from agent_hub.core.hub_files.rendered_file import Ownership, RenderedFile
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.hub_template import render_template
from agent_hub.generator.json_form import JsonBuilder, dump_json
from agent_hub.generator.json_merge import merge_json
from agent_hub.generator.links import plugin_links, project_links
from agent_hub.generator.placeholders import substitution_mapping
from agent_hub.generator.registry import REGISTRY, TemplateEntry


def render_hub(config: HubConfig, extensions: ExtensionInputs = NO_EXTENSIONS) -> RenderedHub:
    """Render every registry file this config selects and their links, each sorted by path.

    ``extensions`` merges each sibling it holds into its ``X.json`` and links the project's
    agents and skills; the empty value renders what the config alone gives.
    """
    return render_entries(config, REGISTRY, extensions)


def project_json_siblings(config: HubConfig) -> tuple[str, ...]:
    """The ``X.project.json`` paths ``render_hub`` merges for this config, sorted (spec Q-18).

    Each is a seeded built entry whose managed built ``X.json`` renders too: the only paths the
    cli may pass as siblings in ``ExtensionInputs``.
    """
    selected = dict(_selected(config, REGISTRY))
    return tuple(sorted(path for path in selected if _paired_build(path, selected) is not None))


def render_entries(
    config: HubConfig,
    entries: Iterable[TemplateEntry],
    extensions: ExtensionInputs = NO_EXTENSIONS,
) -> RenderedHub:
    """Render the ``entries`` this config selects and their plugin links, each sorted by path.

    An entry of a module renders only when the config selects that module. An entry path may hold
    ``@@{project_name}`` and no other placeholder (``TemplateError``). A built entry's bytes are
    its builder's value in the JSON byte form (``dump_json``). Two files or links with one
    path, or a path under a link's path, raise ``GeneratorError`` naming it. Everything is built
    before anything is returned, so an error leaves no partial result.

    Each sibling of ``extensions`` must be a seeded built ``X.project.json`` whose managed built
    ``X.json`` renders too (else ``ValueError``, a caller bug); ``X.json`` then holds the strict
    merge (``MergeError``). Project agent and skill links come after the base plugin's, which
    keep a name both plugins hold.
    """
    mapping = substitution_mapping(config)
    selected = _selected(config, entries)
    rendered = [_render(entry, path, config=config, mapping=mapping) for path, entry in selected]
    merged = _merged_json(dict(selected), config=config, extensions=extensions)
    rendered = [
        file.model_copy(update={"content": merged[file.path]}) if file.path in merged else file
        for file in rendered
    ]
    base_links = plugin_links(rendered)
    added = project_links(
        project=config.project.name,
        agents=extensions.agents,
        skills=extensions.skills,
        taken={link.path for link in base_links},
    )
    links = tuple(sorted((*base_links, *added), key=lambda link: link.path))
    _refuse_clashes(
        [*(file.path for file in rendered), *(link.path for link in links)],
        link_paths=[link.path for link in links],
    )
    return RenderedHub(files=tuple(sorted(rendered, key=lambda file: file.path)), links=links)


def _selected(
    config: HubConfig, entries: Iterable[TemplateEntry]
) -> list[tuple[str, TemplateEntry]]:
    """The entries this config selects, each with its rendered path, in the given order."""
    path_mapping = {"project_name": config.project.name}
    # Dumped by alias: the closed JSON ids (``contract-sync``) that ``TemplateEntry.module`` uses.
    selected_modules = config.modules.model_dump(exclude_none=True).keys()
    return [
        (render_template(entry.path, path_mapping, source=entry.path), entry)
        for entry in entries
        if entry.module is None or entry.module in selected_modules
    ]


def _target_of(sibling: str) -> str:
    return sibling.removesuffix(PROJECT_JSON_SUFFIX) + ".json"


def _paired_build(path: str, selected: Mapping[str, TemplateEntry]) -> JsonBuilder | None:
    """The builder of the managed built ``X.json`` when ``path`` is its seeded built sibling."""
    if not path.endswith(PROJECT_JSON_SUFFIX):
        return None
    seeded, managed = selected.get(path), selected.get(_target_of(path))
    if (
        seeded is not None
        and seeded.build is not None
        and seeded.ownership is Ownership.SEEDED
        and managed is not None
        and managed.ownership is Ownership.MANAGED
    ):
        return managed.build
    return None


def _merged_json(
    selected: Mapping[str, TemplateEntry], *, config: HubConfig, extensions: ExtensionInputs
) -> dict[str, bytes]:
    """The merged bytes of each ``X.json`` whose sibling ``extensions`` holds, by ``X.json``."""
    merged: dict[str, bytes] = {}
    for sibling, content in extensions.project_json.items():
        build = _paired_build(sibling, selected)
        if build is None:
            msg = f"{sibling}: not a seeded sibling of a managed built JSON file in this render"
            raise ValueError(msg)
        merged[_target_of(sibling)] = merge_json(build(config), content, path=sibling)
    return merged


def _refuse_clashes(paths: Sequence[str], *, link_paths: Sequence[str]) -> None:
    """Raise ``GeneratorError`` naming the first path (code-point order) that clashes.

    A path clashes when it is given twice, or when it lies under a link's path: writing it would
    go through the link.
    """
    repeated = sorted(path for path, count in Counter(paths).items() if count > 1)
    if repeated:
        msg = f"{repeated[0]}: rendered twice (two files or links share this path)"
        raise GeneratorError(msg)
    for path in sorted(paths):
        link_path = next((link for link in link_paths if path.startswith(f"{link}/")), None)
        if link_path is not None:
            msg = f"{path}: lies under the link {link_path}"
            raise GeneratorError(msg)


def _render(
    entry: TemplateEntry, path: str, *, config: HubConfig, mapping: Mapping[str, str]
) -> RenderedFile:
    return RenderedFile(
        path=path,
        content=_content(entry, config=config, mapping=mapping),
        executable=entry.executable,
        kind=entry.kind,
        ownership=entry.ownership,
        module=entry.module,
    )


def _content(entry: TemplateEntry, *, config: HubConfig, mapping: Mapping[str, str]) -> bytes:
    if entry.source is None:
        # ``TemplateEntry`` holds exactly one of ``source`` and ``build``.
        return dump_json(cast(JsonBuilder, entry.build)(config))
    package, name = entry.source
    source = files(package).joinpath(*name.split("/")).read_bytes()
    # Strict UTF-8 and no newline translation: the bytes are the template's, placeholders aside.
    if entry.verbatim:
        return source
    return render_template(source.decode("utf-8"), mapping, source=name).encode("utf-8")
