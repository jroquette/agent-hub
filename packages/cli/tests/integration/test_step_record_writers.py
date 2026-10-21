"""``hub step ticket-brief|preflight|change-request|decide|amend-plan`` (two-level-flows AC-2.2,
AC-2.3, AC-2.7, AC-2.12, P7): the ticket records an ``implement`` run writes into the hub.

Each runs in process in a copy of the ``DEMO`` workspace whose hub is a git repo holding one
feature folder; the repo checkouts are real clones. Every case checks that nothing was committed
and no repo checkout changed; a refusal exits 1 with one ``hub step <name>: <reason>`` line and
writes nothing.
"""

import fcntl
import hashlib
import json
import os
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli import step_records
from agent_hub.cli.main import app

pytestmark = pytest.mark.disable_socket

type CommandRunner = Callable[..., Result]
type Workspace = Any

FEATURE = "brain/features/demo-flow"
TICKET = ("--feature", "demo-flow", "--ticket", "DEM-8")
FEATURES_JSON = {
    "tickets": [
        {"key": "T1", "id": "DEM-7", "repo": "demo-api", "blocked_by": []},
        {"key": "T2", "id": "DEM-8", "repo": "demo-api", "blocked_by": ["T1", "T3"]},
        {"key": "T3", "repo": "demo-api", "blocked_by": []},
        {"key": "P1-T1-T2", "id": "DEM-9", "repo": "demo-api", "blocked_by": []},
    ],
    "acs": [
        {"id": "AC-1.1", "description": "It writes the brief.", "passes": False, "ticket": "T2"},
        {
            "id": "AC-1.2",
            "description": "A withdrawn one.",
            "passes": False,
            "ticket": "DEM-8",
            "withdrawn": True,
        },
        {"id": "AC-1.3", "description": "Another ticket's.", "passes": False, "ticket": "T1"},
    ],
}
PLAN = """# Plan

### T2 api: the handler

Change `src/api/handler.py:3`, per ADR 0040.

### T3 other

Touch `src/other.py`.

## Joined tickets

| Ticket | Boundary | ACs |
|---|---|---|
| P1-T1 | `src/api/handler.py` | AC-1.3 |
| P1-T3 | other | AC-1.1 |

## Amendments

- A1 (2026-01-01, Dana Owner): First.
"""
OUTCOME = "---\nmerged_at: 2026-01-20T10:00:00Z\npr: '#4'\n---\n# Outcome\n"
LOCK = ".agent-runs/locks/demo-flow.lock"
HELD = "are being written by another run; run again"
RUN = {
    "ran_at": "2026-02-02T09:30:00Z",
    "plan_version": 2,
    "commit": "4e1a9c2",
    "blockers_read": ["DEM-7"],
    "input": "none",
    "input_text": None,
    "drift": "none",
    "local_notes": [],
    "change_request": None,
    "run_id": "implement-8",
}


