"""The doc-drift pack's ``doc_fix.py`` (AGH-491), in process: ``plan`` checks the judge's lines
against the docs at the base and sorts out ADR lines; ``apply`` writes, commits and checks that
the commit holds only the approved doc lines."""

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

SCRIPTS = Path(str(files("agent_hub.core").joinpath("workflows/builtin/doc-drift/scripts")))
PACKAGE = "agent_hub.core.workflows.builtin.doc-drift.scripts"


def load(name: str = "doc_fix") -> ModuleType:
    # Named as its folder places it, so coverage of agent_hub.core measures it.
    spec = importlib.util.spec_from_file_location(f"{PACKAGE}.{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


doc_fix = load()
NAMES = [{"kind": "command", "name": "old-cmd", "new": ["new-cmd"], "source": "src/cli.py"}]
USING = "# Using\n\nRun `demo old-cmd` to start.\n"
README = "# Demo\n\n- `demo old-cmd`: starts the demo.\n"
ADR = "# 9. X\n\n- Status: accepted\n\nWe add `demo old-cmd`.\n"
DOCS = {
    "docs/USING.md": USING,
    "README.md": README,
    "docs/adr/0009-x.md": ADR,
    "CHANGELOG.md": "- Adds `old-cmd`.\n",
    "Makefile": "llms-txt:\n\tpython build.py\n",
}


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "T")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "T")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.com")


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", *args],  # noqa: S607
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def a_repo(tmp_path: Path, docs: dict[str, str] | None = None) -> tuple[Path, str]:
    repo = tmp_path / "demo-api"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "trunk")
    for name, text in (DOCS if docs is None else docs).items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    return repo, git(repo, "rev-parse", "HEAD")


def fix(path: str, line: int, change: tuple[str, str]) -> dict[str, object]:
    old, new = change
    return {"path": path, "line": line, "old": old, "new": new, "reason": "renamed"}


USING_FIX = fix(
    "docs/USING.md", 3, ("Run `demo old-cmd` to start.", "Run `demo new-cmd` to start.")
)
README_FIX = fix(
    "README.md", 3, ("- `demo old-cmd`: starts the demo.", "- `demo new-cmd`: starts the demo.")
)
ADR_LINE = {
    "path": "docs/adr/0009-x.md",
    "line": 5,
    "text": "We add `demo old-cmd`.",
    "names": ["old-cmd"],
    "status": "accepted",
}


def plan(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    where: tuple[Path, str],
    *,
    judge: str,
    adr: str = "",
    notes: str = "",
) -> dict[str, object]:
    repo, base = where
    monkeypatch.setattr(sys, "stdin", io.StringIO(judge))
    argv = ["plan", "--repo-path", str(repo), "--base", base, "--names", json.dumps(NAMES)]
    argv += ["--adr", adr, "--notes", notes]
    argv += ["--names-truncated", "", "--patch-truncated", "", "--mentions-truncated", ""]
    assert doc_fix.main(argv) == 0
    output: dict[str, object] = json.loads(capsys.readouterr().out)
    return output


def judged(*fixes: dict[str, object]) -> str:
    return json.dumps({"fixes": list(fixes), "kept": [], "more": 0})


def test_plans_both_lines_when_judge_proposes_two_valid_fixes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, base = a_repo(tmp_path)

    output = plan(monkeypatch, capsys, (repo, base), judge=judged(USING_FIX, README_FIX))

    assert (output["verdict"], output["fixes"]) == ("proposed", 2)
    assert output["items"] == [{"n": 1, **USING_FIX}, {"n": 2, **README_FIX}]
    assert (output["superseded"], output["refused"], output["notes"]) == ([], [], [])
    message = str(output["message"])
    assert "1. docs/USING.md:3" in message
    assert "- Run `demo old-cmd` to start.\n+ Run `demo new-cmd` to start." in message
    assert "2. README.md:3" in message


def test_lists_superseded_wording_when_judge_proposes_an_adr_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, base = a_repo(tmp_path)
    adr_fix = fix("docs/adr/0009-x.md", 5, ("We add `demo old-cmd`.", "We add `demo new-cmd`."))

    output = plan(monkeypatch, capsys, (repo, base), judge=judged(USING_FIX, adr_fix))

    assert [item["path"] for item in output["items"]] == ["docs/USING.md"]  # type: ignore[attr-defined]
    assert output["superseded"] == [ADR_LINE]
    assert "Superseded wording (accepted ADRs, not edited):" in str(output["message"])
    assert "docs/adr/0009-x.md:5" in str(output["message"])


