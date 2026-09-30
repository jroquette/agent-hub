"""The strict deep merge of a seeded ``X.project.json`` sibling over its managed ``X.json``.

ADR 0009 and spec Q-18: objects merge by key and the project wins on scalars; arrays are the
template's items then the project's, de-duplicated keeping the first, where two items are equal
when their JSON byte form is (so ``true`` and ``1``, ``1`` and ``1.0`` stay distinct, unlike Python
``==``). The merge only adds: a ``null``, an object or array where the template has another type,
bad JSON and a key that weakens the harness are refused, each as one line
``<sibling path>: <key path>: <message>`` (key paths as ``problems.json_path``, ``$`` for the root).
Pure: the sibling's bytes come in, the merged file's bytes go out.
"""

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final

from agent_hub.core.hub_config.problems import json_path
from agent_hub.core.json_form import InvalidJsonError, load_json_bytes
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.json_form import JsonValue, dump_json

type KeyPath = tuple[str | int, ...]

# Keys a sibling may not set, whatever their value: they weaken the harness. One definition, for
# the merge now and hub doctor's ``settings.weakening`` rule later (ADR 0009).
REFUSED_KEYS: Final[Mapping[str, tuple[tuple[str, ...], ...]]] = MappingProxyType(
    {".claude/settings.project.json": (("disableAllHooks",), ("permissions", "defaultMode"))}
)
_REFUSED: Final = "refused: a project cannot set this key (it weakens the harness)"
_NULL: Final = "null is refused: the merge never deletes a key"
# The parser's own words for a value nested too deeply (``agent_hub.core.json_form``).
_TOO_DEEP: Final = "not valid JSON here: it is nested too deeply"


class MergeError(GeneratorError):
    """A sibling that cannot be merged: ``<path>: <key path>: <message>``, on one line."""

    def __init__(self, *, path: str, key_path: KeyPath, message: str) -> None:
        self.path = path
        self.key_path = json_path(key_path)
        self.message = message
        super().__init__(f"{path}: {self.key_path}: {message}")


def merge_json(template: JsonValue, project: bytes, *, path: str) -> bytes:
    """Return ``project`` (the sibling at ``path``) merged over ``template``, in the byte form.

    Raises ``MergeError`` for a refused key first, then the first problem in the sibling's own key
    order.
    """
    try:
        value = load_json_bytes(project, strict=True)
    except InvalidJsonError as error:
        raise MergeError(path=path, key_path=(), message=error.message) from None
    for key_path in REFUSED_KEYS.get(path, ()):
        if _holds(value, key_path):
            raise MergeError(path=path, key_path=key_path, message=_REFUSED)
    try:
        return dump_json(_merge(template, value, path=path, at=()))
    except RecursionError:
        # The parser reads deeper values than this recursive merge and ``json.dumps`` can walk.
        raise MergeError(path=path, key_path=(), message=_TOO_DEEP) from None


def _holds(value: JsonValue, key_path: tuple[str, ...]) -> bool:
    for key in key_path:
        if not isinstance(value, dict) or key not in value:
            return False
        value = value[key]
    return True


def _merge(template: JsonValue, project: JsonValue, *, path: str, at: KeyPath) -> JsonValue:
    if isinstance(template, dict) and isinstance(project, dict):
        merged = dict(template)
        for key, item in project.items():
            here = (*at, key)
            merged[key] = (
                _merge(template[key], item, path=path, at=here)
                if key in template
                else _checked(item, path=path, at=here)
            )
        return merged
    if isinstance(template, list) and isinstance(project, list):
        added = [_checked(item, path=path, at=(*at, index)) for index, item in enumerate(project)]
        return _unique([*template, *added])
    if project is None:
        raise MergeError(path=path, key_path=at, message=_NULL)
    if _is_container(template) or _is_container(project):
        message = f"{_type_name(project)} where the template has {_type_name(template)}"
        raise MergeError(path=path, key_path=at, message=message)
    return project


def _checked(value: JsonValue, *, path: str, at: KeyPath) -> JsonValue:
    """``value`` when it holds no ``null`` at any depth; else ``MergeError`` at the first one."""
    if value is None:
        raise MergeError(path=path, key_path=at, message=_NULL)
    if isinstance(value, dict):
        for key, item in value.items():
            _checked(item, path=path, at=(*at, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _checked(item, path=path, at=(*at, index))
    return value


def _is_container(value: JsonValue) -> bool:
    return isinstance(value, dict | list)


def _type_name(value: JsonValue) -> str:
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, list):
        return "an array"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, bool):
        return "a boolean"
    return "null" if value is None else "a number"


def _unique(items: Sequence[JsonValue]) -> list[JsonValue]:
    """``items`` without repeats, keeping the first: equal means the same JSON byte form."""
    seen: set[bytes] = set()
    kept: list[JsonValue] = []
    for item in items:
        form = dump_json(item)
        if form not in seen:
            seen.add(form)
            kept.append(item)
    return kept
