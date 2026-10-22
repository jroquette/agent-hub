"""The doc-drift pack's ``mentions.py`` (AGH-491), in process: which doc lines at the base still
name a changed name, with ADR files apart and never offered for a fix."""

import importlib.util
import io
import json
import os
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/doc-drift/scripts/mentions.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.doc-drift.scripts.mentions"


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


mentions = load()
OLD_CMD: list[dict[str, object]] = [
    {"kind": "command", "name": "old-cmd", "new": ["new-cmd"], "source": "src/cli.py"}
]


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def a_repo(tmp_path: Path, docs: dict[str, bytes]) -> tuple[Path, str]:
    repo = tmp_path / "demo-api"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "trunk")
    for name, content in docs.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    return repo, git(repo, "rev-parse", "HEAD")


def run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    contract: dict[str, object],
) -> tuple[int, dict[str, object]]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(contract)))
    code = mentions.main([])
    out = capsys.readouterr().out
    return code, (json.loads(out) if code == 0 else {})


def contract_of(repo: Path, base: str, names: list[dict[str, object]]) -> dict[str, object]:
    return {"repo_path": str(repo), "base": base, "names": names, "count": len(names)}


def test_finds_two_lines_when_two_docs_name_old_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, base = a_repo(
        tmp_path,
        {
            "docs/USING.md": b"# Using\n\nRun `demo old-cmd` to start.\n",
            "README.md": b"# Demo\n\n- `demo old-cmd`: starts the demo.\n",
            "CHANGELOG.md": b"- Adds `old-cmd`.\n",
            "src/cli.py": b'@app.command("old-cmd")\n',
        },
    )

    code, output = run(monkeypatch, capsys, contract_of(repo, base, OLD_CMD))

    assert code == 0
    assert output == {
        "fixable_count": 2,
        "fixable": [
            {
                "path": "README.md",
                "line": 3,
                "text": "- `demo old-cmd`: starts the demo.",
                "names": ["old-cmd"],
            },
            {
                "path": "docs/USING.md",
                "line": 3,
                "text": "Run `demo old-cmd` to start.",
                "names": ["old-cmd"],
            },
        ],
        "adr": [],
        "notes": [],
        "truncated": 0,
    }


@pytest.mark.parametrize(
    ("head", "status"),
    [
        ("# 9. X\n\n- Status: accepted\n", "accepted"),
        ("# 9. X\n\n- Status: accepted. Accepted by the owner on 2026-01-02.\n", "accepted"),
        ("# 9. X\n\nStatus: superseded by 0047\n", "superseded"),
        ("# 9. X\n\n## Status\n\nAccepted\n", "accepted"),
        ("# 9. X\n\n**Status:** Accepted\n", "accepted"),
    ],
)
def test_reports_accepted_adr_apart_when_it_names_an_old_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    head: str,
    status: str,
) -> None:
    text = f"{head}\nWe add `demo old-cmd`.\n"
    repo, base = a_repo(tmp_path, {"docs/adr/0009-x.md": text.encode()})
    line = text.splitlines().index("We add `demo old-cmd`.") + 1

    code, output = run(monkeypatch, capsys, contract_of(repo, base, OLD_CMD))

    assert code == 0
    assert (output["fixable_count"], output["fixable"]) == (0, [])
    assert output["adr"] == [
        {
            "path": "docs/adr/0009-x.md",
            "line": line,
            "text": "We add `demo old-cmd`.",
            "names": ["old-cmd"],
            "status": status,
        }
    ]


def test_reports_proposed_adr_as_wording_when_status_proposed() -> None:
    assert mentions.adr_status("# 9. X\n\n- Status: proposed\n") == "proposed"
    assert mentions.adr_status("# 9. X\n\nNo status here.\n") == ""
    assert mentions.is_accepted("proposed") is False
    assert mentions.is_accepted("") is False
    assert mentions.is_accepted("accepted") is True
    assert mentions.is_accepted("superseded") is True


def test_ignores_prose_word_when_name_outside_code() -> None:
    names = [{"kind": "command", "name": "run"}]
    text = "We run the tests.\nUse `hub run` now.\n```sh\nhub run --live\n```\nrunning `rerun`\n"

    assert mentions.mentions_in(text, names) == [(2, ["run"]), (4, ["run"])]


