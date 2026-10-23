"""The incident pack's ``evidence.py`` (AGH-483), in process: the git evidence of each repo since
the window, bounded, with what it leaves out named; bad input exits 2. The repos come from
``hub step config``'s output (``--config``, AGH-480), never from a ``hub.json`` file.
"""

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/incident/scripts/evidence.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.incident.scripts.evidence"
REPORT = "Checkout fails since Tuesday."


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


def git(folder: Path, *args: str, when: datetime | None = None, stdin: bytes = b"") -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    if when is not None:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = when.isoformat()
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=folder,
        env=env,
        input=stdin,
        capture_output=True,
        check=True,
    )
    return done.stdout.decode().strip()


def commit(repo: Path, name: str, *, when: datetime | None = None) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-qm", f"add {name}", when=when)
    return git(repo, "rev-parse", "HEAD")


def a_repo(root: Path, name: str, *, origin: bool = True) -> Path:
    repo = root / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, "a.txt")
    if origin:
        git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


# Each hub's ``hub step config`` output, as the workflow passes it with ``--config``.
CONFIGS: dict[Path, str] = {}


def a_hub(root: Path, *dirs: str) -> Path:
    hub = root / "hub"
    hub.mkdir()
    repos = [{"dir": name, "default_branch": "main"} for name in dirs]
    CONFIGS[hub] = json.dumps({"default_branch": "main", "repos": repos})
    return hub


def run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hub: Path,
    *argv: str,
    report: str = REPORT,
) -> tuple[int, Any, str]:
    monkeypatch.chdir(hub)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(report.encode())))
    code = load().main([*argv, "--config", CONFIGS[hub]])
    captured = capsys.readouterr()
    return code, json.loads(captured.out) if code == 0 else captured.out, captured.err


def test_lists_merges_tags_and_changed_files_when_commits_are_in_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = a_repo(tmp_path, "api")
    git(repo, "checkout", "-qb", "feature")
    commit(repo, "b.txt")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge feature", "feature")
    plain = commit(repo, "c.txt")
    git(repo, "tag", "v1")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    hub = a_hub(tmp_path, "api")

    code, output, _ = run(monkeypatch, capsys, hub, "--since", "72h")

    assert code == 0
    (found,) = output["repos"]
    assert found["dir"] == "api"
    assert found["ref"] == "origin/main"
    assert found["head"] == plain
    subjects = [(c["subject"], c["merge"], c["paths"]) for c in found["commits"]]
    assert subjects == [
        ("add c.txt", False, ["c.txt"]),
        ("Merge feature", True, ["b.txt"]),
        ("add a.txt", False, ["a.txt"]),
    ]
    assert found["more_commits"] == 0
    assert [(tag["name"], tag["sha"]) for tag in found["tags"]] == [("v1", plain)]
    assert output["unreadable"] == []
    assert output["trimmed"] is False
    assert output["since"] == "72h"


def test_skips_commits_before_since_when_window_is_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    now = datetime.now(UTC)
    repo = tmp_path / "api"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, "old.txt", when=now - timedelta(days=5))
    commit(repo, "new.txt", when=now - timedelta(hours=1))
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    hub = a_hub(tmp_path, "api")

    code, output, _ = run(monkeypatch, capsys, hub, "--since", "24h")

    assert code == 0
    assert [c["subject"] for c in output["repos"][0]["commits"]] == ["add new.txt"]
    since = datetime.fromisoformat(output["since_iso"])
    assert timedelta(hours=23) < now - since < timedelta(hours=25)


def test_lists_unreadable_repo_when_origin_ref_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    a_repo(tmp_path, "unfetched", origin=False)
    a_repo(tmp_path, "api")
    (tmp_path / "plain").mkdir()
    hub = a_hub(tmp_path, "unfetched", "missing", "plain", "../escape", "api")

    code, output, _ = run(monkeypatch, capsys, hub, "--since", "3d")

    assert code == 0
    assert [repo["dir"] for repo in output["repos"]] == ["api"]
    unreadable = {item["repo"]: item["reason"] for item in output["unreadable"]}
    assert set(unreadable) == {"unfetched", "missing", "plain", "../escape"}
    assert "origin/main" in unreadable["unfetched"]
    assert "not a folder" in unreadable["missing"]
    assert "not a repo dir" in unreadable["../escape"]


def test_names_what_is_left_out_when_evidence_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    a_repo(tmp_path, "api")
    hub = a_hub(tmp_path, "api")

    code, output, _ = run(monkeypatch, capsys, hub, "--since", "72h")

    assert code == 0
    left_out = " ".join(output["left_out"])
    assert "failing checks on main" in left_out
    assert "logs (hub.json declares no log paths)" in left_out


