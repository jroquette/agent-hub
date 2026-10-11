from agent_hub.core.testing.read_model_builders import a_finding_view


def test_serializes_finding_in_doctor_json_shape_when_dumped() -> None:
    document = a_finding_view().model_dump(mode="json")

    assert document == {
        "project": "demo",
        "rule": "instructions.size",
        "severity": "warning",
        "path": "AGENTS.md",
        "line": 1,
        "message": "132 lines, limit 100",
        "fix": "Keep it a map, not a manual",
    }
