"""Parsing ``git diff`` and ``git log --numstat`` output into a repository's file changes."""

import os
from collections.abc import Sequence
from pathlib import Path

import pytest

from agent_hub.core.agent_sessions.repo_changes import RepoPullRequest
from agent_hub.hub_git.git_runner import ProcessResult
from agent_hub.hub_git.repo_changes import GitRepoChanges, parse_log, parse_patch

_PATCH = """\
diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,3 @@
 a
-b
+B
 c
diff --git a/src/new.py b/src/new.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,2 @@
+one
+two
diff --git a/src/gone.py b/src/gone.py
deleted file mode 100644
index 4444444..0000000
--- a/src/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-bye
diff --git a/old name.py b/new name.py
similarity index 100%
rename from old name.py
rename to new name.py
diff --git a/logo.png b/logo.png
index 5555555..6666666 100644
Binary files a/logo.png and b/logo.png differ
"""


def test_reads_each_file_s_status_and_diff_when_a_patch_is_parsed() -> None:
    patches = {patch.path: patch for patch in parse_patch(_PATCH)}

    assert {path: patch.status for path, patch in patches.items()} == {
        "src/app.py": "modified",
        "src/new.py": "added",
        "src/gone.py": "deleted",
        "new name.py": "renamed",
        "logo.png": "modified",
    }
    assert patches["src/app.py"].lines == [
        "--- a/src/app.py",
        "+++ b/src/app.py",
        "@@ -1,3 +1,3 @@",
        " a",
        "-b",
        "+B",
        " c",
    ]
    assert patches["new name.py"].old_path == "old name.py"
    assert patches["new name.py"].lines == []
    assert patches["logo.png"].binary


def test_keeps_a_hunk_line_in_the_diff_when_it_looks_like_a_header() -> None:
    patch = """\
diff --git a/notes.txt b/notes.txt
--- a/notes.txt
+++ b/notes.txt
@@ -1 +1,2 @@
 keep
+--- not a header
"""

    [only] = parse_patch(patch)

    assert only.lines[-1] == "+--- not a header"
    assert only.path == "notes.txt"


def test_reads_commits_newest_first_when_a_log_is_parsed() -> None:
    log = (
        "\x1eaaa\x1fAna\x1f2026-10-19T15:00:00+01:00\x1fsecond\n\n3\t1\tsrc/app.py\n"
        "\x1ebbb\x1fAna\x1f2026-10-19T14:00:00+01:00\x1ffirst\n\n"
        "10\t0\tsrc/app.py\n-\t-\tlogo.png\n"
    )

    commits, by_path = parse_log(log)

    assert [(commit.sha, commit.subject) for commit in commits] == [
        ("aaa", "second"),
        ("bbb", "first"),
    ]
    assert [(c.sha, c.added, c.removed) for c in by_path["src/app.py"]] == [
        ("aaa", 3, 1),
        ("bbb", 10, 0),
    ]
    assert [(c.added, c.removed) for c in by_path["logo.png"]] == [(0, 0)]


def test_names_the_pull_request_when_gh_lists_one_for_the_branch(tmp_path: Path) -> None:
    asked: list[list[str]] = []

    def launch(argv: Sequence[str], **_: object) -> ProcessResult:
        asked.append(list(argv))
        out = b'[{"number":545,"url":"https://github.com/acme/ui/pull/545","state":"OPEN","headRefOid":"abc"}]'
        return ProcessResult(returncode=0, stdout=out)

    reader = GitRepoChanges(gh="git", launch=launch, environ={"PATH": os.environ["PATH"]})

    pull = reader.pull_request(str(tmp_path / "gone" / "tree"), branch="tip-1")

    assert pull == RepoPullRequest(
        number=545, url="https://github.com/acme/ui/pull/545", state="OPEN", head_sha="abc"
    )
    assert asked[0][1:5] == ["pr", "list", "--head", "tip-1"]


@pytest.mark.parametrize("stdout", [b"[]", b"not json", b'[{"number":"x"}]'])
def test_no_pull_request_when_gh_names_none(tmp_path: Path, stdout: bytes) -> None:
    reader = GitRepoChanges(
        gh="git",
        launch=lambda argv, **_: ProcessResult(returncode=0, stdout=stdout),
        environ={"PATH": os.environ["PATH"]},
    )

    assert reader.pull_request(str(tmp_path), branch="tip-1") is None


def test_names_no_pull_request_when_the_branch_reads_as_an_option(tmp_path: Path) -> None:
    reader = GitRepoChanges(gh="git", environ={"PATH": os.environ["PATH"]})

    assert reader.pull_request(str(tmp_path), branch="--web") is None
