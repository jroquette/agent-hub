"""The model and the hooks' reader give the same blocked entries for the same files (AC-277.5).

Each shared case (``agent_hub.core.testing.blocked_words_cases``) becomes a rendered demo hub:
its ``hub.json`` is the case's document and its ``hub.local.json`` the case's text (absent when
``None``). The model reads both documents and merges them with ``effective_environments``; the
hooks read both files through ``load_config`` in a child on ``hook_python``. Both must give the
case's words, globs and variable names, each with the first layer listing it. ``$HUB_CONFIG``,
the hooks' third layer, is ``test_hooks_config.py``'s (spec AM-3).
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    LayeredEntry,
    effective_environments,
)
from agent_hub.core.hub_config.local_config import LOCAL_FILE, LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.blocked_words_cases import BLOCKED_WORDS_CASES, BlockedWordsCase

HOOKS = "plugin/hub-workflow/hooks"
# The hooks' blocked entries as (entry, layer) pairs, and the problem they found.
HOOK_BLOCKED_CODE = (
    "import json\nfrom hubhooks import load_config\ncfg = load_config(None)\n"
    "print(json.dumps([cfg.blocked_words, cfg.blocked_files, cfg.blocked_env,"
    " cfg.blocked_problem]))\n"
)


def pairs(entries: tuple[LayeredEntry, ...]) -> list[list[str]]:
    return [[entry.value, entry.layer] for entry in entries]


def model_view(case: BlockedWordsCase) -> EffectiveEnvironments:
    local = case.local_document()
    return effective_environments(
        HubConfig.model_validate(case.hub_document()),
        LocalConfig() if local is None else LocalConfig.model_validate(local),
    )


@pytest.mark.parametrize(
    "case", BLOCKED_WORDS_CASES, ids=[case.name for case in BLOCKED_WORDS_CASES]
)
def test_reads_same_union_when_case_table_read(
    case: BlockedWordsCase,
    *,
    rendered_hub: Callable[[HubConfig], Path],
    demo_config: HubConfig,
    hook_python: str,
    run_python: Callable[..., Any],
    tmp_path: Path,
) -> None:
    hub = rendered_hub(demo_config)
    (hub / "hub.json").write_text(json.dumps(case.hub_document()), encoding="utf-8")
    if case.local_text is not None:
        (hub / LOCAL_FILE).write_text(case.local_text, encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    model = model_view(case)
    words, files, env, problem = run_python(
        hook_python, HOOK_BLOCKED_CODE, path=hub / HOOKS, cwd=elsewhere
    )

    expected = [[list(pair) for pair in layered] for layered in (case.words, case.files, case.env)]
    assert [pairs(model.blocked_words), pairs(model.blocked_files), pairs(model.blocked_env)] == (
        expected
    )
    assert [words, files, env] == expected
    assert problem == ""