def fast_import(repo: Path, commits: int, paths: int) -> None:
    """``commits`` commits on main, each changing the same ``paths`` long paths."""
    names = [f"{'d' * 150}/{'f' * 140}{n:03d}.txt" for n in range(paths)]
    stream = io.BytesIO()
    stamp = int(datetime.now(UTC).timestamp()) - 3600
    for number in range(commits):
        stream.write(
            f"commit refs/heads/main\ncommitter T <t@example.com> {stamp + number} +0000\n".encode()
        )
        message = f"change {number}"
        stream.write(f"data {len(message)}\n{message}\n".encode())
        for name in names:
            content = f"{number}\n"
            stream.write(f"M 100644 inline {name}\ndata {len(content)}\n{content}\n".encode())
    git(repo, "fast-import", "--quiet", stdin=stream.getvalue())


def test_stays_under_byte_cap_when_history_is_large(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "api"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    fast_import(repo, 150, 60)
    git(repo, "update-ref", "refs/remotes/origin/main", "refs/heads/main")
    hub = a_hub(tmp_path, "api")
    monkeypatch.chdir(hub)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(REPORT.encode())))

    code = load().main(["--since", "24h", "--config", CONFIGS[hub]])

    out = capsys.readouterr().out
    assert code == 0
    assert len(out.encode()) <= 49152
    output = json.loads(out)
    assert output["trimmed"] is True
    (found,) = output["repos"]
    assert found["more_commits"] >= 50
    assert all(len(c["paths"]) <= 50 for c in found["commits"])
    assert all(c["more_paths"] >= 10 for c in found["commits"])
    assert all(len(path) <= 300 for c in found["commits"] for path in c["paths"])
    # The newest commits are kept; the oldest go first.
    assert found["commits"][0]["subject"] == "change 149"


def test_stays_under_byte_cap_when_every_repo_has_many_long_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first = a_repo(tmp_path, "r00")
    for n in range(20):
        git(first, "tag", f"{'t' * 190}{n:02d}")
    for number in range(1, 20):
        shutil.copytree(first, tmp_path / f"r{number:02d}", symlinks=True)
    # Twenty more entries past the repo cap, each an unreadable entry with a long label.
    names = [f"r{n:02d}" for n in range(20)] + [f"{'x' * 300}{n}" for n in range(20)]
    hub = a_hub(tmp_path, *names)
    monkeypatch.chdir(hub)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(REPORT.encode())))

    code = load().main(["--since", "72h", "--config", CONFIGS[hub]])

    out = capsys.readouterr().out
    assert code == 0
    assert len(out.encode()) <= 49152
    output = json.loads(out)
    assert output["trimmed"] is True
    assert len(output["repos"]) == 20
    assert sum(len(repo["tags"]) for repo in output["repos"]) < 400


@pytest.mark.parametrize("since", ["0h", "72", "91d", "2161h", "3w", "1d ", "072h"])
def test_exits_two_when_since_is_malformed(
    since: str,
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hub = a_hub(tmp_path)

    code, out, err = run(monkeypatch, capsys, hub, "--since", since)

    assert code == 2
    assert out == ""
    assert "evidence.py: since must look like 72h or 3d" in err


def test_exits_two_when_report_exceeds_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path)
    monkeypatch.chdir(hub)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"x" * 32769)))

    code = load().main(["--since", "72h", "--config", CONFIGS[hub]])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "report is 32769 bytes, over 32768" in captured.err


def test_reads_the_report_when_it_is_at_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path)

    code, _, _ = run(monkeypatch, capsys, hub, "--since", "72h", report="\U0001f600" * 8192)

    assert code == 0


def test_exits_two_when_report_is_blank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path)

    code, out, err = run(monkeypatch, capsys, hub, "--since", "72h", report=" \n\t")

    assert code == 2
    assert out == ""
    assert "evidence.py: report is blank" in err


@pytest.mark.parametrize(
    "content",
    ["{not json", "[]", '{"repos": {}}', '{"repos": [1]}', "{" + " " * (1024 * 1024)],
    ids=["not-json", "not-object", "repos-not-list", "repo-not-object", "too-big"],
)
def test_exits_two_when_config_is_unreadable(
    content: str,
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hub = a_hub(tmp_path)
    monkeypatch.chdir(hub)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(REPORT.encode())))

    code = load().main(["--since", "72h", "--config", content])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "cannot read the config" in captured.err


def test_reads_no_hub_json_when_config_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    a_repo(tmp_path, "api")
    hub = a_hub(tmp_path)
    # A hub.json naming a repo the config does not: only the config is read.
    (hub / "hub.json").write_text(json.dumps({"repos": [{"dir": "api"}]}), encoding="utf-8")

    code, output, _ = run(monkeypatch, capsys, hub, "--since", "72h")

    assert code == 0
    assert output["repos"] == []
    assert output["unreadable"] == []


def test_reads_each_repo_default_branch_when_config_gives_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    a_repo(tmp_path, "api")
    hub = a_hub(tmp_path, "api")
    CONFIGS[hub] = json.dumps(
        {"default_branch": "main", "repos": [{"dir": "api", "default_branch": "trunk"}]}
    )

    code, output, _ = run(monkeypatch, capsys, hub, "--since", "72h")

    assert code == 0
    assert output["unreadable"] == [{"repo": "api", "reason": "no origin/trunk (fetch it first)"}]
