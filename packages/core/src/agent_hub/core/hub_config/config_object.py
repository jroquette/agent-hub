"""The base of every fixed-key object in ``hub.json`` and the field factory for optional keys."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, ClassVar, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetJsonSchemaHandler,
    ModelWrapValidatorHandler,
    ValidationError,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import (
    CoreSchema,
    ErrorDetails,
    InitErrorDetails,
    PydanticCustomError,
    PydanticKnownError,
)

COMMENT_KEY_PREFIX = "_"
# Keys starting with "_" are comments at every object level (ADR 0010); the schema says so too.
COMMENT_KEYS_SCHEMA: dict[str, Any] = {"patternProperties": {f"^{COMMENT_KEY_PREFIX}": {}}}


def drop_comment_keys[Value](data: dict[Any, Value]) -> dict[Any, Value]:
    """The object without its comment keys: string keys that start with ``_``."""
    return {
        key: value
        for key, value in data.items()
        if not (isinstance(key, str) and key.startswith(COMMENT_KEY_PREFIX))
    }


class ConfigObject(BaseModel):
    """A frozen ``hub.json`` object: unknown keys are errors, ``_`` keys are dropped.

    JSON ``null`` is never a value: a key is either absent (and takes its default) or holds a
    value of its type, so the CLI and an editor using the exported schema agree.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        # The ``$schema`` key is an alias; dumping by name would write a key the model rejects.
        serialize_by_alias=True,
        json_schema_extra=COMMENT_KEYS_SCHEMA,
    )

    # Keys that are never valid here, each with the message that says why; a subclass sets them.
    # They are reported like nulls, so they do not hide the object's other errors.
    rejected_keys: ClassVar[Mapping[str, str]] = MappingProxyType({})

    @model_validator(mode="wrap")
    @classmethod
    def _drop_comment_keys_and_reject_null(
        cls, data: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        if not isinstance(data, dict):
            return handler(data)
        kept = drop_comment_keys(data)
        # A null under an unknown key is reported as the unknown key it is.
        declared = {field.alias or name for name, field in cls.model_fields.items()}
        null_keys = [key for key, value in kept.items() if value is None and key in declared]
        rejected = [key for key in kept if key in cls.rejected_keys]
        rest = {key: value for key, value in kept.items() if key not in [*null_keys, *rejected]}
        problems = [*map(_null_error, null_keys)]
        problems.extend(_rejected_error(key, kept[key], cls.rejected_keys[key]) for key in rejected)
        try:
            instance = handler(rest)
        except ValidationError as error:
            if not problems:
                raise
            problems.extend(_rebuilt(error, null_keys))
        else:
            problems.extend(instance.cross_field_problems())
        if problems:
            raise ValidationError.from_exception_data(cls.__name__, problems)
        return instance

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        """The model's schema, without the titles pydantic gives ``absent_by_default`` keys.

        Pydantic titles a key after its attribute, which is not the key (``$schema``), and it
        adds the title after the field's own ``json_schema_extra`` has run.
        """
        json_schema = handler(core_schema)
        properties = handler.resolve_ref_schema(json_schema).get("properties", {})
        for name, field in cls.model_fields.items():
            if field.json_schema_extra is _drop_null_branch:
                for key in {field.alias or name, name}:
                    properties.get(key, {}).pop("title", None)
        return json_schema

    def cross_field_problems(self) -> list[InitErrorDetails]:
        """Checks JSON Schema cannot express, each error with its own location; none by default.

        They run here, not in an after-validator, so a null elsewhere in the object does not
        hide them.
        """
        return []


def _null_error(key: str) -> InitErrorDetails:
    return InitErrorDetails(
        type=PydanticCustomError(
            "null_not_allowed", "null is not a value; give a value or leave the key out"
        ),
        loc=(key,),
        input=None,
    )


def _rejected_error(key: str, value: object, message: str) -> InitErrorDetails:
    return InitErrorDetails(
        type=PydanticCustomError("key_not_allowed", message), loc=(key,), input=value
    )


def _rebuilt(error: ValidationError, null_keys: list[str]) -> list[InitErrorDetails]:
    """The errors of the object without its null keys, minus the ``missing`` errors at them."""
    null_locs = [(key,) for key in null_keys]
    return [
        _same_error(detail)
        for detail in error.errors()
        if not (detail["type"] == "missing" and detail["loc"] in null_locs)
    ]


def _same_error(detail: ErrorDetails) -> InitErrorDetails:
    """Rebuild an error with the same type, message, location, input and context.

    A pydantic error is rebuilt by its type name and context, so it also keeps its url. Any other
    error is a custom one, rebuilt from its message; its context is kept unless formatting the
    message with it again would change the text (pydantic has no escape for ``{name}``).
    """
    context = detail.get("ctx")
    rebuilt = InitErrorDetails(type=detail["type"], loc=detail["loc"], input=detail["input"])
    if _pydantic_message(detail["type"], context) != detail["msg"]:
        custom = PydanticCustomError(detail["type"], detail["msg"], context)
        if custom.message() != detail["msg"]:
            custom = PydanticCustomError(detail["type"], detail["msg"])
        rebuilt["type"] = custom
    elif context is not None:
        rebuilt["ctx"] = context
    return rebuilt


def _pydantic_message(error_type: str, context: dict[str, Any] | None) -> str | None:
    """The message pydantic gives ``error_type`` with ``context``; None when it is not its type."""
    try:
        return PydanticKnownError(error_type, context).message()  # type: ignore[arg-type]
    except KeyError, TypeError:
        # Not a pydantic error type, or one that needs another context: a custom error.
        return None


def _drop_null_branch(schema: dict[str, Any]) -> None:
    schema.pop("default", None)
    branches = schema.pop("anyOf", [])
    for branch in branches:
        if branch != {"type": "null"}:
            schema.update(branch)


def absent_by_default(*, alias: str | None = None) -> Any:
    """A ``Field`` for an optional key typed ``X | None = None``: absent means ``None``.

    Its schema shows only ``X``, with no ``null`` branch, no default and no generated title,
    because ``null`` is rejected as a value (see ``ConfigObject``).
    """
    return Field(default=None, alias=alias, json_schema_extra=_drop_null_branch)
