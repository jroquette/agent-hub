"""The release pack's ``pin.py`` (AGH-494), in process: the sync list, then the hub's pin commit.

A fake ``hub`` (a Python file run by ``--cli``) stands in for the CLI: it records where it ran
and what pin it saw, and prints what ``hub sync`` would.
"""

import importlib.util
import json
import shlex
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/release/scripts/pin.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.release.scripts.pin"


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


HUB_JSON = """{
  "_comment": "Hub configuration; keep this layout.",
  "schema_version": 1,
  "platform": {
    "version": "0.20.1"
  },
  "project": {
    "name": "demo",
    "hub_repo": "acme/demo-hub",
    "branch_prefix": "jdoe/",
    "default_branch": "trunk"
  },
  "repos": [{"dir": "platform", "version": "9.9.9"}]
}
"""


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def a_hub(tmp_path: Path, hub_json: str = HUB_JSON) -> Path:
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / "hub.json").write_text(hub_json)
    (hub / "Makefile").write_text("old\n")
    (hub / ".gitignore").write_text(".claude/worktrees/\n")
    git(hub, "init", "-q", "-b", "trunk")
    git(hub, "config", "user.name", "T")
    git(hub, "config", "user.email", "t@example.com")
    git(hub, "add", ".")
    git(hub, "commit", "-qm", "base")
    git(hub, "update-ref", "refs/remotes/origin/trunk", "HEAD")
    return hub


def a_fake_hub(tmp_path: Path, *, check: str, check_exit: int, sync: str = "") -> str:
    """A fake CLI: records each run's cwd and pin in ``seen.jsonl``; ``sync`` rewrites Makefile."""
    seen = tmp_path / "seen.jsonl"
    fake = tmp_path / "fake_hub.py"
    fake.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "pin = json.loads(Path('hub.json').read_text())['platform']['version']\n"
        f"with open({str(seen)!r}, 'a') as seen:\n"
        "    seen.write(json.dumps({'cwd': str(Path.cwd()), 'pin': pin, 'argv': sys.argv[1:]}))\n"
        "    seen.write('\\n')\n"
        "if sys.argv[1:] == ['sync', '--check']:\n"
        f"    print({check!r})\n"
        f"    sys.exit({check_exit})\n"
        "Path('Makefile').write_text('new\\n')\n"
        f"print({sync!r})\n"
    )
    return shlex.join([sys.executable, str(fake)])


def seen(tmp_path: Path) -> list[dict[str, Any]]:
    lines = (tmp_path / "seen.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


# What hub step config prints for the hub, as the workflow passes it with --config (AGH-480).
CONFIG = json.dumps(
    {"default_branch": "trunk", "hub": {"github": "acme/demo-hub", "default_branch": "trunk"}}
)


def list_pin(hub: Path, monkeypatch: pytest.MonkeyPatch, *, cli: str, config: str = CONFIG) -> int:
    monkeypatch.chdir(hub)
    argv = ["list", "--repo", str(hub.parent), "--version", "0.21.0", "--cli", cli]
    code: int = load().main([*argv, "--config", config])
    return code


def test_sets_only_platform_version_when_pin_set() -> None:
    found = load().set_pin(HUB_JSON, "0.21.0")

    assert found == HUB_JSON.replace('"version": "0.20.1"', '"version": "0.21.0"')
    assert '"version": "9.9.9"' in found
    assert '"_comment": "Hub configuration; keep this layout."' in found


@pytest.mark.parametrize(
    "text",
    [
        '{"platform": {}}',
        '{"platform": {"name": "x"}, "version": "1.0.0"}',
        '{"version": "1.0.0"}',
        '{"platform": "0.20.1"}',
    ],
)
def test_exits_two_when_platform_version_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    text: str,
) -> None:
    hub = a_hub(tmp_path, text)
    monkeypatch.chdir(hub)
    cli = a_fake_hub(tmp_path, check="up to date", check_exit=0)

    assert list_pin(hub, monkeypatch, cli=cli) == 2
    assert capsys.readouterr().err.startswith("pin.py: hub.json: ")


@pytest.mark.parametrize("config", ["not json", "[]", json.dumps({"hub": {"default_branch": ""}})])
def test_exits_two_when_config_gives_no_hub_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    config: str,
) -> None:
    hub = a_hub(tmp_path)
    cli = a_fake_hub(tmp_path, check="up to date", check_exit=0)

    assert list_pin(hub, monkeypatch, cli=cli, config=config) == 2
    assert capsys.readouterr().err.startswith("pin.py: the config: ")