class Hub:
    """The workspace's hub with the ``demo-flow`` feature, and the repos' state to compare."""

    def __init__(self, workspace: Workspace, run_command: CommandRunner) -> None:
        self.workspace = workspace
        self.root: Path = workspace.hub
        self.feature = self.root / FEATURE
        self._run = run_command
        files = {
            "features.json": json.dumps(FEATURES_JSON),
            "plan.md": PLAN,
            "tickets/DEM-7/outcome.md": OUTCOME,
        }
        for name, text in files.items():
            (self.feature / name).parent.mkdir(parents=True, exist_ok=True)
            (self.feature / name).write_text(text)
        self.handler_before = self.dated("2025-12-01T00:00:00Z", self.handler, b"v1\n")
        with self.dated_env("2026-01-01T00:00:00Z"):
            workspace.init_hub_repo(None)
        self.handler_after = self.dated("2026-02-01T00:00:00Z", self.handler, b"v2\n")
        self.unnamed = self.dated("2026-02-01T00:00:00Z", self.unnamed_file, b"x\n")
        workspace.git(workspace.ws / "demo-api", "fetch", "-q", "origin")
        self.before = self.state()

    @staticmethod
    def handler(workspace: Workspace, content: bytes) -> str:
        return str(workspace.advance("demo-api", {"src/api/handler.py": (content, 0o644)}))

    @staticmethod
    def unnamed_file(workspace: Workspace, content: bytes) -> str:
        return str(workspace.advance("demo-api", {"src/unnamed.py": (content, 0o644)}))

    def dated(self, date: str, push: Callable[[Workspace, bytes], str], content: bytes) -> str:
        with self.dated_env(date):
            return push(self.workspace, content)

    @property
    def dated_env(self) -> Callable[[str], Any]:
        env = self.workspace.env

        class Dated:
            def __init__(self, date: str) -> None:
                self.date = date

            def __enter__(self) -> None:
                env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = self.date

            def __exit__(self, *_: object) -> None:
                env.pop("GIT_AUTHOR_DATE")
                env.pop("GIT_COMMITTER_DATE")

        return Dated

    def state(self) -> dict[str, tuple[str, str, str]]:
        """Each checkout's HEAD, ``git status`` and refs; the hub's status lists only brain."""
        found = {}
        for name in ("hub", "demo-api", "demo-web"):
            folder = self.workspace.ws / name
            status = self.workspace.git(folder, "status", "--porcelain", "--untracked-files=all")
            if name == "hub":
                # Only the feature folder may change (git's output comes stripped).
                status = "\n".join(
                    line
                    for line in status.splitlines()
                    if not line.split(maxsplit=1)[-1].startswith(FEATURE)
                )
            refs = self.workspace.git(folder, "for-each-ref")
            found[name] = (self.workspace.git(folder, "rev-parse", "HEAD"), status, refs)
        return found

    def step(self, *args: str) -> Result:
        return self._run(self.root, "step", *args)

    def ok(self, *args: str) -> dict[str, Any]:
        result = self.step(*args)
        assert result.exit_code == 0, result.output
        value = json.loads(result.stdout)
        assert isinstance(value, dict)
        return value

    def refused(self, name: str, *args: str) -> str:
        """The one stderr line of a refused step; nothing under the feature changed."""
        before = self.tree()
        result = self.step(name, *args)
        assert result.exit_code == 1, result.output
        assert result.stdout == ""
        [line] = result.stderr.splitlines()
        assert line.startswith(f"hub step {name}: ")
        assert self.tree() == before
        return line

    def tree(self) -> dict[str, bytes]:
        return {
            path.relative_to(self.feature).as_posix(): path.read_bytes()
            for path in sorted(self.feature.rglob("*"))
            if path.is_file()
        }

    def request(self, *extra: str) -> dict[str, Any]:
        return self.ok(
            "change-request",
            *TICKET,
            *("--run-id", "implement-8", "--evidence", "The API moved."),
            *("--proposal", "Follow it.", "--affected", "T3"),
            *extra,
        )

    def link(self, name: str, tmp_path: Path) -> Path:
        """``<feature>/<name>`` made a link to an empty folder outside the hub."""
        target = tmp_path / "outside"
        target.mkdir()
        (self.feature / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(self.feature / name, ignore_errors=True)
        (self.feature / name).symlink_to(target)
        return target

    def approved(self) -> None:
        self.request()
        assert self.decide("--decision", "approved", "--by", "Dana").exit_code == 0

    def amend(self, *extra: str) -> dict[str, Any]:
        return self.ok(
            "amend-plan", "--feature", "demo-flow", "--request", "1", *extra, "--summary", "Go."
        )

    def lock_held_while(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """Each file ``_replace`` writes, after checking the feature's lock is held then."""
        written: list[str] = []
        replace = step_records._replace

        def checked(folder: Path, name: str, content: bytes) -> None:
            descriptor = os.open(self.root / LOCK, os.O_RDWR)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(descriptor)
            written.append(name)
            replace(folder, name, content)

        monkeypatch.setattr(step_records, "_replace", checked)
        return written

    def decide(self, *extra: str) -> Result:
        return self.step("decide", "--feature", "demo-flow", "--request", "1", *extra)


@pytest.fixture
def hub(demo_workspace: Workspace, run_command: CommandRunner) -> Iterator[Hub]:
    made = Hub(demo_workspace, run_command)
    yield made
    assert made.state() == made.before, "a checkout changed or something was committed"


class TestTicketBrief:
    def test_writes_the_brief_from_the_records_and_main_when_the_ticket_is_planned(
        self, hub: Hub
    ) -> None:
        output = hub.ok("ticket-brief", *TICKET)

        assert output == {"path": f"{FEATURE}/tickets/DEM-8/brief.md", "version": 1}
        text = (hub.root / output["path"]).read_text()
        fields = json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])
        assert fields == {
            "plan_version": 2,
            "blockers": [
                {
                    "id": "DEM-7",
                    "outcome_path": "tickets/DEM-7/outcome.md",
                    "recorded_at": "2026-01-20T10:00:00Z",
                },
                {"id": "T3", "outcome_path": None, "recorded_at": None},
            ],
            "adrs": ["ADR 0040"],
        }
        assert "**AC-1.1** It writes the brief." in text
        assert "AC-1.2" not in text and "AC-1.3" not in text
        assert "> ### T2 api: the handler" in text and "T3 other" not in text
        assert "- T3: none recorded" in text
        assert f"`{hub.handler_after[:12]}` 2026-02-01 advance" in text
        assert hub.handler_before[:12] not in text and hub.unnamed[:12] not in text

    def test_appends_a_second_version_keeping_the_first_when_run_again(self, hub: Hub) -> None:
        path = hub.root / hub.ok("ticket-brief", *TICKET)["path"]
        first = path.read_bytes()

        output = hub.ok("ticket-brief", *TICKET)

        assert output["version"] == 2
        assert path.read_bytes().startswith(first)
        assert b"## Brief v2 (" in path.read_bytes()[len(first) :]

    def test_keeps_every_earlier_byte_when_the_brief_ends_in_blank_lines(self, hub: Hub) -> None:
        path = hub.root / hub.ok("ticket-brief", *TICKET)["path"]
        with path.open("ab") as file:
            file.write(b"\n \n\n")
        first = path.read_bytes()

        hub.ok("ticket-brief", *TICKET)

        assert path.read_bytes().startswith(first)

    def test_takes_the_plan_rows_and_their_acs_when_the_key_joins_plan_ids(self, hub: Hub) -> None:
        output = hub.ok("ticket-brief", "--feature", "demo-flow", "--ticket", "DEM-9")

        text = (hub.root / output["path"]).read_text()
        assert output["path"] == f"{FEATURE}/tickets/DEM-9/brief.md"
        assert "> | P1-T1 | `src/api/handler.py` | AC-1.3 |" in text
        assert "P1-T3" not in text
        assert "**AC-1.3** Another ticket's." in text and "AC-1.1" not in text
        assert f"`{hub.handler_after[:12]}`" in text

    @pytest.mark.parametrize("step", ["ticket-brief", "preflight", "change-request"])
    def test_refuses_a_ticket_when_the_feature_does_not_plan_it(self, hub: Hub, step: str) -> None:
        extra = {
            "ticket-brief": (),
            "preflight": ("--run", json.dumps(RUN)),
            "change-request": ("--run-id", "r1", "--evidence", "e", "--proposal", "p"),
        }[step]

        line = hub.refused(step, "--feature", "demo-flow", "--ticket", "DEM-99", *extra)

        assert line == f"hub step {step}: DEM-99 is not a ticket of features.json"

    @pytest.mark.parametrize("given", ["dem-8", "T2", "t2"])
    def test_writes_into_the_one_folder_of_the_ticket_when_named_by_key_or_case(
        self, hub: Hub, given: str
    ) -> None:
        hub.ok("ticket-brief", *TICKET)

        output = hub.ok(
            "preflight", "--feature", "demo-flow", "--ticket", given, "--run", json.dumps(RUN)
        )

        assert output["path"] == f"{FEATURE}/tickets/DEM-8/preflight.json"
        assert sorted(p.name for p in (hub.feature / "tickets").iterdir()) == ["DEM-7", "DEM-8"]

    def test_writes_into_the_existing_folder_when_its_name_differs_in_case(self, hub: Hub) -> None:
        (hub.feature / "tickets/t2").mkdir()

        output = hub.ok("ticket-brief", *TICKET)

        assert output["path"] == f"{FEATURE}/tickets/t2/brief.md"

    def test_writes_the_brief_under_the_feature_lock_when_run(
        self, hub: Hub, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        written = hub.lock_held_while(monkeypatch)

        hub.ok("ticket-brief", *TICKET)

        assert written == ["brief.md"]


class TestPreflight:
    def test_appends_each_run_keeping_earlier_entries_and_validates_when_run_twice(
        self, hub: Hub
    ) -> None:
        first = hub.ok("preflight", *TICKET, "--run", json.dumps(RUN))
        path = hub.root / first["path"]
        before = json.loads(path.read_bytes())["runs"]

        second = hub.ok(
            "preflight",
            *TICKET,
            "--run",
            json.dumps(RUN | {"drift": "local", "local_notes": ["x"]}),
        )

        assert (first["runs"], second["runs"]) == (1, 2)
        runs = json.loads(path.read_bytes())["runs"]
        assert [json.dumps(r, sort_keys=True) for r in runs[:1]] == [
            json.dumps(r, sort_keys=True) for r in before
        ]
        checked = CliRunner().invoke(app, ["validate-output", "preflight", str(path)])
        assert checked.exit_code == 0, checked.output

    def test_keeps_the_record_when_the_model_refuses_the_run(self, hub: Hub) -> None:
        hub.ok("preflight", *TICKET, "--run", json.dumps(RUN))

        line = hub.refused("preflight", *TICKET, "--run", json.dumps(RUN | {"drift": "plan"}))

        assert "change_request is required when drift is plan" in line

    def test_refuses_without_writing_when_the_record_is_a_link(
        self, hub: Hub, tmp_path: Path
    ) -> None:
        elsewhere = tmp_path / "elsewhere.json"
        elsewhere.write_text("{}")
        (hub.feature / "tickets/DEM-8").mkdir(parents=True)
        (hub.feature / "tickets/DEM-8/preflight.json").symlink_to(elsewhere)

        line = hub.refused("preflight", *TICKET, "--run", json.dumps(RUN))

        assert line == "hub step preflight: preflight.json is a link; no link is followed"
        assert elsewhere.read_text() == "{}"

    @pytest.mark.parametrize("name", ["tickets", "tickets/DEM-8"])
    def test_refuses_without_writing_when_a_ticket_folder_is_a_link(
        self, hub: Hub, tmp_path: Path, name: str
    ) -> None:
        target = hub.link(name, tmp_path)

        for step, extra in (("preflight", ("--run", json.dumps(RUN))), ("ticket-brief", ())):
            line = hub.refused(step, *TICKET, *extra)
            leaf = name.rsplit("/", 1)[-1]
            assert line == f"hub step {step}: {leaf} is a link; no link is followed"
        assert list(target.iterdir()) == []

    def test_refuses_a_record_when_it_is_one_byte_over_its_read_cap(self, hub: Hub) -> None:
        folder = hub.feature / "tickets/DEM-8"
        folder.mkdir(parents=True)
        (folder / "preflight.json").write_bytes(b" " * 65_537)

        line = hub.refused("preflight", *TICKET, "--run", json.dumps(RUN))

        assert line == "hub step preflight: preflight.json is larger than 65536 bytes"

    def test_replaces_the_record_with_a_new_file_when_a_run_is_appended(
        self, hub: Hub, tmp_path: Path
    ) -> None:
        path = hub.root / hub.ok("preflight", *TICKET, "--run", json.dumps(RUN))["path"]
        before = path.read_bytes()
        os.link(path, tmp_path / "old.json")

        hub.ok("preflight", *TICKET, "--run", json.dumps(RUN))

        assert (tmp_path / "old.json").read_bytes() == before
        assert path.read_bytes() != before

    def test_writes_under_the_feature_lock_and_refuses_when_another_run_holds_it(
        self, hub: Hub, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with monkeypatch.context() as patched:
            written = hub.lock_held_while(patched)
            hub.ok("preflight", *TICKET, "--run", json.dumps(RUN))
        descriptor = os.open(hub.root / LOCK, os.O_RDWR)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            line = hub.refused("preflight", *TICKET, "--run", json.dumps(RUN))
        finally:
            os.close(descriptor)

        assert written == ["preflight.json"]
        assert line == f"hub step preflight: the records of demo-flow {HELD}"

    def test_refuses_without_writing_when_the_feature_folder_is_a_link(
        self, hub: Hub, tmp_path: Path
    ) -> None:
        (hub.root / "brain/features/linked").symlink_to(hub.feature)

        result = hub.step("preflight", "--feature", "linked", "--ticket", "DEM-8", "--run", "{}")

        (hub.root / "brain/features/linked").unlink()
        assert result.exit_code == 1
        assert result.stderr == "hub step preflight: no feature folder brain/features/linked\n"


class TestChangeRequest:
    def test_opens_the_next_numbered_request_against_the_plan_version_when_asked(
        self, hub: Hub
    ) -> None:
        first, second = hub.request(), hub.request()

        assert first == {
            "path": f"{FEATURE}/change-requests/1.md",
            "n": 1,
            "plan_from": 2,
            "plan_to": 3,
        }
        assert second["n"] == 2
        text = (hub.root / first["path"]).read_text()
        assert "ticket: DEM-8\nstatus: open\nplan_from: 2\nplan_to: 3\naffected: [T3]\n" in text

    def test_takes_the_next_number_keeping_the_request_when_the_one_picked_is_taken(
        self, hub: Hub, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first = hub.feature / "change-requests/1.md"
        hub.request()
        before = first.read_bytes()
        monkeypatch.setattr(step_records, "next_request", lambda names: 1)

        output = hub.request("--run-id", "implement-9")

        assert (output["n"], output["path"]) == (2, f"{FEATURE}/change-requests/2.md")
        assert first.read_bytes() == before
        assert b"run_id: implement-9" in (hub.feature / "change-requests/2.md").read_bytes()

    def test_refuses_without_writing_when_the_requests_folder_is_a_link(
        self, hub: Hub, tmp_path: Path
    ) -> None:
        target = hub.link("change-requests", tmp_path)

        line = hub.refused(
            "change-request",
            *TICKET,
            *("--run-id", "r1", "--evidence", "e", "--proposal", "p"),
        )
        decided = hub.refused(
            "decide",
            "--feature",
            "demo-flow",
            "--request",
            "1",
            "--decision",
            "approved",
            "--by",
            "Dana",
        )

        assert line == "hub step change-request: change-requests is a link; no link is followed"
        assert decided == "hub step decide: change-requests is a link; no link is followed"
        assert list(target.iterdir()) == []


class TestDecideAndAmend:
    def test_records_the_approval_then_one_amendment_keeping_the_plan_when_approved(
        self, hub: Hub
    ) -> None:
        hub.request()
        plan = hub.feature / "plan.md"
        prefix = hashlib.sha256(plan.read_bytes()).hexdigest()
        size = plan.stat().st_size

        decided = hub.decide("--decision", "approved", "--by", "Dana Owner")
        amended = hub.ok(
            "amend-plan", "--feature", "demo-flow", "--request", "1", "--summary", "Follow the API."
        )

        assert decided.exit_code == 0, decided.output
        assert json.loads(decided.stdout) == {
            "path": f"{FEATURE}/change-requests/1.decision.md",
            "decision": "approved",
        }
        decision = (hub.feature / "change-requests/1.decision.md").read_text()
        assert "decision: approved\ndecided_by: Dana Owner\n" in decision
        assert amended == {"path": f"{FEATURE}/plan.md", "amendment": "A2", "already": None}
        written = plan.read_bytes()
        assert hashlib.sha256(written[:size]).hexdigest() == prefix
        assert written[size:].decode().startswith("- A2 (")
        assert written[size:].decode().count("\n") == 1
        again = hub.ok(
            "amend-plan", "--feature", "demo-flow", "--request", "1", "--summary", "Again."
        )
        assert again == {
            "path": f"{FEATURE}/plan.md",
            "amendment": "A2",
            "already": "already amended as A2",
        }
        assert plan.read_bytes() == written

    def test_keeps_every_earlier_byte_when_the_plan_ends_in_blank_lines(
        self, hub: Hub, tmp_path: Path
    ) -> None:
        plan = hub.feature / "plan.md"
        with plan.open("ab") as file:
            file.write(b"\n \n\n")
        before = plan.read_bytes()
        os.link(plan, tmp_path / "old.md")
        hub.approved()

        hub.amend()

        assert plan.read_bytes().startswith(before)
        assert (tmp_path / "old.md").read_bytes() == before

    def test_amends_the_plan_under_the_feature_lock_when_approved(
        self, hub: Hub, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hub.approved()
        written = hub.lock_held_while(monkeypatch)

        hub.amend()

        assert written == ["plan.md"]

    def test_keeps_the_first_decision_when_a_second_is_asked(self, hub: Hub) -> None:
        hub.request()
        assert hub.decide("--decision", "declined", "--by", "Dana", "--note", "No.").exit_code == 0

        line = hub.refused(
            "decide",
            "--feature",
            "demo-flow",
            "--request",
            "1",
            "--decision",
            "approved",
            "--by",
            "Dana",
        )

        assert line == "hub step decide: change request 1 is already decided"

    @pytest.mark.parametrize(
        ("args", "reason"),
        [
            (("--decision", "approved", "--by", "unknown"), "names no person"),
            (("--decision", "approved", "--by", " "), "decided_by is missing"),
            (("--decision", "approved", "--by", "Dana (owner)"), "could not be written"),
            (("--decision", "declined", "--by", "Dana"), "a declined change needs a note"),
            (("--decision", "approved", "--by", "Dana", "--request", "2"), "no 2.md"),
        ],
    )
    def test_refuses_without_writing_when_a_person_note_or_request_is_missing(
        self, hub: Hub, args: tuple[str, ...], reason: str
    ) -> None:
        hub.request()

        line = hub.refused("decide", "--feature", "demo-flow", "--request", "1", *args)

        assert reason in line

    def test_refuses_without_writing_when_another_run_holds_the_plan_lock(self, hub: Hub) -> None:
        hub.approved()
        locks = hub.root / ".agent-runs/locks"
        locks.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(hub.root / LOCK, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            line = hub.refused(
                "amend-plan", "--feature", "demo-flow", "--request", "1", "--summary", "Go."
            )
        finally:
            os.close(descriptor)

        assert line == f"hub step amend-plan: the records of demo-flow {HELD}"
        hub.amend()

    def test_refuses_an_amendment_when_the_request_is_not_decided(self, hub: Hub) -> None:
        hub.request()

        line = hub.refused(
            "amend-plan", "--feature", "demo-flow", "--request", "1", "--summary", "Go."
        )

        assert line == "hub step amend-plan: no 1.decision.md in the feature folder"
