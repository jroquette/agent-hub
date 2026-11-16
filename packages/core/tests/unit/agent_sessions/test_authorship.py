from agent_hub.core.agent_sessions.authorship import path_matches, wrote

SPEC = "brain/features/real-cost/spec.md"
ABSOLUTE = f"/work/agent-hub-hub/{SPEC}"


def test_reports_wrote_when_path_written_or_edited() -> None:
    for name in ("Write", "Edit", "MultiEdit"):
        assert wrote({"name": name, "input": {"file_path": ABSOLUTE}}, SPEC)
    assert wrote({"name": "NotebookEdit", "input": {"notebook_path": ABSOLUTE}}, SPEC)


def test_reports_not_wrote_when_read_other_file_or_malformed() -> None:
    assert not wrote({"name": "Read", "input": {"file_path": ABSOLUTE}}, SPEC)
    assert not wrote({"name": "Write", "input": {"file_path": "/w/plan.md"}}, SPEC)
    assert not wrote({"name": "Write", "input": "not a dict"}, SPEC)
    assert not wrote({"input": {"file_path": ABSOLUTE}}, SPEC)


def test_matches_path_when_whole_segments_match() -> None:
    assert path_matches(ABSOLUTE, SPEC)
    assert path_matches(ABSOLUTE, ABSOLUTE)
    assert not path_matches("/w/xbrain/features/real-cost/spec.md", SPEC)