def test_lists_from_the_config_branch_when_hub_json_names_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The checkout's hub.json is never read for the branch: the config's is the one used.
    hub = a_hub(tmp_path, HUB_JSON.replace('"default_branch": "trunk"', '"default_branch": "gone"'))
    cli = a_fake_hub(tmp_path, check="up to date", check_exit=0)

    assert list_pin(hub, monkeypatch, cli=cli) == 0
    assert json.loads(capsys.readouterr().out)["from"] == "0.20.1"


def test_lists_would_lines_when_sync_check_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path)
    check = "\n".join(
        [
            "would update .claude/settings.json",
            "would create plugin/hub-workflow/skills/release/SKILL.md",
            "would remove 2 leftover temporary files",
            "would update hub.lock",
            "production environment: prod (access read, hub.json)",
        ]
    )
    cli = a_fake_hub(tmp_path, check=check, check_exit=4)

    code = list_pin(hub, monkeypatch, cli=cli)
    found = json.loads(capsys.readouterr().out)

    assert code == 0
    assert found["from"] == "0.20.1"
    assert found["version"] == "0.21.0"
    assert found["files"] == [
        {"verb": "update", "path": ".claude/settings.json"},
        {"verb": "create", "path": "plugin/hub-workflow/skills/release/SKILL.md"},
    ]
    assert (found["count"], found["omitted"], found["conflicts"]) == (2, 0, [])
    assert found["text"] == (
        "update .claude/settings.json\ncreate plugin/hub-workflow/skills/release/SKILL.md"
    )
    [run] = seen(tmp_path)
    assert run["pin"] == "0.21.0"
    assert run["argv"] == ["sync", "--check"]
    assert run["cwd"] != str(hub)


def test_reports_up_to_date_when_sync_check_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path)
    cli = a_fake_hub(tmp_path, check="up to date", check_exit=0)

    code = list_pin(hub, monkeypatch, cli=cli)
    found = json.loads(capsys.readouterr().out)

    assert code == 0
    assert (found["count"], found["files"], found["conflicts"]) == (0, [], [])
    assert found["text"] == "none"


def test_lists_conflicts_when_sync_check_exits_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path)
    fake = tmp_path / "conflict.py"
    fake.write_text(
        "import sys\n"
        "for n in range(60):\n"
        "    print(f'Makefile: line {n}', file=sys.stderr)\n"
        "sys.exit(3)\n"
    )
    cli = shlex.join([sys.executable, str(fake)])

    code = list_pin(hub, monkeypatch, cli=cli)
    found = json.loads(capsys.readouterr().out)

    assert code == 0
    assert found["count"] == 0
    assert len(found["conflicts"]) == 50
    assert found["conflicts"][0] == "Makefile: line 0"


def test_exits_one_when_sync_check_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path)
    fake = tmp_path / "broken.py"
    fake.write_text("import sys\nprint('hub: wrong version', file=sys.stderr)\nsys.exit(1)\n")

    code = list_pin(hub, monkeypatch, cli=shlex.join([sys.executable, str(fake)]))

    assert code == 1
    assert "hub: wrong version" in capsys.readouterr().err


def test_removes_temp_worktree_when_list_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path)
    cli = a_fake_hub(tmp_path, check="would update Makefile", check_exit=4)

    code = list_pin(hub, monkeypatch, cli=cli)
    capsys.readouterr()

    assert code == 0
    [run] = seen(tmp_path)
    assert not Path(run["cwd"]).exists()
    assert len(git(hub, "worktree", "list", "--porcelain").split("\n\n")) == 1
    assert git(hub, "status", "--porcelain") == ""
    assert json.loads((hub / "hub.json").read_text())["platform"]["version"] == "0.20.1"


def test_caps_files_when_sync_list_over_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path)
    check = "\n".join(f"would update f{n}" for n in range(510))
    cli = a_fake_hub(tmp_path, check=check, check_exit=4)

    code = list_pin(hub, monkeypatch, cli=cli)
    found = json.loads(capsys.readouterr().out)

    assert code == 0
    assert (len(found["files"]), found["omitted"], found["count"]) == (500, 10, 510)
    assert found["text"].splitlines()[-1] == "and 10 more"
    assert len(found["text"].splitlines()) == 501


def a_hub_worktree(hub: Path) -> Path:
    path = hub / ".claude/worktrees/agh-9-bump-platform"
    git(hub, "worktree", "add", "-q", "-b", "jdoe/agh-9-bump-platform", str(path), "origin/trunk")
    return path


