"""Parsing ``git diff`` and ``git log --numstat`` output into a repository's file changes."""

from agent_hub.hub_git.repo_changes import parse_log, parse_patch

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


def test_parse_patch_reads_each_file_s_status_and_diff() -> None:
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


def test_a_hunk_line_that_looks_like_a_header_stays_in_the_diff() -> None:
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


def test_parse_log_reads_commits_newest_first_and_each_file_s_lines() -> None:
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
