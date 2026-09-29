import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import (
    HUB_JSON_PATH,
    HUB_LOCK_PATH,
    LOCK_VERSION,
    HubLock,
    ManagedFileEntry,
    build_hub_lock,
    lock_bytes,
)
from agent_hub.core.hub_files.rendered_file import Ownership
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.json_form import dump_json
from agent_hub.core.testing.builders import a_hub_document

SHA256_HEX = re.compile(r"[0-9a-f]{64}")


@pytest.fixture
def config() -> HubConfig:
    return HubConfig.model_validate(a_hub_document())


@pytest.fixture
def lock(a_rendered_hub: Callable[..., RenderedHub], config: HubConfig) -> HubLock:
    return build_hub_lock(rendered=a_rendered_hub(), config=config)


def written_value(lock: HubLock) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(lock_bytes(lock))
    return value


def test_records_every_file_link_and_hub_json_when_lock_built(
    a_rendered_hub: Callable[..., RenderedHub], config: HubConfig
) -> None:
    rendered = a_rendered_hub()

    value = written_value(build_hub_lock(rendered=rendered, config=config))

    assert set(value) == {"lock_version", "platform_version", "schema_version", "modules", "files"}
    assert value["lock_version"] == LOCK_VERSION == 1
    assert value["platform_version"] == config.platform.version
    assert value["schema_version"] == 1
    rendered_paths = {file.path for file in rendered.files} | {link.path for link in rendered.links}
    assert set(value["files"]) == rendered_paths | {HUB_JSON_PATH}
    assert HUB_LOCK_PATH not in value["files"]


def test_hashes_content_and_bit_when_managed_file_recorded(lock: HubLock) -> None:
    files = written_value(lock)["files"]

    assert files["AGENTS.md"] == {
        "executable": False,
        "ownership": "managed",
        "sha256": hashlib.sha256(b"# Rules\n").hexdigest(),
    }
    assert files["scripts/run.sh"] == {
        "executable": True,
        "ownership": "managed",
        "sha256": hashlib.sha256(b"#!/bin/sh\n").hexdigest(),
    }
    assert SHA256_HEX.fullmatch(files["AGENTS.md"]["sha256"])


def test_records_target_when_link_recorded(lock: HubLock) -> None:
    files = written_value(lock)["files"]

    assert files[".claude/agents/x.md"] == {
        "ownership": "managed",
        "symlink": "../../plugin/agents/x.md",
    }


def test_records_only_ownership_when_seeded(lock: HubLock) -> None:
    files = written_value(lock)["files"]

    for path in ("README.md", ".claude/skills/y", HUB_JSON_PATH):
        assert files[path] == {"ownership": "seeded"}, path


def test_sorts_modules_when_config_order_differs(
    a_rendered_hub: Callable[..., RenderedHub],
) -> None:
    document = a_hub_document()
    document["modules"] = {"marketplace": {}, "contract-sync": {}, "bench": {}}
    config = HubConfig.model_validate(document)

    lock = build_hub_lock(rendered=a_rendered_hub(), config=config)

    assert lock.modules == ("bench", "contract-sync", "marketplace")
    assert written_value(lock)["modules"] == ["bench", "contract-sync", "marketplace"]


def _with_file_changed(hub: RenderedHub, path: str, **update: object) -> RenderedHub:
    files = tuple(
        file.model_copy(update=update) if file.path == path else file for file in hub.files
    )
    return hub.model_copy(update={"files": files})


def _with_link_target(hub: RenderedHub, path: str, target: str) -> RenderedHub:
    links = tuple(
        link.model_copy(update={"target": target}) if link.path == path else link
        for link in hub.links
    )
    return hub.model_copy(update={"links": links})


def _with_platform_version(config: HubConfig, version: str) -> HubConfig:
    document = a_hub_document()
    document["platform"]["version"] = version
    return HubConfig.model_validate(document)


# Each case changes exactly one field, from the render, the config or (for the schema version,
# which the config model pins to 1) the lock itself, and must change the bytes.
CHANGES: dict[str, Callable[[RenderedHub, HubConfig], HubLock]] = {
    "content-byte": lambda hub, config: build_hub_lock(
        rendered=_with_file_changed(hub, "AGENTS.md", content=b"# Rulez\n"), config=config
    ),
    "executable-bit": lambda hub, config: build_hub_lock(
        rendered=_with_file_changed(hub, "AGENTS.md", executable=True), config=config
    ),
    "link-target": lambda hub, config: build_hub_lock(
        rendered=_with_link_target(hub, ".claude/agents/x.md", "../../plugin/agents/z.md"),
        config=config,
    ),
    "ownership": lambda hub, config: build_hub_lock(
        rendered=_with_file_changed(hub, "AGENTS.md", ownership=Ownership.SEEDED), config=config
    ),
    "platform-version": lambda hub, config: build_hub_lock(
        rendered=hub, config=_with_platform_version(config, "9.9.9")
    ),
    "schema-version": lambda hub, config: build_hub_lock(rendered=hub, config=config).model_copy(
        update={"schema_version": 2}
    ),
}


