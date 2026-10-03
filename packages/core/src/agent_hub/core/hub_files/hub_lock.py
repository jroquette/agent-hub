"""``hub.lock`` v1: what init or sync last wrote, by path (docs/design/hub-sync.md § hub.lock).

A managed file is recorded by the SHA-256 of its bytes and its executable bit, a managed link by
its relative target, and a seeded path (``hub.json`` included) by its ownership only. The lock
depends only on the render and the config, so the same inputs always give the same bytes. The
builder does no I/O, and neither does ``read_hub_lock``, which turns the bytes ``hub sync`` read
back into the lock or into one problem per line.
"""

import hashlib
import re
from collections.abc import Iterator
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator

from agent_hub.core.hub_config.document_check import KEY_MARKER, Location
from agent_hub.core.hub_config.model import MODULE_IDS, HubConfig, ReleaseVersion, exact_int
from agent_hub.core.hub_config.problems import ROOT_PATH, ConfigProblem, json_path, one_line
from agent_hub.core.hub_files.rendered_file import Ownership, RelativePosixPath
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.rendered_link import link_target_problem
from agent_hub.core.json_form import InvalidJsonError, JsonValue, dump_json, load_json_bytes

LOCK_VERSION: Final = 1
HUB_JSON_PATH: Final = "hub.json"
HUB_LOCK_PATH: Final = "hub.lock"
_GIT_FOLDER = ".git"

# What ``hub sync`` prints after the problems of a lock it cannot read (spec Q-6, Q-12).
LOCK_WAY_OUT: Final = "restore it from git, or run hub sync --adopt"
# The same for ``hub sync --adopt``, which needs no lock but refuses a broken one (AGH-16 Q-5).
ADOPT_LOCK_WAY_OUT: Final = "restore it from git, or delete it and re-run hub sync --adopt"
LOCK_NOT_REGULAR: Final = "not a regular file"
ADOPT_POINTER: Final = "hub.lock: not found; run hub sync --adopt to join this hub to the lock"
HUB_JSON_NOT_SEEDED: Final = f"must be seeded: {HUB_JSON_PATH} is the project's"
LONE_SURROGATE: Final = "not UTF-8 text: holds a lone surrogate"

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _tuple_from_json_array(value: object) -> object:
    # A strict tuple field takes no list, and JSON has only arrays: the read form is ``json.loads``.
    return tuple(value) if isinstance(value, list) else value


_LOCK_CONFIG = ConfigDict(frozen=True, extra="forbid", strict=True)


class ManagedFileEntry(BaseModel):
    """A managed file: the SHA-256 of the bytes written and its executable bit."""

    model_config = _LOCK_CONFIG

    ownership: Literal["managed"]
    sha256: Sha256Hex
    executable: bool


class ManagedLinkEntry(BaseModel):
    """A managed link: its target, relative to the link's folder."""

    model_config = _LOCK_CONFIG

    ownership: Literal["managed"]
    symlink: str


class SeededEntry(BaseModel):
    """A seeded path: written once, then the project's, so no hash is kept."""

    model_config = _LOCK_CONFIG

    ownership: Literal["seeded"]


# ``extra="forbid"`` makes the arms exclusive: an entry with both ``sha256`` and ``symlink``, a
# seeded entry with a hash or a managed file without ``sha256`` matches none of them.
type LockEntry = ManagedFileEntry | ManagedLinkEntry | SeededEntry


class HubLock(BaseModel):
    """The whole ``hub.lock``: frozen, and the only form it is written or read in.

    ``files`` is frozen only shallowly: ``build_hub_lock`` is its only producer.
    """

    model_config = _LOCK_CONFIG

    lock_version: Annotated[Literal[1], BeforeValidator(exact_int)]
    platform_version: ReleaseVersion
    schema_version: Annotated[Literal[1], BeforeValidator(exact_int)]
    modules: Annotated[tuple[str, ...], BeforeValidator(_tuple_from_json_array)]
    files: dict[RelativePosixPath, LockEntry]

    @model_validator(mode="after")
    def _modules_and_paths_allowed(self) -> Self:
        _check_modules(self.modules)
        for path, entry in self.files.items():
            _check_path(path)
            if isinstance(entry, ManagedLinkEntry):
                _check_link_target(path, entry.symlink)
        return self


def _check_modules(modules: tuple[str, ...]) -> None:
    if list(modules) != sorted(set(modules)):
        msg = "modules must be sorted and unique"
        raise ValueError(msg)
    unknown = [module for module in modules if module not in MODULE_IDS]
    if unknown:
        msg = f"module {unknown[0]!r} is not one of {', '.join(MODULE_IDS)}"
        raise ValueError(msg)


def _check_path(path: str) -> None:
    if path == HUB_LOCK_PATH:
        msg = f"files must not list {HUB_LOCK_PATH}"
        raise ValueError(msg)
    if path == _GIT_FOLDER or path.startswith(f"{_GIT_FOLDER}/"):
        msg = f"files must not list anything under {_GIT_FOLDER}, got {path!r}"
        raise ValueError(msg)


