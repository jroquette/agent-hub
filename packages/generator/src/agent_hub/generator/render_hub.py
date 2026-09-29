"""``render_hub``: every file of a hub, rendered in memory from a validated ``HubConfig``.

Pure and deterministic: sources are package data read through ``importlib.resources``; nothing
is written, and no clock, environment, working directory or hub tree is read. The same config
renders the same bytes on any machine (docs/design/hub-generator.md).
"""

from collections.abc import Iterable, Mapping
from importlib.resources import files

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.rendered_file import RenderedFile
from agent_hub.generator.hub_template import render_template
from agent_hub.generator.placeholders import substitution_mapping
from agent_hub.generator.registry import REGISTRY, TemplateEntry


def render_hub(config: HubConfig) -> tuple[RenderedFile, ...]:
    """Render every registry file this config selects, sorted by path."""
    return render_entries(config, REGISTRY)


def render_entries(config: HubConfig, entries: Iterable[TemplateEntry]) -> tuple[RenderedFile, ...]:
    """Render the ``entries`` this config selects, sorted by path (code-point order).

    An entry of a module renders only when the config selects that module. Every file is built
    before any is returned, so a ``TemplateError`` leaves no partial result.
    """
    mapping = substitution_mapping(config)
    # Dumped by alias: the closed JSON ids (``contract-sync``) that ``TemplateEntry.module`` uses.
    selected_modules = config.modules.model_dump(exclude_none=True).keys()
    rendered = [
        _render(entry, mapping)
        for entry in entries
        if entry.module is None or entry.module in selected_modules
    ]
    return tuple(sorted(rendered, key=lambda file: file.path))


def _render(entry: TemplateEntry, mapping: Mapping[str, str]) -> RenderedFile:
    package, name = entry.source
    source = files(package).joinpath(*name.split("/")).read_bytes()
    # Strict UTF-8 and no newline translation: the bytes are the template's, placeholders aside.
    content = (
        source
        if entry.verbatim
        else render_template(source.decode("utf-8"), mapping, source=name).encode("utf-8")
    )
    return RenderedFile(
        path=entry.path,
        content=content,
        executable=entry.executable,
        kind=entry.kind,
        ownership=entry.ownership,
        module=entry.module,
    )