@pytest.mark.parametrize("change", CHANGES.values(), ids=CHANGES.keys())
def test_changes_bytes_when_one_field_changes(
    a_rendered_hub: Callable[..., RenderedHub],
    config: HubConfig,
    change: Callable[[RenderedHub, HubConfig], HubLock],
) -> None:
    hub = a_rendered_hub()
    base = build_hub_lock(rendered=hub, config=config)

    changed = change(hub, config)

    assert lock_bytes(changed) != lock_bytes(base)


def _set_file(path: str, entry: dict[str, Any]) -> Callable[[dict[str, Any]], None]:
    def mutate(value: dict[str, Any]) -> None:
        value["files"][path] = entry

    return mutate


_HASH = "0" * 64
INVALID: dict[str, Callable[[dict[str, Any]], None]] = {
    "unknown-key": lambda value: value.update(extra=1),
    "lock-version-2": lambda value: value.update(lock_version=2),
    "lock-version-true": lambda value: value.update(lock_version=True),
    "managed-file-without-sha256": _set_file("a.md", {"ownership": "managed", "executable": False}),
    "seeded-with-sha256": _set_file("a.md", {"ownership": "seeded", "sha256": _HASH}),
    "sha256-and-symlink": _set_file(
        "a.md", {"ownership": "managed", "executable": False, "sha256": _HASH, "symlink": "b.md"}
    ),
    "uppercase-hex": _set_file(
        "a.md", {"ownership": "managed", "executable": False, "sha256": "A" * 64}
    ),
    "unsorted-modules": lambda value: value.update(modules=["cloud", "bench"]),
    "hub-lock-key": _set_file(HUB_LOCK_PATH, {"ownership": "seeded"}),
    "git-key": _set_file(".git/x", {"ownership": "seeded"}),
    "git-folder-key": _set_file(".git", {"ownership": "seeded"}),
    "duplicate-modules": lambda value: value.update(modules=["bench", "bench"]),
    "unknown-module": lambda value: value.update(modules=["nope"]),
    "schema-version-true": lambda value: value.update(schema_version=True),
    "executable-int": _set_file("a.md", {"ownership": "managed", "executable": 1, "sha256": _HASH}),
    "executable-string": _set_file(
        "a.md", {"ownership": "managed", "executable": "false", "sha256": _HASH}
    ),
}


@pytest.mark.parametrize("mutate", INVALID.values(), ids=INVALID.keys())
def test_rejects_lock_when_invalid(lock: HubLock, mutate: Callable[[dict[str, Any]], None]) -> None:
    value = written_value(lock)
    HubLock.model_validate(value)  # the unchanged value is valid: only the mutation is rejected
    mutate(value)

    with pytest.raises(ValidationError):
        HubLock.model_validate(value)


# Each case is valid only if the clause next to it is no broader than the rule: a ``.git`` prefix
# must not catch ``.gitignore`` or ``.github``, and a link may climb as far as the hub root.
VALID: dict[str, Callable[[dict[str, Any]], None]] = {
    "gitignore-key": _set_file(".gitignore", {"ownership": "seeded"}),
    "github-key": _set_file(".github/x", {"ownership": "seeded"}),
    "link-to-hub-root-folder": _set_file(
        "a/b/c.md", {"ownership": "managed", "symlink": "../../x.md"}
    ),
}


@pytest.mark.parametrize("mutate", VALID.values(), ids=VALID.keys())
def test_accepts_lock_when_valid(lock: HubLock, mutate: Callable[[dict[str, Any]], None]) -> None:
    value = written_value(lock)
    mutate(value)

    assert written_value(HubLock.model_validate(value)) == value


@pytest.mark.parametrize(
    ("path", "target", "problem"),
    [
        ("a.md", "", "must not be empty"),
        ("a.md", "/etc/passwd", "must be relative"),
        ("a/b.md", "../../x", "resolves outside the hub"),
        (".claude/agents/x.md", "../../../x", "resolves outside the hub"),
        ("a.md", "b\x00.md", "must not contain NUL"),
        ("a.md", "./b.md", "must be a normalized POSIX path"),
        ("a.md", "a.md", "must not point at the hub root or at itself"),
    ],
)
def test_rejects_link_target_when_not_inside_hub(
    *, lock: HubLock, path: str, target: str, problem: str
) -> None:
    value = written_value(lock)
    value["files"][path] = {"ownership": "managed", "symlink": target}

    with pytest.raises(ValidationError, match=problem):
        HubLock.model_validate(value)


def test_rejects_assignment_when_lock_frozen(lock: HubLock) -> None:
    with pytest.raises(ValidationError, match="frozen"):
        lock.platform_version = "9.9.9"  # type: ignore[misc]
    entry = lock.files["AGENTS.md"]
    assert isinstance(entry, ManagedFileEntry)
    with pytest.raises(ValidationError, match="frozen"):
        entry.executable = True  # type: ignore[misc]


def test_round_trips_when_written_value_validated(lock: HubLock) -> None:
    assert HubLock.model_validate(json.loads(lock_bytes(lock))) == lock


def test_writes_lock_form_when_bytes_made(lock: HubLock) -> None:
    written = lock_bytes(lock)

    assert written == dump_json(json.loads(written))
    assert written.startswith(b'{\n  "files": {\n    ".claude/agents/x.md": {\n')
    assert written.endswith(b"}\n")
    assert not written.endswith(b"\n\n")
