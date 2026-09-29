"""``render_hub``: every file and link of a hub, rendered in memory from a validated ``HubConfig``.

Pure and deterministic: sources are package data read through ``importlib.resources``, or JSON
values built from the config; nothing is written, and no clock, environment, working directory or
hub tree is read. The same config renders the same bytes on any machine
(docs/design/hub-generator.md).
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from importlib.resources import files
from typing import cast

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.rendered_file import RenderedFile
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.hub_template import render_template
from agent_hub.generator.json_form import JsonBuilder, dump_json
from agent_hub.generator.links import plugin_links
from agent_hub.generator.placeholders import substitution_mapping
from agent_hub.generator.registry import REGISTRY, TemplateEntry


def render_hub(config: HubConfig) -> RenderedHub:
    """Render every registry file this config selects and their links, each sorted by path."""
    return render_entries(config, REGISTRY)


def render_entries(config: HubConfig, entries: Iterable[TemplateEntry]) -> RenderedHub:
    """Render the ``entries`` this config selects and their plugin links, each sorted by path.

    An entry of a module renders only when the config selects that module. An entry path may hold
    ``@@{project_name}`` and no other placeholder (``TemplateError``). A built entry's bytes are
    its builder's value in the JSON byte form (``dump_json``). Two files or links with one
    path, or a path under a link's path, raise ``GeneratorError`` naming it. Everything is built
    before anything is returned, so an error leaves no partial result.
    """
    mapping = substitution_mapping(config)
    path_mapping = {"project_name": config.project.name}
    # Dumped by alias: the closed JSON ids (``contract-sync``) that ``TemplateEntry.module`` uses.
    selected_modules = config.modules.model_dump(exclude_none=True).keys()
    rendered = [
        _render(
            entry,
            render_template(entry.path, path_mapping, source=entry.path),
            config=config,
            mapping=mapping,
        )
        for entry in entries
        if entry.module is None or entry.module in selected_modules
    ]
    links = plugin_links(rendered)
    _refuse_clashes(
        [*(file.path for file in rendered), *(link.path for link in links)],
        link_paths=[link.path for link in links],
    )
    return RenderedHub(files=tuple(sorted(rendered, key=lambda file: file.path)), links=links)


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
