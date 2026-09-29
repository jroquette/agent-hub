"""``hub.lock`` v1: what ``hub init`` wrote, by path (docs/design/hub-generator.md § hub.lock).

A managed file is recorded by the SHA-256 of its bytes and its executable bit, a managed link by
its relative target, and a seeded path (``hub.json`` included) by its ownership only. The lock
depends only on the render and the config, so the same inputs always give the same bytes. The
builder does no I/O; ``hub sync`` (AGH-14) reads a lock back with ``HubLock.model_validate``.
"""

import hashlib
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from agent_hub.core.hub_config.model import MODULE_IDS, HubConfig, ReleaseVersion, exact_int
from agent_hub.core.hub_files.rendered_file import Ownership, RelativePosixPath
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.json_form import dump_json

LOCK_VERSION: Final = 1
HUB_JSON_PATH: Final = "hub.json"
HUB_LOCK_PATH: Final = "hub.lock"
_GIT_FOLDER = ".git"

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
        if list(self.modules) != sorted(set(self.modules)):
            msg = "modules must be sorted and unique"
            raise ValueError(msg)
        unknown = [module for module in self.modules if module not in MODULE_IDS]
        if unknown:
            msg = f"module {unknown[0]!r} is not one of {', '.join(MODULE_IDS)}"
            raise ValueError(msg)
        for path in self.files:
            if path == HUB_LOCK_PATH:
                msg = f"files must not list {HUB_LOCK_PATH}"
                raise ValueError(msg)
            if path == _GIT_FOLDER or path.startswith(f"{_GIT_FOLDER}/"):
                msg = f"files must not list anything under {_GIT_FOLDER}, got {path!r}"
                raise ValueError(msg)
        return self


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
