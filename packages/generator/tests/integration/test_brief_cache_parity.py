"""The SessionStart hook shows the brief ``hub brief --write-cache`` wrote (ADR 0055).

The CLI writes the cache with core's ``brief_cache_document`` (UTF-8 JSON, the brief cut at 8000
characters, mode 0600) in ``.hub-cache/`` beside its own ``.gitignore``; the hook reads it with a
stdlib copy of the format. Each case writes that document, made 200 s ago (under the 5 min
refresh floor, so no refresh starts), in a rendered demo hub pinned to ``VERSION`` with a ``uvx``
on ``PATH`` that only logs. The hook, on ``hook_python``, must show the brief as written, headed
with its age, and call nothing. The expected text is the case's literal brief, cut at 8000 by
hand where it is longer.
"""

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.workspace.brief_cache import GITIGNORE_TEXT, brief_cache_document

HOOK = "plugin/hub-workflow/hooks/session_start.py"
VERSION = "1.2.3"
CUT = 8000
LOGGER = "#!/bin/sh\nprintf '%s\\n' \"uvx $*\" >> '{log}'\nexit 0\n"
# Briefs whose bytes the two sides must agree on: JSON escapes, non-ASCII, past the cut.
BRIEFS = {
    "plain": "# Brief\n\n## Now\nShip the cache.\n",
    "non_ascii": "# Brief\n\n## Now\nCafé … résumé, naïve, 𝄞 clef\n",
    "json_specials": '# Brief\n\n- "quoted" \\ back\\slash\tand a tab </script>\n-   line\n',
    "past_cut": "# Brief\n" + "word " * 2000,
}


@pytest.mark.parametrize("case", sorted(BRIEFS))
def test_reads_what_cli_wrote_when_hook_reads_cache(
    case: str,
    *,
    rendered_hub: Callable[[HubConfig], Path],
    demo_config: HubConfig,
    tmp_path: Path,
    hook_python: str,
    run_hook_file: Callable[..., Any],
) -> None:
    brief = BRIEFS[case]
    hub = rendered_hub(demo_config).resolve()
    document = a_hub_document()
    document["platform"]["version"] = VERSION
    (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "uvx-calls.log"
    (bin_dir / "uvx").write_text(LOGGER.format(log=log), encoding="utf-8")
    (bin_dir / "uvx").chmod(0o755)
    folder = hub / ".hub-cache"
    folder.mkdir()
    (folder / ".gitignore").write_text(GITIGNORE_TEXT, encoding="utf-8")
    descriptor = os.open(folder / "brief.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as cache:
        cache.write(brief_cache_document(brief, made_at=time.time() - 200))
    expected = brief[:CUT].strip()
    assert expected.startswith("# Brief")

    completed = run_hook_file(
        hook_python,
        hub / HOOK,
        stdin=json.dumps(
            {"session_id": "abcdef123456", "cwd": str(hub), "source": "startup"}
        ).encode(),
        cwd=hub.parent,
        env={"PATH": str(bin_dir), "HOME": str(tmp_path / "home")},
    )

    assert (completed.returncode, completed.stderr) == (0, b"")
    output = json.loads(completed.stdout)["hookSpecificOutput"]
    assert output["additionalContext"] == f"(brief from 3 min ago)\n\n{expected}"
    assert not log.exists()


def test_writes_same_gitignore_when_hook_and_cli_create_cache_folder(
    rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig
) -> None:
    # The hook rewrites a .gitignore that differs from its copy, so a drift would make the hook
    # and hub brief --write-cache rewrite each other's file on every run.
    source = (rendered_hub(demo_config) / HOOK).read_text(encoding="utf-8")

    assert f"CACHE_GITIGNORE = {json.dumps(GITIGNORE_TEXT)}\n" in source
