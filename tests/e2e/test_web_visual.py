"""The screens the owner validated in the playground (AGH-314), compared with their baselines.

Builds this checkout's web app, serves its ``hub web`` on the demo data (``seed_demo``), the way
``make playground-export`` captured the baselines (``scripts/playground_export.py``'s
``demo_web``), then runs ``apps/web/e2e/visual/`` with Playwright: each screen at 1440 x 900, dark
theme, clock frozen at 2026-01-01T12:00:00Z, ``<time>`` masked, against
``apps/web/e2e/visual/baselines/<area>/<route>.png``. Skipped without npm, failed under CI.
"""

import os
import re
import shutil
from pathlib import Path

import pytest

from scripts.playground_export import ROOT, WEB_DIR, demo_web, run_playwright
from scripts.seed_demo import CHAT_SESSION

# The browser compares 17 full screens one after the other: run alone (make test-e2e).
pytestmark = pytest.mark.serial

BASELINES = WEB_DIR / "e2e" / "visual" / "baselines"


def test_matches_baselines_when_demo_screens_rendered(tmp_path: Path) -> None:
    if shutil.which("npm") is None:
        reason = "the visual tests need npm and a Playwright Chromium"
        if os.environ.get("CI"):
            pytest.fail(reason)
        pytest.skip(reason)
    baselines = sorted(BASELINES.glob("*/*.png"))

    with demo_web(ROOT, tmp_path) as web:
        result = run_playwright(
            web,
            WEB_DIR,
            "e2e/visual/",
            extra={
                "AH_VISUAL": "1",
                "AH_VISUAL_CHAT_SESSION": CHAT_SESSION,
                **({"AH_VISUAL_LOGIN": web.login} if web.login else {}),
            },
        )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    # Every baseline is a test, and every test ran.
    assert len(baselines) == 17, baselines
    assert re.search(rf"\b{len(baselines)} passed\b", output), output
    assert "skipped" not in output, output
