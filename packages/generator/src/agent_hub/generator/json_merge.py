"""The strict deep merge of a seeded ``X.project.json`` sibling over its managed ``X.json``.

ADR 0009 and spec Q-18: objects merge by key and the project wins on scalars; arrays are the
template's items then the project's, de-duplicated keeping the first, where two items are equal
when their JSON byte form is (so ``true`` and ``1``, ``1`` and ``1.0`` stay distinct, unlike Python
``==``). The merge only adds: a ``null``, an object or array where the template has another type,
bad JSON, a key that weakens the harness, a key or named entry the managed file owns
(``OWNED_KEYS``, ``NAMED_ARRAYS``) and an entry of a named array without a string ``name`` of its
own are refused, each as one line ``<sibling path>: <key path>: <message>`` (key paths as
``problems.json_path``, ``$`` for the root).
Pure: the sibling's bytes come in, the merged file's bytes go out.
"""

from collections.abc import Mapping, Sequence
from typing import Final

from agent_hub.core.hub_config.problems import json_path
from agent_hub.core.hub_files.extension_inputs import REFUSED_KEYS
from agent_hub.core.json_form import InvalidJsonError, load_json_bytes
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.json_form import JsonValue, dump_json

type KeyPath = tuple[str | int, ...]

_REFUSED: Final = "refused: a project cannot set this key (it weakens the harness)"
_NULL: Final = "null is refused: the merge never deletes a key"
_MARKETPLACE_SIBLING: Final = ".claude-plugin/marketplace.project.json"
# AGH-17 D4 (Q-2): the top-level keys of a managed file its sibling cannot set, by sibling path.
OWNED_KEYS: Final[Mapping[str, tuple[str, ...]]] = {_MARKETPLACE_SIBLING: ("name", "owner")}
# AGH-17 D4 (Q-1): the arrays whose entries are named by `name`, by sibling path; a sibling entry
# with the name of a managed entry is refused (ADR 0009's concatenation is otherwise unchanged).
NAMED_ARRAYS: Final[Mapping[str, tuple[str, ...]]] = {_MARKETPLACE_SIBLING: ("plugins",)}
_OWNED_KEY: Final = "refused: the managed marketplace.json owns this key"
_OWNED_ENTRY: Final = "refused: the managed marketplace.json owns this entry"
# `claude plugin validate` needs each plugin entry named, once.
_TWICE: Final = "refused: the sibling lists this plugin name more than once"
_UNNAMED: Final = "refused: a plugin entry is an object with a string name"
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

    Raises ``MergeError`` for a refused key first, then an owned key, then a named entry the
    template holds, then the first problem in the sibling's own key order.
    """
    try:
        value = load_json_bytes(project, strict=True)
    except InvalidJsonError as error:
        raise MergeError(path=path, key_path=(), message=error.message) from None
    for key_path in REFUSED_KEYS.get(path, ()):
        if _holds(value, key_path):
            raise MergeError(path=path, key_path=key_path, message=_REFUSED)
    if isinstance(value, dict):
        _refuse_owned(template, value, path=path)
    try:
        return dump_json(_merge(template, value, path=path, at=()))
    except RecursionError:
        # The parser reads deeper values than this recursive merge and ``json.dumps`` can walk.
        raise MergeError(path=path, key_path=(), message=_TOO_DEEP) from None


def _refuse_owned(template: JsonValue, project: dict[str, JsonValue], *, path: str) -> None:
    """``MergeError`` at the first key or named entry of ``project`` the managed file owns."""
    for key in OWNED_KEYS.get(path, ()):
        if key in project:
            raise MergeError(path=path, key_path=(key,), message=_OWNED_KEY)
    for key in NAMED_ARRAYS.get(path, ()):
        _refuse_managed_names(template, project, key=key, path=path)


def _refuse_managed_names(
    template: JsonValue, project: dict[str, JsonValue], *, key: str, path: str
) -> None:
    """``MergeError`` at the first ``project[key]`` entry that is not an object with a string
    ``name``, is named like an entry of ``template``, or repeats a name an earlier entry has.
    """
    managed = template.get(key) if isinstance(template, dict) else None
    added = project.get(key)
    if not isinstance(managed, list) or not isinstance(added, list):
        return
    owned = {name for name in map(_name_of, managed) if name is not None}
    seen: set[str] = set()
    for index, entry in enumerate(added):
        name = _name_of(entry)
        if name is None:
            raise MergeError(path=path, key_path=(key, index), message=_UNNAMED)
        if name in owned:
            raise MergeError(path=path, key_path=(key, index, "name"), message=_OWNED_ENTRY)
        if name in seen:
            raise MergeError(path=path, key_path=(key, index, "name"), message=_TWICE)
        seen.add(name)


def _name_of(entry: JsonValue) -> str | None:
    name = entry.get("name") if isinstance(entry, dict) else None
    return name if isinstance(name, str) else None


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
