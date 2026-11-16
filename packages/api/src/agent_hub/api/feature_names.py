"""Feature display names: a nickname the owner gives a feature in the web app (playground).

The slug stays the feature's identity; the name is only how the app shows it. Names live on
this machine, in ``feature-names.json`` beside the hub registry (``~/.config/agent-hub``), keyed
by ``<project>/<slug>``; nothing is written into a hub or a repository. An empty name removes
the nickname, so the app falls back to the slug. A missing or unreadable file is no names.
"""

import json
import os
import threading
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

FILE_NAME: Final = "feature-names.json"
MAX_NAME_CHARS: Final = 80
MAX_KEY_CHARS: Final = 200


class FeatureName(BaseModel):
    """One feature's nickname."""

    model_config = ConfigDict(frozen=True)

    project: str = Field(min_length=1, max_length=MAX_KEY_CHARS)
    slug: str = Field(min_length=1, max_length=MAX_KEY_CHARS)
    name: str


class FeatureNameBody(BaseModel):
    """``PUT /feature-names``: the feature and its new name ("" clears it)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project: str = Field(min_length=1, max_length=MAX_KEY_CHARS)
    slug: str = Field(min_length=1, max_length=MAX_KEY_CHARS)
    name: str = Field(max_length=MAX_NAME_CHARS)


class FeatureNamesView(BaseModel):
    """``GET /feature-names``: every nickname set on this machine."""

    model_config = ConfigDict(frozen=True)

    items: tuple[FeatureName, ...]


def _clean(name: str) -> str:
    return " ".join(name.split())


class FeatureNames:
    """The nicknames file: read on each call, written whole and atomically."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            key: value
            for key, value in data.items()
            if isinstance(key, str) and isinstance(value, str) and "/" in key and value.strip()
        }

    def all(self) -> FeatureNamesView:
        """Every nickname, sorted by project and slug."""
        items = []
        for key, name in sorted(self._read().items()):
            project, _, slug = key.partition("/")
            items.append(FeatureName(project=project, slug=slug, name=name))
        return FeatureNamesView(items=tuple(items))

    def set(self, body: FeatureNameBody) -> FeatureName:
        """Save ``body.name`` for the feature, or forget it when blank."""
        name = _clean(body.name)
        key = f"{body.project}/{body.slug}"
        with self._lock:
            names = self._read()
            if name and name != body.slug:
                names[key] = name
            else:
                names.pop(key, None)
                name = ""
            self._write(names)
        return FeatureName(project=body.project, slug=body.slug, name=name)

    def _write(self, names: dict[str, str]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(names, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