@pytest.mark.parametrize(
    "target",
    [
        fix("packages/x.py", 1, ("`old-cmd`", "`new-cmd`")),
        fix("CHANGELOG.md", 1, ("- Adds `old-cmd`.", "- Adds `new-cmd`.")),
        fix("../x.md", 1, ("`old-cmd`", "`new-cmd`")),
    ],
)
def test_refuses_fix_when_path_is_not_an_allowed_doc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    target: dict[str, object],
) -> None:
    repo, base = a_repo(tmp_path)

    output = plan(monkeypatch, capsys, (repo, base), judge=judged(target))

    assert (output["items"], output["verdict"]) == ([], "reported")
    assert output["refused"] == [
        {"path": target["path"], "line": 1, "reason": "not a doc this run may change"}
    ]


def test_refuses_fix_when_old_line_differs_at_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, base = a_repo(tmp_path)
    moved = {**USING_FIX, "line": 2}
    missing = {**README_FIX, "line": 99}

    output = plan(monkeypatch, capsys, (repo, base), judge=judged(moved, missing))

    assert output["items"] == []
    assert output["refused"] == [
        {"path": "docs/USING.md", "line": 2, "reason": "the line at the base differs"},
        {"path": "README.md", "line": 99, "reason": "the line at the base differs"},
    ]


def test_refuses_fix_when_old_names_no_changed_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, base = a_repo(tmp_path)
    title = fix("docs/USING.md", 1, ("# Using", "# Use"))

    output = plan(monkeypatch, capsys, (repo, base), judge=judged(title))

    assert output["refused"] == [
        {"path": "docs/USING.md", "line": 1, "reason": "the line names no changed name"}
    ]


@pytest.mark.parametrize(
    ("new", "reason"),
    [
        ("Run `demo new-cmd`\nto start.", "the new text is not one line"),
        ("Run `demo old-cmd` to start.", "the new text is the old one"),
    ],
)
def test_refuses_fix_when_new_holds_a_newline_or_equals_old(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    new: str,
    reason: str,
) -> None:
    repo, base = a_repo(tmp_path)

    output = plan(monkeypatch, capsys, (repo, base), judge=judged({**USING_FIX, "new": new}))

    assert output["refused"] == [{"path": "docs/USING.md", "line": 3, "reason": reason}]


def test_keeps_first_fix_when_two_target_one_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, base = a_repo(tmp_path)
    second = {**USING_FIX, "new": "Run `demo other-cmd` to start."}

    output = plan(monkeypatch, capsys, (repo, base), judge=judged(USING_FIX, second))

    assert output["items"] == [{"n": 1, **USING_FIX}]
    assert output["refused"] == [
        {"path": "docs/USING.md", "line": 3, "reason": "another fix already targets this line"}
    ]


def test_returns_clean_when_judge_skipped_and_nothing_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, base = a_repo(tmp_path)

    clean = plan(monkeypatch, capsys, (repo, base), judge="")
    adr_only = plan(monkeypatch, capsys, (repo, base), judge="", adr=json.dumps([ADR_LINE]))
    noted = plan(
        monkeypatch,
        capsys,
        (repo, base),
        judge="",
        notes=json.dumps([{"path": "docs/big.md", "reason": "larger than 1 MiB"}]),
    )

    assert (clean["verdict"], clean["fixes"], clean["message"]) == ("clean", 0, "")
    assert (adr_only["verdict"], adr_only["superseded"]) == ("reported", [ADR_LINE])
    assert (noted["verdict"], noted["notes"]) == ("reported", ["docs/big.md: larger than 1 MiB"])


