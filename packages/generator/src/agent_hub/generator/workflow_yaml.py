"""Read a workflow file's bytes into one JSON mapping (docs/design/workflow-schema.md, ADR 0032).

A ``.json`` file goes through core's strict JSON reader. Any other file is YAML, read by a
``SafeLoader`` subclass that refuses what the format does not need and what makes a file mean
something other than it shows: a repeated key, an anchor or alias (reuse comes from ``include``),
a tag or ``%TAG`` directive, and a second document. Its scalars are JSON's: ``true``/``false``,
``null``/``~``/empty, decimal integers and floats; everything else plain is text, so ``on``,
``yes``, ``2026-10-14``, ``012`` and ``1:30`` never change type as YAML 1.1 would have them. A key
must be text. Both forms are capped at ``MAX_WORKFLOW_BYTES`` and must hold a mapping.

The line in an error comes from the parser's marks, never from its message text. What the
mapping means is core's document model; this module only reads it.
"""

import json
import math
import re
from collections.abc import Callable
from typing import Final

import yaml
from yaml.events import AliasEvent, CollectionStartEvent, Event, ScalarEvent, StreamEndEvent
from yaml.nodes import MappingNode, Node, ScalarNode

from agent_hub.core.hub_config.versions import cut_echo
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes
from agent_hub.generator.errors import GeneratorError

MAX_WORKFLOW_BYTES: Final = 256 * 1024
JSON_SUFFIX: Final = ".json"

type WorkflowMapping = dict[str, JsonValue]


class WorkflowFileError(GeneratorError):
    """A workflow file that cannot be read: ``source`` names it, ``line`` (1-based) is where the
    problem is when known, ``reason`` says what it is, on one line."""

    def __init__(self, *, source: str, line: int | None, reason: str) -> None:
        self.source = source
        self.line = line
        self.reason = reason
        where = source if line is None else f"{source}:{line}"
        super().__init__(f"{where}: {reason}")


def load_workflow_bytes(content: bytes, *, source: str) -> WorkflowMapping:
    """The mapping a workflow file holds; JSON when ``source`` ends in ``.json``, else YAML.

    Raises ``WorkflowFileError`` naming ``source`` and, when known, the line.
    """
    if len(content) > MAX_WORKFLOW_BYTES:
        reason = f"the file is over {MAX_WORKFLOW_BYTES} bytes"
        raise WorkflowFileError(source=source, line=None, reason=reason)
    if source.endswith(JSON_SUFFIX):
        value, line = _load_json(content, source=source)
    else:
        value, line = _load_yaml(content, source=source)
    if not isinstance(value, dict):
        reason = "the top level is not a mapping of keys to values"
        raise WorkflowFileError(source=source, line=line, reason=reason)
    return value


def _load_json(content: bytes, *, source: str) -> tuple[JsonValue, int | None]:
    try:
        return load_json_bytes(content, strict=True), 1
    except InvalidJsonError as error:
        raise WorkflowFileError(source=source, line=error.line, reason=error.message) from None


def _load_yaml(content: bytes, *, source: str) -> tuple[JsonValue, int | None]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        reason = f"not UTF-8 text: byte {error.start} cannot be decoded"
        raise WorkflowFileError(source=source, line=None, reason=reason) from None
    loader = _StrictLoader(text)
    try:
        node = loader.get_single_node()
        if node is None:
            return None, None
        value: JsonValue = loader.construct_document(node)
        return value, node.start_mark.line + 1
    except _RefusedError as refusal:
        raise WorkflowFileError(source=source, line=refusal.line, reason=refusal.reason) from None
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        line = None if mark is None else mark.line + 1
        reason = f"not valid YAML: {error.problem or error.context}"
        raise WorkflowFileError(source=source, line=line, reason=reason) from None
    except yaml.YAMLError as error:
        # ReaderError (a character YAML does not allow) carries a position, not a line.
        raise WorkflowFileError(
            source=source, line=None, reason=f"not valid YAML: {error}"
        ) from None
    except RecursionError:
        reason = "not valid YAML here: it is nested too deeply"
        raise WorkflowFileError(source=source, line=None, reason=reason) from None
    finally:
        loader.dispose()


class _RefusedError(Exception):
    """Raised inside the loader; ``line`` is 1-based when the mark has one, ``reason`` completes
    the message."""

    def __init__(self, mark: object, reason: str) -> None:
        line = getattr(mark, "line", None)
        self.line = line + 1 if isinstance(line, int) else None
        self.reason = reason
        super().__init__(reason)


class _StrictLoader(yaml.SafeLoader):
    """A ``SafeLoader`` with JSON's scalars and the refusals in the module docstring."""

    # A dict of its own: SafeLoader's YAML 1.1 resolvers are never consulted.
    yaml_implicit_resolvers = {}

    def get_single_node(self) -> Node | None:
        self._next_event()  # STREAM-START
        node = None if self.check_event(StreamEndEvent) else self.compose_document()
        if not self.check_event(StreamEndEvent):
            raise _RefusedError(self._peek().start_mark, "a file holds one document only")
        self._next_event()  # STREAM-END
        return node

    def compose_document(self) -> Node | None:
        start = self._peek()
        if getattr(start, "tags", None):
            reason = "a %TAG directive is not accepted: tags are refused"
            raise _RefusedError(start.start_mark, reason)
        return super().compose_document()

    def compose_node(self, parent: Node | None, index: int) -> Node | None:
        event = self._peek()
        if isinstance(event, AliasEvent):
            raise _RefusedError(event.start_mark, f"an alias (*{event.anchor}) is not accepted")
        if isinstance(event, ScalarEvent | CollectionStartEvent):
            if event.anchor is not None:
                reason = f"an anchor (&{event.anchor}) is not accepted"
                raise _RefusedError(event.start_mark, reason)
            if event.tag is not None:
                raise _RefusedError(event.start_mark, f"a tag ({event.tag}) is not accepted")
        return super().compose_node(parent, index)

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[object, object]:  # noqa: FBT001, FBT002
        seen: set[str] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node) if isinstance(key_node, ScalarNode) else None
            if not isinstance(key, str):
                raise _RefusedError(key_node.start_mark, "a mapping key is not text")
            if key in seen:
                reason = f"the key {cut_echo(json.dumps(key))} appears more than once"
                raise _RefusedError(key_node.start_mark, reason)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)

    def _peek(self) -> Event:
        # The stubs leave the parser's event methods untyped.
        peek: Callable[[], Event] = self.peek_event
        return peek()

    def _next_event(self) -> Event:
        get: Callable[[], Event] = self.get_event
        return get()


def _construct_int(loader: yaml.SafeLoader, node: ScalarNode) -> int:
    try:
        return int(node.value)
    except ValueError:
        # Python reads integers of at most 4300 digits (sys.get_int_max_str_digits()).
        raise _RefusedError(node.start_mark, "a number has more than 4300 digits") from None


def _construct_float(loader: yaml.SafeLoader, node: ScalarNode) -> float:
    number = float(node.value)
    if math.isinf(number):
        raise _RefusedError(node.start_mark, "a number is too large for this reader")
    return number


_StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:null", re.compile(r"^(?:~|null|Null|NULL|)$"), ["~", "n", "N", ""]
)
_StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)
_StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:int", re.compile(r"^[-+]?[0-9]+$"), list("-+0123456789")
)
_StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(r"^[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?$"),
    list("-+.0123456789"),
)
_StrictLoader.add_constructor("tag:yaml.org,2002:int", _construct_int)
_StrictLoader.add_constructor("tag:yaml.org,2002:float", _construct_float)