def _check_link_target(path: str, target: str) -> None:
    # The lock is read back from disk, so a target gets the check ``RenderedLink`` gave it.
    problem = link_target_problem(path, target)
    if problem is not None:
        msg = f"files[{path!r}].symlink {target!r} {problem}"
        raise ValueError(msg)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def build_hub_lock(*, rendered: RenderedHub, config: HubConfig) -> HubLock:
    """The lock of ``rendered`` for ``config``: every file and link, plus ``hub.json`` as seeded."""
    files: dict[str, LockEntry] = {}
    for file in rendered.files:
        if file.ownership is Ownership.MANAGED:
            files[file.path] = ManagedFileEntry(
                ownership="managed", sha256=_sha256(file.content), executable=file.executable
            )
        else:
            files[file.path] = SeededEntry(ownership="seeded")
    for link in rendered.links:
        if link.ownership is Ownership.MANAGED:
            files[link.path] = ManagedLinkEntry(ownership="managed", symlink=link.target)
        else:
            files[link.path] = SeededEntry(ownership="seeded")
    files[HUB_JSON_PATH] = SeededEntry(ownership="seeded")
    return HubLock(
        lock_version=LOCK_VERSION,
        platform_version=config.platform.version,
        schema_version=config.schema_version,
        # Dumped by alias (``ConfigObject``), so the ids are the JSON spelling: ``contract-sync``.
        modules=tuple(sorted(config.modules.model_dump(exclude_none=True))),
        files=dict(sorted(files.items())),
    )


def lock_bytes(lock: HubLock) -> bytes:
    """``lock`` in the one JSON form: sorted keys, two-space indent, UTF-8, final newline."""
    return dump_json(lock.model_dump(mode="json"))


def read_hub_lock(content: bytes) -> HubLock | tuple[ConfigProblem, ...]:
    """The lock ``content`` holds, or its problems, one per line to print after ``hub.lock: ``.

    The JSON problems read as ``hub.json``'s do. A lock the model accepts is still refused when it
    records ``hub.json`` as managed (sync would then compare, rewrite or delete the project's file).
    A key or a string with a lone surrogate (a ``\\ud800``
    escape: no UTF-8 bytes) is reported before the model sees it, one line where each one is.
    """
    try:
        value = load_json_bytes(content)
    except InvalidJsonError as error:
        return (ConfigProblem(ROOT_PATH, error.message),)
    surrogates = tuple(_surrogate_problems(value, ()))
    if surrogates:
        return surrogates
    try:
        lock = HubLock.model_validate(value)
    except ValidationError as error:
        return _problems_from(error, value)
    return _entry_problems(lock) or lock


def _entry_problems(lock: HubLock) -> tuple[ConfigProblem, ...]:
    problems: list[ConfigProblem] = []
    for path, entry in lock.files.items():
        if path == HUB_JSON_PATH and not isinstance(entry, SeededEntry):
            problems.append(ConfigProblem(json_path(("files", path)), HUB_JSON_NOT_SEEDED))
    return tuple(problems)


def _surrogate_problems(value: JsonValue, loc: Location) -> Iterator[ConfigProblem]:
    # Every key and string of the document, in its order: pydantic would otherwise read one as
    # "unable to parse raw data" or print it with replacement characters.
    if isinstance(value, str) and not _is_utf8(value):
        yield ConfigProblem(json_path(loc), LONE_SURROGATE)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not _is_utf8(key):
                yield ConfigProblem(json_path((*loc, key)), LONE_SURROGATE)
            yield from _surrogate_problems(item, (*loc, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _surrogate_problems(item, (*loc, index))


def _is_utf8(text: str) -> bool:
    # Only a lone surrogate has no UTF-8 form.
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


# pydantic names the class it tried in a location or in a type error's message ("Input should be
# a valid dictionary or instance of SeededEntry"), a name the file does not hold.
_VALUE_ERROR_PREFIX = "Value error, "
_MODEL_TYPE_ERROR = "model_type"
_INSTANCE_OF = re.compile(r" or instance of \w+$")


def _problems_from(error: ValidationError, value: JsonValue) -> tuple[ConfigProblem, ...]:
    entries = value.get("files") if isinstance(value, dict) else None
    problems = (
        ConfigProblem(json_path(location), one_line(_message(detail["msg"], detail["type"])))
        for detail in error.errors()
        if (location := _entry_location(detail["loc"], entries)) is not None
    )
    # The arms of a non-object entry all fail with the same line: it is printed once.
    return tuple(dict.fromkeys(problems))


def _entry_location(loc: Location, entries: JsonValue) -> Location | None:
    """``loc`` without the union arm, or ``None`` for an arm the entry's shape does not choose.

    ``files.<path>.<arm>.<field>`` becomes ``files.<path>.<field>``, and a refused key
    (``files.<path>.[key]``) becomes ``files.<path>``.
    """
    if len(loc) < 3 or loc[0] != "files":  # noqa: PLR2004 - files, the path, the arm or key marker
        return loc
    head, arm, rest = loc[:2], loc[2], loc[3:]
    if arm == KEY_MARKER and not rest:
        return head
    entry = entries.get(str(loc[1])) if isinstance(entries, dict) else None
    if isinstance(entry, dict) and arm != _arm_by_shape(entry):
        return None
    return (*head, *rest)


def _arm_by_shape(entry: dict[str, JsonValue]) -> str:
    # The arm the entry was meant to be: its errors are the ones that say what to fix.
    if "symlink" in entry:
        return ManagedLinkEntry.__name__
    if entry.get("ownership") == "seeded":
        return SeededEntry.__name__
    return ManagedFileEntry.__name__


def _message(message: str, error_type: str) -> str:
    # Only a type error ends with the class name: a key or a target may hold the same words.
    if error_type == _MODEL_TYPE_ERROR:
        return _INSTANCE_OF.sub("", message)
    return message.removeprefix(_VALUE_ERROR_PREFIX)