def test_notes_truncation_when_upstream_counts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, base = a_repo(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    argv = ["plan", "--repo-path", str(repo), "--base", base, "--names", "", "--adr", ""]
    argv += ["--notes", "", "--names-truncated", "3", "--patch-truncated", "true"]
    argv += ["--mentions-truncated", "4"]

    assert doc_fix.main(argv) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["verdict"] == "reported"
    assert output["notes"] == [
        "3 changed names past the cap were not checked",
        "the change's diff was cut: some changed names may be missing",
        "4 doc lines past the prompt budget were not judged",
    ]


@pytest.mark.parametrize(
    ("path", "head"),
    [
        ("docs/USING.md", ""),
        ("README.md", ""),
        ("packages/x/AGENTS.md", ""),
        ("docs/adr/0001-x.md", "- Status: accepted\n"),
        ("docs/adr/0002-x.md", "- Status: proposed\n"),
        ("decisions/0003-x.md", "## Status\n\nSuperseded by 0004\n"),
        ("docs/ADR/0005-x.md", "- Status: accepted\n"),
        ("CHANGELOG.md", ""),
        (".github/README.md", ""),
        ("node_modules/a/README.md", ""),
        ("src/prompts/a.md", ""),
        ("src/x.py", ""),
        ("../x.md", ""),
    ],
)
def test_classifies_paths_like_mentions_when_rules_shared(path: str, head: str) -> None:
    mentions = load("mentions")

    assert doc_fix.doc_role(path) == mentions.doc_role(path)
    assert doc_fix.adr_status(head) == mentions.adr_status(head)
    status = mentions.adr_status(head)
    assert doc_fix.is_accepted(status) == mentions.is_accepted(status)


@pytest.mark.parametrize("text", ["a\u2028b\nc\r\nd", "a\x0cb\n\nc\n", "", "one"])
def test_numbers_lines_like_mentions_when_doc_holds_odd_separators(text: str) -> None:
    mentions = load("mentions")

    assert doc_fix.doc_lines(text) == mentions.doc_lines(text)
    assert (
        doc_fix.doc_lines(text)
        == [line.removesuffix("\r") for line in text.split("\n")][
            : len(text.split("\n")) - (1 if text.endswith("\n") or not text else 0)
        ]
    )


# apply


def a_worktree(tmp_path: Path) -> tuple[Path, str]:
    repo, base = a_repo(tmp_path)
    worktree = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", "-b", "jdoe/doc-drift-r1", str(worktree), base)
    return worktree, base


def a_plan(*items: dict[str, object], superseded: list[dict[str, object]] | None = None) -> str:
    numbered = [{"n": n, **item} for n, item in enumerate(items, start=1)]
    return json.dumps(
        {
            "verdict": "proposed",
            "fixes": len(numbered),
            "items": numbered,
            "superseded": superseded or [],
            "refused": [],
            "notes": [],
            "message": "",
        }
    )


def apply(
    monkeypatch: pytest.MonkeyPatch,
    where: tuple[Path, str],
    stdin: str,
    *,
    note: str = "",
) -> int:
    worktree, base = where
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    argv = ["apply", "--worktree", str(worktree), "--base", base, "--label", "merge 0a1b2c3"]
    argv += ["--subject-prefix", "docs(repo): ", "--note", note]
    code: int = doc_fix.main(argv)
    return code


def test_replaces_only_planned_lines_when_fixes_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    worktree, base = a_worktree(tmp_path)

    code = apply(monkeypatch, (worktree, base), a_plan(USING_FIX, README_FIX))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert (output["changes"], output["files"], output["skipped"]) == (
        2,
        ["README.md", "docs/USING.md"],
        [],
    )
    assert git(worktree, "diff", "--name-only", f"{base}..HEAD").splitlines() == [
        "README.md",
        "docs/USING.md",
    ]
    assert git(worktree, "diff", "--numstat", f"{base}..HEAD").splitlines() == [
        "1\t1\tREADME.md",
        "1\t1\tdocs/USING.md",
    ]
    assert git(worktree, "log", "-1", "--format=%s") == (
        "docs(repo): fix doc lines stale after merge 0a1b2c3"
    )
    assert (worktree / "docs/USING.md").read_text() == USING.replace("old-cmd", "new-cmd")
    assert "make llms-txt" in output["summary"]


def test_keeps_line_endings_when_doc_uses_crlf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, base = a_repo(tmp_path, {"docs/USING.md": USING.replace("\n", "\r\n")})
    worktree = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", "-b", "jdoe/doc-drift-r1", str(worktree), base)

    assert apply(monkeypatch, (worktree, base), a_plan(USING_FIX)) == 0

    assert (worktree / "docs/USING.md").read_bytes() == (
        USING.replace("old-cmd", "new-cmd").replace("\n", "\r\n").encode()
    )
    assert "make" not in json.loads(capsys.readouterr().out)["summary"]


def test_refuses_adr_path_when_apply_is_given_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    worktree, base = a_worktree(tmp_path)
    adr_fix = fix("docs/adr/0009-x.md", 5, ("We add `demo old-cmd`.", "We add `demo new-cmd`."))

    code = apply(monkeypatch, (worktree, base), a_plan(USING_FIX, adr_fix))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["skipped"] == [
        {"path": "docs/adr/0009-x.md", "line": 5, "reason": "not a doc this run may change"}
    ]
    assert (worktree / "docs/adr/0009-x.md").read_text() == ADR
    assert git(worktree, "diff", "--name-only", f"{base}..HEAD") == "docs/USING.md"


def test_exits_one_when_diff_holds_a_path_outside_the_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    worktree, base = a_worktree(tmp_path)
    (worktree / "CHANGELOG.md").write_text("- Changed.\n")
    git(worktree, "add", "CHANGELOG.md")

    code = apply(monkeypatch, (worktree, base), a_plan(USING_FIX))

    assert code == 1
    assert "CHANGELOG.md" in capsys.readouterr().err


def test_skips_line_when_it_moved_since_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    worktree, base = a_worktree(tmp_path)
    moved = {**USING_FIX, "line": 1}

    code = apply(monkeypatch, (worktree, base), a_plan(moved, README_FIX))
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["skipped"] == [
        {"path": "docs/USING.md", "line": 1, "reason": "the line moved since the plan"}
    ]
    assert output["files"] == ["README.md"]


def test_resumes_without_a_second_commit_when_run_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    worktree, base = a_worktree(tmp_path)

    assert apply(monkeypatch, (worktree, base), a_plan(USING_FIX)) == 0
    assert apply(monkeypatch, (worktree, base), a_plan(USING_FIX)) == 0
    second = json.loads(capsys.readouterr().out.splitlines()[-1])

    assert git(worktree, "rev-list", "--count", f"{base}..HEAD") == "1"
    assert (second["changes"], second["files"]) == (1, ["docs/USING.md"])


def test_cuts_owner_note_when_longer_than_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    worktree, base = a_worktree(tmp_path)
    note = "ok\x07 ```" + "n" * 5000

    assert apply(monkeypatch, (worktree, base), a_plan(USING_FIX), note=note) == 0
    summary = json.loads(capsys.readouterr().out)["summary"]

    kept = "ok ```" + "n" * (doc_fix.MAX_NOTE - 6)
    assert f"\n````text\n{kept}\n````\n" in summary
    assert "\x07" not in summary
    assert len(summary) <= doc_fix.MAX_SUMMARY


def test_names_superseded_wording_in_summary_when_plan_has_some(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    worktree, base = a_worktree(tmp_path)
    proposed = {**ADR_LINE, "path": "docs/adr/0010-y.md", "status": "proposed"}

    stdin = a_plan(USING_FIX, superseded=[ADR_LINE, proposed])
    assert apply(monkeypatch, (worktree, base), stdin) == 0
    summary = json.loads(capsys.readouterr().out)["summary"]

    assert "Superseded wording (accepted ADRs, not edited):\n- `docs/adr/0009-x.md:5`" in summary
    assert "ADR wording to change by hand" in summary
    assert "`docs/adr/0010-y.md:5`" in summary


def test_names_regenerate_target_when_makefile_holds_a_long_line(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / "Makefile").write_text("x = " + "llms" * 10000 + "\nllms-txt:\n\tpython b.py\n")

    assert "`make llms-txt`" in doc_fix._regenerate(worktree)


# M1: the commit itself breaks the plan; only the numstat check sees it.
@pytest.mark.parametrize(
    "extra",
    [
        {"CHANGELOG.md": "- Changed.\n"},
        {"docs/USING.md": USING.replace("old-cmd", "new-cmd").replace("# Using", "# Use")},
    ],
)
def test_exits_one_when_commit_holds_more_than_the_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    extra: dict[str, str],
) -> None:
    worktree, base = a_worktree(tmp_path)
    (worktree / "docs/USING.md").write_text(USING.replace("old-cmd", "new-cmd"))
    for name, text in extra.items():
        (worktree / name).write_text(text)
    git(worktree, "commit", "-qam", "docs(repo): fix doc lines stale after merge 0a1b2c3")

    code = apply(monkeypatch, (worktree, base), a_plan(USING_FIX))

    assert code == 1
    assert "beyond the approved lines" in capsys.readouterr().err


@pytest.mark.parametrize("note", ["-x", "--looks-like-an-option"])
def test_applies_when_owner_note_starts_with_a_dash(
    note: str,
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The owner's note is data (AGH-480): a leading dash is never read as an option.
    worktree, base = a_worktree(tmp_path)

    code = apply(monkeypatch, (worktree, base), a_plan(USING_FIX), note=note)

    assert code == 0, capsys.readouterr().err
    assert note in json.loads(capsys.readouterr().out)["summary"]
