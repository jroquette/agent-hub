"""``hub digest --input``: the owner digest from the session's file and the local claims.

The hub is ``tmp_path``, the clock is fixed, and each test writes the input file itself. The
expected text comes from the core builder (``build_digest`` and ``digest_lines``), so these tests
check what the command reads, writes and refuses, not the digest's rules.
"""

import importlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
from agent_hub.core.claims.claim import Claim
from agent_hub.core.testing.workflow_fakes import FakeClock
from agent_hub.core.workspace.digest import Digest, DigestInput, build_digest, digest_lines

NOW = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
CACHE = ".hub-cache"
# The lines ``hub digest`` prints per section (D-4).
LIMIT = 10
MAX_INPUT_BYTES = 1024 * 1024


def _at(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def input_document() -> dict[str, Any]:
    """One item in each section: a waiting cloud session, an idle ticket and a ready PR."""
    return {
        "version": 1,
        "read_at": _at(0.1),
        "tickets": [
            {
                "id": "DEM-2",
                "title": "Sign-up page",
                "state": "In Progress",
                "url": "https://linear.example/DEM/issue/DEM-2",
                "claim": {
                    "session": "s-cloud",
                    "link": "https://claude.example/code/s-cloud",
                    "live": True,
                    "question": "Ship the new copy?",
                    "asked_at": _at(3),
                    "title": "DEM-2 sign-up",
                },
            },
            {
                "id": "DEM-3",
                "title": "Password reset",
                "state": "In Review",
                "url": "https://linear.example/DEM/issue/DEM-3",
                "claim": None,
            },
        ],
        "prs": [
            {
                "repo": "acme/web",
                "number": 7,
                "title": "Fix footer links",
                "url": "https://github.example/acme/web/pull/7",
                "branch": "fix/footer",
                "draft": False,
                "updated_at": _at(48),
                "mergeable_state": "clean",
                "checks": {"success": 4},
                "unresolved_threads": 0,
            }
        ],
    }


def local_claim(ticket: str, hub_root: Path, **changed: Any) -> Claim:
    fields: dict[str, Any] = {
        "ticket": ticket,
        "session": "s-local",
        "pid": 4242,
        "started": "Mon Nov 16 07:00:00 2026",
        "hub": str(hub_root),
        "claimed_at": NOW - timedelta(hours=5),
        "last_activity": NOW - timedelta(hours=1),
        **changed,
    }
    return Claim(**fields)


def digest_command() -> ModuleType:
    """The command's module, imported when a test runs (task 7 commits these tests red)."""
    return importlib.import_module("agent_hub.cli.digest_command")


@dataclass
class Hub:
    """A hub folder and ``hub digest`` run in this process against it, at ``NOW``."""

    root: Path
    monkeypatch: pytest.MonkeyPatch

    @property
    def claims(self) -> Path:
        return self.root / ".agent-runs" / "claims"

    @property
    def cache(self) -> Path:
        return self.root / CACHE / "digest.json"

    def write_input(self, document: object = None, *, name: str = "digest-input.json") -> Path:
        path = self.root.parent / name
        payload = input_document() if document is None else document
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def write_claim(self, claim: Claim) -> None:
        self.claims.mkdir(parents=True, exist_ok=True)
        (self.claims / f"{claim.ticket}.json").write_text(claim.model_dump_json())

    def run(self, *args: str) -> Result:
        module = digest_command()
        self.monkeypatch.setattr(module, "SystemClock", lambda: FakeClock(NOW))
        return CliRunner().invoke(app, ["digest", *args], env={"COLUMNS": "200"})


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Hub:
    root = Path(os.path.realpath(tmp_path / "hub"))
    root.mkdir()
    (root / "hub.json").write_text("{}\n")
    monkeypatch.setenv("AGENT_HUB_ROOT", str(root))
    monkeypatch.chdir(root)
    return Hub(root, monkeypatch)


def expected(claims: tuple[Claim, ...] = ()) -> Digest:
    return build_digest(DigestInput.model_validate(input_document()), claims, NOW)


def printed(digest: Digest) -> str:
    return "".join(f"{line}\n" for line in digest_lines(digest, limit=LIMIT))


def test_prints_digest_and_writes_cache_when_input_valid(hub: Hub) -> None:
    path = hub.write_input()

    result = hub.run("--input", str(path))

    assert result.exit_code == 0, result.output
    digest = expected()
    # Self-check: the input puts one item in each section.
    assert (len(digest.waiting), len(digest.idle), len(digest.ready)) == (1, 1, 1)
    assert result.stdout == printed(digest)
    assert stat.S_ISREG(hub.cache.lstat().st_mode)
    assert stat.S_IMODE(hub.cache.stat().st_mode) == 0o600
    assert Digest.model_validate_json(hub.cache.read_bytes()) == digest
    gitignore = (hub.root / CACHE / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert [line for line in gitignore if line.strip() and not line.startswith("#")] == ["*"]


def test_reads_local_claims_when_folder_has_them(hub: Hub) -> None:
    document = input_document()
    document["tickets"].append(
        {
            "id": "DEM-4",
            "title": "Login form",
            "state": "In Review",
            "url": "https://linear.example/DEM/issue/DEM-4",
            "claim": None,
        }
    )
    path = hub.write_input(document)
    # A local session waits on DEM-4, and a live local claim holds DEM-3 (idle in the input).
    waiting = local_claim(
        "DEM-4", hub.root, question="Merge #41?", asked_at=NOW - timedelta(hours=5), title=None
    )
    holding = local_claim("DEM-3", hub.root, session="s-other")
    hub.write_claim(waiting)
    hub.write_claim(holding)

    result = hub.run("--input", str(path))

    assert result.exit_code == 0, result.output
    digest = build_digest(DigestInput.model_validate(document), (waiting, holding), NOW)
    assert [item.ticket for item in digest.waiting] == ["DEM-4", "DEM-2"]
    assert digest.idle == ()
    assert result.stdout == printed(digest)
    assert Digest.model_validate_json(hub.cache.read_bytes()) == digest


def test_names_unreadable_claim_and_goes_on_when_claim_corrupt(hub: Hub) -> None:
    path = hub.write_input()
    waiting = local_claim(
        "DEM-4", hub.root, question="Merge #41?", asked_at=NOW - timedelta(hours=5)
    )
    hub.write_claim(waiting)
    (hub.claims / "DEM-9.json").write_text("{not a claim")

    result = hub.run("--input", str(path))

    assert result.exit_code == 0, result.output
    assert "DEM-9.json" in result.stderr
    assert result.stdout == printed(expected((waiting,)))


def _missing(hub: Hub) -> Path:
    return hub.root.parent / "absent.json"


def _link(hub: Hub) -> Path:
    target = hub.write_input(name="real-input.json")
    link = hub.root.parent / "linked-input.json"
    link.symlink_to(target)
    return link


def _folder(hub: Hub) -> Path:
    folder = hub.root.parent / "input-folder"
    folder.mkdir()
    return folder


def _too_big(hub: Hub) -> Path:
    path = hub.root.parent / "big-input.json"
    raw = json.dumps(input_document()).encode()
    path.write_bytes(raw + b" " * (MAX_INPUT_BYTES + 1 - len(raw)))
    return path


def _not_json(hub: Hub) -> Path:
    path = hub.root.parent / "broken-input.json"
    path.write_text("{not json", encoding="utf-8")
    return path


def _bad_shape(hub: Hub) -> Path:
    return hub.write_input({**input_document(), "version": 2}, name="v2-input.json")


@pytest.mark.parametrize(
    "make_input",
    [_missing, _link, _folder, _too_big, _not_json, _bad_shape],
    ids=["missing", "link", "folder", "too_big", "not_json", "bad_shape"],
)
def test_refuses_input_when_unreadable(hub: Hub, make_input: Any) -> None:
    path = make_input(hub)

    result = hub.run("--input", str(path))

    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    errors = result.stderr.splitlines()
    assert len(errors) == 1, result.stderr
    assert errors[0].startswith(f"hub digest: cannot read {path}: "), errors
    assert not (hub.root / CACHE).exists()


def test_refuses_cache_folder_when_it_is_a_link(hub: Hub) -> None:
    path = hub.write_input()
    target = hub.root.parent / "planted"
    target.mkdir()
    (hub.root / CACHE).symlink_to(target)

    result = hub.run("--input", str(path))

    assert list(target.iterdir()) == []
    assert (hub.root / CACHE).is_symlink()
    assert result.exit_code == 1, result.output
    assert CACHE in result.stderr


def test_makes_no_network_call_when_digest_built(
    hub: Hub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = hub.write_input()
    tools = tmp_path / "bin"
    tools.mkdir()
    ran = tmp_path / "gh-ran"
    gh = tools / "gh"
    gh.write_text(f'#!/bin/sh\ntouch "{ran}"\nexit 1\n')
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tools}{os.pathsep}{os.environ['PATH']}")

    result = hub.run("--input", str(path))

    assert result.exit_code == 0, result.output
    assert not ran.exists()
    assert result.stdout == printed(expected())
