"""The canonical YAML of a scenario document (docs/design/scenarios.md § Tree format).

hub web's Save writes it, so a file it wrote reads back to the same document and is written
again to the same bytes. PyYAML's safe dumper with no key sorting, Unicode kept and width 100 (a
long ``until`` folds), quoting a text the strict loader would read as a JSON number, boolean or
null (``1e5``); the keys in a fixed order, then any other key in the order given:

- a tree (``version: 2``): ``version``, ``kind``, ``name``, ``revision``, ``description``,
  ``inputs``, ``stages``; a stage's ``name``, ``description``, ``steps``; a step's kind key
  first, then ``id``, ``description``, ``with``, the kind's own keys, ``capture``, ``retry``
  (a Repeat's ``max``, ``until``, ``steps`` inside its ``repeat``);
- a graph (``version: 1``): ``version``, ``kind``, ``name``, ``revision``, ``description``,
  ``environment``, the other keys, ``nodes`` last; a node's ``id``, ``type``,
  ``description``, ``depends_on``, ``when``, ``trigger_rule`` first.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Final

import yaml

from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.tree_document import STEP_KINDS
from agent_hub.core.workflows.document import is_tree

_GRAPH_ORDER: Final = ("version", "kind", "name", "revision", "description", "environment")
_NODE_ORDER: Final = ("id", "type", "description", "depends_on", "when", "trigger_rule")
_TREE_ORDER: Final = ("version", "kind", "name", "revision", "description", "inputs", "stages")
_STAGE_ORDER: Final = ("name", "description", "steps")
_STEP_ORDER: Final = (
    *STEP_KINDS,
    "id",
    "description",
    "with",
    "until",
    "every",
    "timeout",
    "decisions",
    "capture_response",
    "then",
    "else",
    "capture",
    "retry",
)
_REPEAT_ORDER: Final = ("max", "until", "steps")
_WAIT_ORDER: Final = ("duration", "until", "attention", "options")


def render_document(document: Mapping[str, JsonValue]) -> str:
    """The canonical YAML of ``document``, a tree or a graph by its ``version``."""
    ordered = _tree(document) if is_tree(document) else _graph(document)
    return yaml.dump(
        ordered, Dumper=_CanonicalDumper, sort_keys=False, allow_unicode=True, width=100
    )


class _CanonicalDumper(yaml.SafeDumper):
    """``SafeDumper`` that also quotes a text the strict loader would read as a JSON number,
    boolean or null (``1e5``), so the file reads back as written."""


def _represent_text(dumper: yaml.SafeDumper, text: str) -> yaml.ScalarNode:
    try:
        quote = not isinstance(json.loads(text), str)
    except ValueError:
        quote = False
    style = "'" if quote else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", text, style=style)


_CanonicalDumper.add_representer(str, _represent_text)


def _ordered(mapping: Mapping[str, JsonValue], order: Sequence[str]) -> dict[str, JsonValue]:
    """``mapping`` with the keys ``order`` names first, in that order, then the rest."""
    out: dict[str, JsonValue] = {key: mapping[key] for key in order if key in mapping}
    out.update({key: value for key, value in mapping.items() if key not in out})
    return out


def _graph(document: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    ordered = _ordered({k: v for k, v in document.items() if k != "nodes"}, _GRAPH_ORDER)
    nodes = document.get("nodes")
    if isinstance(nodes, list):
        ordered["nodes"] = [_node(node) for node in nodes]
    elif nodes is not None:
        ordered["nodes"] = nodes
    return ordered


def _node(node: JsonValue) -> JsonValue:
    if not isinstance(node, dict):
        return node
    ordered = _ordered(node, _NODE_ORDER)
    body = ordered.get("nodes")
    if isinstance(body, list):
        ordered["nodes"] = [_node(item) for item in body]
    return ordered


def _tree(document: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    ordered = _ordered(document, _TREE_ORDER)
    stages = ordered.get("stages")
    if isinstance(stages, list):
        ordered["stages"] = [_stage(stage) for stage in stages]
    return ordered


def _stage(stage: JsonValue) -> JsonValue:
    if not isinstance(stage, dict):
        return stage
    ordered = _ordered(stage, _STAGE_ORDER)
    ordered.update(_steps_at(ordered, ("steps",)))
    return ordered


def _steps(steps: JsonValue) -> JsonValue:
    return [_step(step) for step in steps] if isinstance(steps, list) else steps


def _steps_at(mapping: Mapping[str, JsonValue], keys: Sequence[str]) -> dict[str, JsonValue]:
    return {key: _steps(mapping[key]) for key in keys if key in mapping}


def _step(step: JsonValue) -> JsonValue:
    if not isinstance(step, dict):
        return step
    ordered = _ordered(step, _STEP_ORDER)
    ordered.update(_steps_at(ordered, ("then", "else")))
    repeat = ordered.get("repeat")
    if isinstance(repeat, dict):
        spec = _ordered(repeat, _REPEAT_ORDER)
        spec.update(_steps_at(spec, ("steps",)))
        ordered["repeat"] = spec
    wait = ordered.get("wait")
    if isinstance(wait, dict):
        ordered["wait"] = _ordered(wait, _WAIT_ORDER)
    together = ordered.get("together")
    if isinstance(together, list):
        ordered["together"] = [_steps(path) for path in together]
    return ordered