def test_numbers_lines_as_git_when_line_holds_a_unicode_separator() -> None:
    names = [{"kind": "command", "name": "old-cmd"}]
    text = "Intro\u2028still line one.\r\nRun `old-cmd`.\n"

    assert mentions.mentions_in(text, names) == [(2, ["old-cmd"])]


def test_finds_path_in_link_when_file_renamed() -> None:
    names = [{"kind": "path", "name": "docs/guide-old.md"}]
    text = "See [the guide](docs/guide-old.md).\nOr guide-old.md alone.\nNot guide-old.mdx.\n"

    assert mentions.mentions_in(text, names) == [
        (1, ["docs/guide-old.md"]),
        (2, ["docs/guide-old.md"]),
    ]


@pytest.mark.parametrize(
    ("path", "role"),
    [
        ("docs/USING.md", "edit"),
        ("docs/design/a.md", "edit"),
        ("README.md", "edit"),
        ("AGENTS.md", "edit"),
        ("CLAUDE.md", "edit"),
        ("CONTRIBUTING.md", "edit"),
        ("packages/x/README.md", "edit"),
        ("packages/x/AGENTS.md", "edit"),
        ("docs/adr/0001-x.md", "adr"),
        ("design/decisions/0001-x.md", "adr"),
        ("adrs/0001-x.md", "adr"),
        ("CHANGELOG.md", None),
        ("docs/CHANGELOG.md", None),
        (".claude/x.md", None),
        ("node_modules/a/README.md", None),
        ("packages/x/src/prompts/a.md", None),
        ("../x.md", None),
        ("docs/USING.txt", None),
        ("src/x.py", None),
    ],
)
def test_refuses_hidden_and_vendored_paths_when_doc_role_read(path: str, role: str | None) -> None:
    assert mentions.doc_role(path) == role


def test_notes_file_when_doc_is_large_or_not_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    big = b"`old-cmd`\n" + b"x" * (1024 * 1024)
    long = b"`old-cmd` " + b"y" * 2001 + b"\n"
    repo, base = a_repo(
        tmp_path,
        {
            "docs/big.md": big,
            "docs/latin.md": b"\xff `old-cmd`\n",
            "docs/long.md": long,
        },
    )

    code, output = run(monkeypatch, capsys, contract_of(repo, base, OLD_CMD))

    assert code == 0
    assert output["fixable"] == []
    assert output["notes"] == [
        {"path": "docs/big.md", "reason": "larger than 1 MiB"},
        {"path": "docs/latin.md", "reason": "not UTF-8"},
        {"path": "docs/long.md", "reason": "line 1 longer than 1000 characters"},
    ]


def test_counts_truncated_when_mentions_exceed_prompt_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    line = "Run `demo old-cmd` " + "z" * 150 + "\n"
    repo, base = a_repo(tmp_path, {"docs/USING.md": (line * 1000).encode()})

    code, output = run(monkeypatch, capsys, contract_of(repo, base, OLD_CMD))

    assert code == 0
    fixable = output["fixable"]
    assert isinstance(fixable, list)
    assert len(json.dumps(fixable).encode()) <= mentions.MAX_FIXABLE_BYTES
    assert output["fixable_count"] == len(fixable)
    assert output["truncated"] == 1000 - len(fixable)
    assert output["truncated"] > 0


def test_exits_two_when_stdin_is_not_a_contract(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))

    assert mentions.main([]) == 2
    assert capsys.readouterr().err.startswith("mentions.py: stdin: ")


def test_shrinks_fixable_budget_when_names_are_large() -> None:
    small = [{"kind": "command", "name": "old-cmd", "new": [], "source": "a.py"}]
    large = [{"kind": "path", "name": "x" * 200, "new": ["y" * 200] * 5, "source": "z" * 200}] * 50

    assert mentions.fixable_budget(small) == mentions.MAX_FIXABLE_BYTES
    assert mentions.fixable_budget(large) == (
        mentions.MAX_PROMPT_DATA - len(json.dumps(large).encode())
    )
    assert mentions.fixable_budget(large) < mentions.MAX_FIXABLE_BYTES
