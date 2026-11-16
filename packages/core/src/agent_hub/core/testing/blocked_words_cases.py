"""The shared blocked-word cases: the union the model and the hooks' reader each give.

Each case is a ``hub.json`` (the builders' ``W``, its ``guard`` lists replaced) and an optional
``hub.local.json`` (absent when ``None``), with the blocked words, file globs and variable names
the two files give together: each entry once, by exact text, with the first layer listing it
(``hub.json`` before ``hub.local.json``). No layer removes an entry; an empty list adds
nothing. ``$HUB_CONFIG``, a third layer, is the hooks' only and is not here (spec AM-3).
Synthetic values only.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from agent_hub.core.testing.builders import a_local_environments_document, an_environments_document

HUB: Final = "hub.json"
LOCAL: Final = "hub.local.json"

type Layered = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class BlockedWordsCase:
    """One pair of files and the effective blocked entries they give."""

    name: str
    # ``hub.json``'s ``guard`` blocked lists; ``W``'s other keys are kept.
    hub_guard: Mapping[str, tuple[str, ...]]
    # The whole ``hub.local.json`` as JSON text; ``None`` when the file is absent.
    local_text: str | None
    words: Layered
    files: Layered
    env: Layered = ()

    def hub_document(self) -> dict[str, Any]:
        """``W`` with this case's ``guard`` lists; a fresh copy per call."""
        document = an_environments_document()
        for key in ("blocked_words", "blocked_words_files", "blocked_words_env"):
            document["guard"].pop(key, None)
        document["guard"].update({key: list(value) for key, value in self.hub_guard.items()})
        return document

    def local_document(self) -> dict[str, Any] | None:
        """The parsed ``hub.local.json``, or ``None`` when it is absent; a fresh copy."""
        return None if self.local_text is None else json.loads(self.local_text)


_W_GUARD: Final = MappingProxyType(
    {
        "blocked_words": ("prod", "production"),
        "blocked_words_files": ("config/*.json", "serverless.yml"),
    }
)
_W_WORDS: Final = (("prod", HUB), ("production", HUB))
_W_FILES: Final = (("config/*.json", HUB), ("serverless.yml", HUB))


def _local_with_guard(guard: Mapping[str, list[str]]) -> str:
    document = a_local_environments_document()
    document["guard"] = dict(guard)
    return json.dumps(document)


BLOCKED_WORDS_CASES: Final = (
    BlockedWordsCase(
        name="hub-and-local",
        hub_guard=_W_GUARD,
        local_text=json.dumps(a_local_environments_document()),
        words=(*_W_WORDS, ("demo-live", LOCAL)),
        files=(*_W_FILES, ("deploy/*.tfvars", LOCAL)),
    ),
    BlockedWordsCase(
        name="local-empty-lists",
        hub_guard=_W_GUARD,
        local_text=_local_with_guard(
            {"blocked_words": [], "blocked_words_files": [], "blocked_words_env": []}
        ),
        words=_W_WORDS,
        files=_W_FILES,
    ),
    BlockedWordsCase(
        name="local-absent",
        hub_guard=_W_GUARD,
        local_text=None,
        words=_W_WORDS,
        files=_W_FILES,
    ),
    BlockedWordsCase(
        name="word-in-both-layers",
        hub_guard=_W_GUARD,
        local_text=_local_with_guard(
            {
                "blocked_words": ["production", "edge", "prod"],
                "blocked_words_files": ["serverless.yml"],
            }
        ),
        words=(*_W_WORDS, ("edge", LOCAL)),
        files=_W_FILES,
    ),
    BlockedWordsCase(
        name="env-names-local-only",
        hub_guard=_W_GUARD,
        local_text=_local_with_guard({"blocked_words_env": ["DEMO_STAGE", "DEMO_*"]}),
        words=_W_WORDS,
        files=_W_FILES,
        env=(("DEMO_STAGE", LOCAL), ("DEMO_*", LOCAL)),
    ),
    BlockedWordsCase(
        name="env-names-hub-only",
        hub_guard=MappingProxyType({**_W_GUARD, "blocked_words_env": ("DEMO_STAGE", "DEMO_*")}),
        local_text=json.dumps({"project": {"branch_prefix": "jane/"}}),
        words=_W_WORDS,
        files=_W_FILES,
        env=(("DEMO_STAGE", HUB), ("DEMO_*", HUB)),
    ),
)