def apply(hub: Path, worktree: Path, monkeypatch: pytest.MonkeyPatch, *, cli: str) -> int:
    monkeypatch.chdir(hub)
    argv = ["apply", "--worktree", str(worktree), "--version", "0.21.0", "--issue", "AGH-9"]
    code: int = load().main([*argv, "--cli", cli])
    return code


def test_commits_pin_and_synced_files_when_apply_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path)
    worktree = a_hub_worktree(hub)
    cli = a_fake_hub(
        tmp_path, check="up to date", check_exit=0, sync="updated Makefile\nupdated hub.lock"
    )

    assert apply(hub, worktree, monkeypatch, cli=cli) == 0
    found = json.loads(capsys.readouterr().out)

    assert (
        git(worktree, "log", "-1", "--format=%s") == "chore(hub): bump platform to 0.21.0 (AGH-9)"
    )
    assert found["sha"] == git(worktree, "rev-parse", "HEAD")
    assert git(worktree, "show", "--name-only", "--format=", "HEAD").split() == [
        "Makefile",
        "hub.json",
    ]
    assert git(worktree, "status", "--porcelain") == ""
    assert (found["from"], found["version"], found["count"]) == ("0.20.1", "0.21.0", 1)
    assert found["files"] == [{"verb": "updated", "path": "Makefile"}]
    assert "0.21.0" in found["summary"]
    assert "hub.json" in found["summary"]
    assert "Makefile" in found["summary"]
    assert [run["argv"] for run in seen(tmp_path)] == [["sync"], ["sync", "--check"]]
    assert {run["pin"] for run in seen(tmp_path)} == {"0.21.0"}
    assert git(hub, "branch", "--show-current") == "trunk"
    assert json.loads((hub / "hub.json").read_text())["platform"]["version"] == "0.20.1"


def test_exits_one_when_sync_not_up_to_date_after_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path)
    worktree = a_hub_worktree(hub)
    head = git(worktree, "rev-parse", "HEAD")
    cli = a_fake_hub(tmp_path, check="would update Makefile", check_exit=4)

    assert apply(hub, worktree, monkeypatch, cli=cli) == 1
    assert "up to date" in capsys.readouterr().err
    assert git(worktree, "rev-parse", "HEAD") == head


def test_exits_one_when_hub_worktree_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path)
    worktree = a_hub_worktree(hub)
    (worktree / "stray.txt").write_text("x")
    cli = a_fake_hub(tmp_path, check="up to date", check_exit=0)

    assert apply(hub, worktree, monkeypatch, cli=cli) == 1
    assert "not clean" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("option", "value"), [("--version", "0.21"), ("--issue", "AGH 9"), ("--worktree", "")]
)
def test_exits_two_when_apply_argument_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, option: str, value: str
) -> None:
    hub = a_hub(tmp_path)
    worktree = a_hub_worktree(hub)
    argv = ["apply", "--worktree", str(worktree), "--version", "0.21.0", "--issue", "AGH-9"]
    argv[argv.index(option) + 1] = value
    monkeypatch.chdir(hub)

    assert load().main(argv) == 2


def test_restores_hub_worktree_when_sync_not_up_to_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path)
    worktree = a_hub_worktree(hub)
    cli = a_fake_hub(tmp_path, check="would update Makefile", check_exit=4)

    assert apply(hub, worktree, monkeypatch, cli=cli) == 1
    capsys.readouterr()

    assert git(worktree, "status", "--porcelain", "--untracked-files=all") == ""
    assert (worktree / "Makefile").read_text() == "old\n"
    assert json.loads((worktree / "hub.json").read_text())["platform"]["version"] == "0.20.1"
    # The next run starts from the same clean worktree.
    good = a_fake_hub(tmp_path, check="up to date", check_exit=0, sync="updated Makefile")
    assert apply(hub, worktree, monkeypatch, cli=good) == 0


def test_reuses_pin_commit_when_apply_runs_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path)
    worktree = a_hub_worktree(hub)
    cli = a_fake_hub(tmp_path, check="up to date", check_exit=0, sync="updated Makefile")
    assert apply(hub, worktree, monkeypatch, cli=cli) == 0
    first = json.loads(capsys.readouterr().out)

    assert apply(hub, worktree, monkeypatch, cli=cli) == 0
    again = json.loads(capsys.readouterr().out)

    assert again == first
    assert [run["argv"] for run in seen(tmp_path)] == [["sync"], ["sync", "--check"]]
    assert git(worktree, "rev-list", "--count", "origin/trunk..HEAD") == "1"
