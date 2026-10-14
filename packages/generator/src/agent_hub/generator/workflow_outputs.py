"""Workflow output contracts: core's ``OutputValidator`` port over JSON Schema 2020-12.

A value that breaks its node's ``output_format`` fails ``output_contract``; a schema that does
not compile, or names a document it cannot reach (nothing is fetched), fails ``config``. A
message names the path and the broken rule, never the value: the value may be an agent's
output, and a failure's detail must stay safe to show. ``format`` is an annotation, not checked.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Final

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable

from agent_hub.core.features.output_shape import output_path
from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.document import WorkflowDocument, WorkflowProblem
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.substitution import echo

TOO_DEEP: Final = "the schema nests too deeply"
_META: Final = Draft202012Validator(Draft202012Validator.META_SCHEMA)
# An empty registry: a ``$ref`` to another document is never fetched.
_OFFLINE: Final[Registry[bool | Mapping[str, object]]] = Registry()

type _Error = tuple[tuple[str | int, ...], str]


class JsonSchemaOutputs:
    """The ``OutputValidator`` of ``hub workflow run``, ``test`` and ``validate``."""

    def schema_problems(self, schema: Mapping[str, JsonValue]) -> tuple[str, ...]:
        """Each way ``schema`` breaks the 2020-12 meta-schema: ``path: breaks 'rule'``."""
        errors = _schema_errors(schema)
        return tuple(_message(path, rule) if rule else TOO_DEEP for path, rule in errors)

    def check(self, schema: Mapping[str, JsonValue], value: JsonValue) -> None:
        """Raise ``NodeFailedError`` unless ``value`` matches ``schema``."""
        if problems := self.schema_problems(schema):
            detail = "the output_format is not a valid JSON Schema: " + "; ".join(problems)
            raise NodeFailedError("config", detail)
        try:
            errors = _sorted(Draft202012Validator(schema, registry=_OFFLINE).iter_errors(value))
        except Unresolvable as error:
            detail = f"the output_format refers to a schema it cannot read: {echo(error.ref)}"
            raise NodeFailedError("config", detail) from None
        except RecursionError:
            raise NodeFailedError("config", TOO_DEEP) from None
        if errors:
            raise NodeFailedError(
                "output_contract", "; ".join(_message(path, rule) for path, rule in errors)
            )


def output_format_problems(
    document: WorkflowDocument, validator: JsonSchemaOutputs
) -> list[WorkflowProblem]:
    """Each ``output_format`` of ``document`` that does not compile, at its key path."""
    problems: list[WorkflowProblem] = []
    for index, node in enumerate(document.nodes):
        schema = getattr(node, "output_format", None)
        if schema is None:
            continue
        for path, rule in _schema_errors(schema):
            loc = ("nodes", index, "output_format", *path)
            problems.append(WorkflowProblem(loc, f"breaks '{rule}'" if rule else TOO_DEEP))
    return problems


def _schema_errors(schema: Mapping[str, JsonValue]) -> list[_Error]:
    """The meta-schema errors of ``schema``; one with no rule when it nests too deeply."""
    try:
        return _sorted(_META.iter_errors(dict(schema)))
    except RecursionError:
        return [((), "")]


def _sorted(errors: Iterable[ValidationError]) -> list[_Error]:
    return sorted(set(_errors(errors)), key=lambda error: (output_path(error[0]), error[1]))


def _errors(errors: Iterable[ValidationError]) -> Iterator[_Error]:
    for error in errors:
        yield tuple(error.absolute_path), str(error.validator)


def _message(path: Sequence[str | int], rule: str) -> str:
    return f"{output_path(path)}: breaks '{rule}'"
