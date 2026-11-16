from agent_hub.core.hubs.now_note import now_sections
from agent_hub.core.projects.project_views import NowItem

LABELLED = b"""---
type: now
last_verified: 2026-10-09
provenance: agent
---
# Now

- **Focus:** Phase 2 control plane.
  - **AGH-200** in progress: Wave 1 streams.
    Second line of the same item.
  - Hub registry and doctor move.
- **Where it is:**
  - Not a section.
- **Next:**
  1. Merge Wave 1.
  2. Start Wave 2.
- **Watch:** nothing yet.
"""

HEADINGS = b"""# Now

## Focus

- Ship the release.

## Next

- Tag it.

## Watch

- CI time.
- Flaky e2e.

## Done

- Old things.
"""


def test_splits_labelled_bullets_when_note_uses_bold_labels() -> None:
    focus, next_items, watch = now_sections(LABELLED)

    stamp = {"last_verified": "2026-10-09", "provenance": "agent"}
    assert focus == (
        NowItem(text="Phase 2 control plane.", **stamp),
        NowItem(
            text="**AGH-200** in progress: Wave 1 streams. Second line of the same item.", **stamp
        ),
        NowItem(text="Hub registry and doctor move.", **stamp),
    )
    assert [item.text for item in next_items] == ["Merge Wave 1.", "Start Wave 2."]
    assert [item.text for item in watch] == ["nothing yet."]


def test_splits_headings_when_note_uses_sections() -> None:
    focus, next_items, watch = now_sections(HEADINGS)

    assert [item.text for item in focus] == ["Ship the release."]
    assert [item.text for item in next_items] == ["Tag it."]
    assert [item.text for item in watch] == ["CI time.", "Flaky e2e."]
    assert focus[0].last_verified is None


def test_gives_empty_sections_when_note_has_none() -> None:
    assert now_sections(b"# Now\n\nJust prose.\n") == ((), (), ())
