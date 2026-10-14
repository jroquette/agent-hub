"""Workflow output contracts: core's ``OutputValidator`` port over JSON Schema 2020-12.

A schema problem is found before any output: a schema that breaks the meta-schema (an invalid
``pattern`` or ``patternProperties`` regex included), or a ``$ref``/``$dynamicRef`` that does
not resolve inside it (nothing is ever fetched), fails ``config``. A value that breaks a valid
schema, or nests deeper than ``MAX_OUTPUT_DEPTH``, fails ``output_contract``.

A message names the path and the broken rule, never a value: paths may hold the value's keys,
each cut to 80 characters, and a detail lists at most ``MAX_MESSAGES`` of them. Details live only
in the run's record (``.agent-runs/``), never in events (ADR 0019). ``format`` is an annotation,
not checked. ``pattern`` regexes are the author's and trusted: authors own their workflows.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Final
from urllib.parse import urljoin

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from agent_hub.core.features.output_shape import output_path
from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.document import WorkflowDocument, WorkflowProblem
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.ports import OutputValidator
from agent_hub.core.workflows.substitution import echo

TOO_DEEP: Final = "the schema nests too deeply"
# As deep as a hook body may nest (``hook_envelope.MAX_JSON_DEPTH``).
MAX_OUTPUT_DEPTH: Final = 64
MAX_MESSAGES: Final = 20
# The format checker makes an invalid regex in ``pattern`` or ``patternProperties`` an error.
_META: Final = Draft202012Validator(
    Draft202012Validator.META_SCHEMA, format_checker=Draft202012Validator.FORMAT_CHECKER
)
# An empty registry: a ``$ref`` to another document is never fetched.
_OFFLINE: Final[Registry[bool | Mapping[str, object]]] = Registry()
_ROOT: Final = "urn:agent-hub:output-format"
_REF_KEYS: Final = ("$ref", "$dynamicRef")
# Keywords whose values are data, not schemas: a ``$ref`` key there is not a reference.
_DATA_KEYS: Final = frozenset({"enum", "const", "default", "examples"})

type _Problem = tuple[tuple[str | int, ...], str]


class JsonSchemaOutputs:
    """The ``OutputValidator`` of ``hub workflow run``, ``test`` and ``validate``."""

    def schema_problems(self, schema: Mapping[str, JsonValue]) -> tuple[str, ...]:
        """Each problem of ``schema``: ``path: breaks 'rule'``, or an unresolvable reference."""
        return tuple(
            message if message == TOO_DEEP else f"{output_path(path)}: {message}"
            for path, message in _schema_problems(schema)
        )

    def check(self, schema: Mapping[str, JsonValue], value: JsonValue) -> None:
        """Raise ``NodeFailedError`` unless ``value`` matches ``schema``."""
        if problems := self.schema_problems(schema):
            detail = "the output_format is not a valid JSON Schema: " + _joined(problems)
            raise NodeFailedError("config", detail)
        if _too_deep(value):
            detail = f"the output nests deeper than {MAX_OUTPUT_DEPTH} levels"
            raise NodeFailedError("output_contract", detail)
        try:
            errors = _sorted(Draft202012Validator(schema, registry=_OFFLINE).iter_errors(value))
        except RecursionError:
            raise NodeFailedError("output_contract", "the output nests too deeply") from None
        if errors:
            messages = [f"{output_path(path)}: {message}" for path, message in errors]
            raise NodeFailedError("output_contract", _joined(messages))


def output_format_problems(
    document: WorkflowDocument, validator: OutputValidator
) -> list[WorkflowProblem]:
    """Each problem of each ``output_format`` of ``document``, at that key."""
    problems: list[WorkflowProblem] = []
    for index, node in enumerate(document.nodes):
        schema = getattr(node, "output_format", None)
        if schema is not None:
            loc = ("nodes", index, "output_format")
            problems.extend(WorkflowProblem(loc, p) for p in validator.schema_problems(schema))
    return problems


def _schema_problems(schema: Mapping[str, JsonValue]) -> list[_Problem]:
    try:
        return _sorted(_META.iter_errors(dict(schema))) or _ref_problems(dict(schema))
    except RecursionError:
        return [((), TOO_DEEP)]


def _ref_problems(schema: dict[str, JsonValue]) -> list[_Problem]:
    """Each ``$ref``/``$dynamicRef`` that does not resolve within ``schema``."""
    resource = Resource.from_contents(schema, default_specification=DRAFT202012)
    registry = _OFFLINE.with_resource(_ROOT, resource).crawl()
    problems: list[_Problem] = []
    pending: list[tuple[JsonValue, tuple[str | int, ...], str]] = [(schema, (), _ROOT)]
    while pending:
        node, path, base = pending.pop()
        if isinstance(node, list):
            pending.extend((item, (*path, i), base) for i, item in enumerate(node))
            continue
        if not isinstance(node, dict):
            continue
        if isinstance(node_id := node.get("$id"), str):
            base = urljoin(base, node_id)
        for key in _REF_KEYS:
            ref = node.get(key)
            if isinstance(ref, str) and not _resolves(registry, base, ref):
                problems.append(((*path, key), f"names a schema that cannot be read: {echo(ref)}"))
        pending.extend(
            (item, (*path, key), base) for key, item in node.items() if key not in _DATA_KEYS
        )
    return sorted(problems, key=lambda problem: output_path(problem[0]))


def _resolves(registry: Registry[bool | Mapping[str, object]], base: str, ref: str) -> bool:
    try:
        registry.resolver(base).lookup(ref)
    except Unresolvable:
        return False
    return True


def _too_deep(value: JsonValue) -> bool:
    pending: list[tuple[JsonValue, int]] = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if isinstance(item, dict | list):
            if depth > MAX_OUTPUT_DEPTH:
                return True
            children = item.values() if isinstance(item, dict) else item
            pending.extend((child, depth + 1) for child in children)
    return False


def _joined(messages: Sequence[str]) -> str:
    shown = list(messages[:MAX_MESSAGES])
    if len(messages) > MAX_MESSAGES:
        shown.append(f"and {len(messages) - MAX_MESSAGES} more")
    return "; ".join(shown)


def _sorted(errors: Iterable[ValidationError]) -> list[_Problem]:
    return sorted(set(_errors(errors)), key=lambda error: (output_path(error[0]), error[1]))


def _errors(errors: Iterable[ValidationError]) -> Iterator[_Problem]:
    for error in errors:
        yield tuple(error.absolute_path), f"breaks '{error.validator}'"
