from agent_hub.core.agent_sessions.authorship import path_matches, wrote

SPEC = "brain/features/real-cost/spec.md"
ABSOLUTE = f"/work/agent-hub-hub/{SPEC}"


def test_wrote_is_true_for_a_write_or_edit_of_the_path() -> None:
    for name in ("Write", "Edit", "MultiEdit"):
        assert wrote({"name": name, "input": {"file_path": ABSOLUTE}}, SPEC)
    assert wrote({"name": "NotebookEdit", "input": {"notebook_path": ABSOLUTE}}, SPEC)


def test_wrote_is_false_for_a_read_another_file_or_a_malformed_body() -> None:
    assert not wrote({"name": "Read", "input": {"file_path": ABSOLUTE}}, SPEC)
    assert not wrote({"name": "Write", "input": {"file_path": "/w/plan.md"}}, SPEC)
    assert not wrote({"name": "Write", "input": "not a dict"}, SPEC)
    assert not wrote({"input": {"file_path": ABSOLUTE}}, SPEC)


def test_path_matches_whole_segments_only() -> None:
    assert path_matches(ABSOLUTE, SPEC)
    assert path_matches(ABSOLUTE, ABSOLUTE)
    assert not path_matches("/w/xbrain/features/real-cost/spec.md", SPEC)
