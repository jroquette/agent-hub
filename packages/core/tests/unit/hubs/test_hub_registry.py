from agent_hub.core.brain.brain_note import BrainEntry
from agent_hub.core.hubs.hub_registry import BrainListing, UnreadHubFile


def test_keeps_kind_unset_when_unread_file_built_by_older_reader() -> None:
    unread = UnreadHubFile(message="cannot read: denied", is_missing=False)

    assert unread.kind is None


def test_names_kind_when_brain_file_too_large() -> None:
    unread = UnreadHubFile(message="too large", is_missing=False, kind="too_large")

    assert unread.kind == "too_large"


def test_defaults_listing_when_brain_complete() -> None:
    listing = BrainListing(entries=(BrainEntry(path="index.md", size=1),))

    assert (listing.truncated, listing.skipped) == (False, 0)
