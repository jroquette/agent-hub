"""The live transcript tail through ``POST /events/hooks`` on the composed app (AC-200.12, E6)."""

import os
from pathlib import Path
from typing import Any

from agent_hub.core.testing.hook_inputs import a_hook_input, an_envelope
from agent_hub.core.testing.transcript_lines import (
    TRANSCRIPT_SESSION,
    a_text_block,
    a_user_line,
    an_assistant_line,
    transcript_text,
)

HOOKS = "/api/v1/events/hooks"


def _post(composed: Any, hook: dict[str, Any], **overrides: Any) -> Any:
    envelope = an_envelope(hook, **overrides).model_dump(mode="json")
    return composed.client.post(HOOKS, json=envelope)


def _status(composed: Any) -> dict[str, Any]:
    response = composed.client.get("/api/v1/collector/status")
    assert response.status_code == 200, response.text
    document: dict[str, Any] = response.json()
    return document


def _transcript(composed: Any, name: str = f"{TRANSCRIPT_SESSION}.jsonl") -> Path:
    path: Path = composed.projects / "-work-demo-api" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(transcript_text([a_user_line("one")]), encoding="utf-8")
    return path


def test_ingests_new_transcript_records_when_stop_names_file_under_projects(
    composed: Any,
) -> None:
    path = _transcript(composed)

    first = _post(composed, a_hook_input("Stop", transcript_path=str(path)))
    with path.open("a", encoding="utf-8") as file:
        file.write(transcript_text([a_user_line("two"), an_assistant_line([a_text_block()])]))
    second = _post(
        composed,
        a_hook_input("Stop", transcript_path=str(path)),
        sent_at="2026-10-11T10:05:00Z",
    )

    assert (first.status_code, first.json()) == (202, {"appended": 1, "duplicates": 0})
    assert second.status_code == 202
    assert second.json()["appended"] == 2
    rows = composed.rows()
    assert {row.source for row in rows} == {"transcript"}
    assert {(row.project, row.repo, row.agent) for row in rows} == {("demo", "demo-api", "main")}
    assert [row.payload["turn"] for row in rows] == [1, 2, 2]
    assert _status(composed)["transcript_refused"] == 0


def test_counts_refusal_and_reads_nothing_when_path_outside_projects_folder(
    composed: Any, tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere" / "s.jsonl"
    outside.parent.mkdir()
    outside.write_text(transcript_text([a_user_line()]), encoding="utf-8")

    response = _post(composed, a_hook_input("Stop", transcript_path=str(outside)))

    assert (response.status_code, response.json()) == (202, {"appended": 0, "duplicates": 0})
    assert composed.rows() == []
    assert _status(composed)["transcript_refused"] == 1


def test_counts_refusal_and_reads_nothing_when_path_is_symlink(
    composed: Any, tmp_path: Path
) -> None:
    target = _transcript(composed, "real.jsonl")
    link = composed.projects / "-work-demo-api" / "link.jsonl"
    os.symlink(target, link)

    response = _post(composed, a_hook_input("Stop", transcript_path=str(link)))

    assert response.json() == {"appended": 0, "duplicates": 0}
    assert composed.rows() == []
    assert _status(composed)["transcript_refused"] == 1


def test_reads_subagent_transcript_as_its_agent_when_subagent_stop_names_it(
    composed: Any,
) -> None:
    main = _transcript(composed)
    subagent = _transcript(composed, f"{TRANSCRIPT_SESSION}/subagents/agent-agent-7.jsonl")
    hook = a_hook_input(
        "SubagentStop", transcript_path=str(main), agent_transcript_path=str(subagent)
    )

    response = _post(composed, hook)

    assert response.json() == {"appended": 1, "duplicates": 0}
    [row] = composed.rows()
    assert (row.source, row.agent, row.session) == ("transcript", "Explore", TRANSCRIPT_SESSION)
