from agent_hub.core.agent_sessions.diff import (
    INPUT_MAX_BYTES,
    INPUT_MAX_LINES,
    edit_diff,
    patch_diff,
    write_diff,
)


def test_builds_unified_diff_when_edit_replaces_string() -> None:
    diff = edit_diff("src/app.py", "a = 1\nb = 2\n", "a = 1\nb = 3\n")

    assert diff == ("--- a/src/app.py\n+++ b/src/app.py\n@@ -1,2 +1,2 @@\n a = 1\n-b = 2\n+b = 3\n")


def test_ends_every_line_when_text_has_no_final_newline() -> None:
    diff = edit_diff("x.py", "old", "new")

    assert diff == "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n"


def test_adds_every_line_when_file_written() -> None:
    diff = write_diff("notes.md", "one\ntwo\n")

    assert diff == "--- /dev/null\n+++ b/notes.md\n@@ -0,0 +1,2 @@\n+one\n+two\n"


def test_answers_empty_when_nothing_changes() -> None:
    assert edit_diff("x.py", "same\n", "same\n") == ""


def test_caps_diff_when_large() -> None:
    old = "".join(f"line {n}\n" for n in range(2000))
    new = "".join(f"line {n} changed\n" for n in range(2000))

    diff = edit_diff("big.txt", old, new, limit=1024)

    assert len(diff.encode()) <= 1024
    assert diff.startswith("--- a/big.txt\n+++ b/big.txt\n")
    assert diff.endswith("bytes)\n")
    assert all(line.endswith("\n") for line in diff.splitlines(keepends=True))


def test_pins_input_bounds_when_imported() -> None:
    assert (INPUT_MAX_BYTES, INPUT_MAX_LINES) == (256 * 1024, 5000)


def test_omits_diff_when_edit_input_one_byte_over_bound() -> None:
    old = "a" * (128 * 1024)
    new = "b" * (128 * 1024 + 1)

    diff = edit_diff("big.txt", old, new)

    assert diff == "--- a/big.txt\n+++ b/big.txt\n... diff omitted (262145 bytes)\n"


def test_diffs_edit_when_input_at_byte_bound() -> None:
    diff = edit_diff("big.txt", "a" * (128 * 1024), "b" * (128 * 1024), limit=64)

    assert diff.startswith("--- a/big.txt\n+++ b/big.txt\n")
    assert "omitted" not in diff


def test_omits_diff_when_edit_input_one_line_over_bound() -> None:
    old = "x\n" * 2500
    new = "y\n" * 2501

    diff = edit_diff("many.txt", old, new)

    assert diff == "--- a/many.txt\n+++ b/many.txt\n... diff omitted (10002 bytes)\n"


def test_diffs_edit_when_input_at_line_bound() -> None:
    diff = edit_diff("many.txt", "x\n" * 2500, "y\n" * 2500)

    assert diff.startswith("--- a/many.txt\n+++ b/many.txt\n@@ -1,2500 +1,2500 @@\n")


def test_omits_diff_when_written_content_over_bound() -> None:
    diff = write_diff("big.md", "é" * (128 * 1024) + "!")

    assert diff == "--- /dev/null\n+++ b/big.md\n... diff omitted (262145 bytes)\n"


def test_renders_engine_hunks_with_file_line_numbers_when_patch_given() -> None:
    hunks = [
        {
            "oldStart": 12,
            "oldLines": 3,
            "newStart": 12,
            "newLines": 4,
            "lines": [" a", "-b", "+c", "+d", " e"],
        },
        {"oldStart": 40, "oldLines": 1, "newStart": 41, "newLines": 1, "lines": ["-x", "+y"]},
    ]

    diff = patch_diff("src/app.py", hunks)

    assert diff == (
        "--- a/src/app.py\n+++ b/src/app.py\n"
        "@@ -12,3 +12,4 @@\n a\n-b\n+c\n+d\n e\n"
        "@@ -40,1 +41,1 @@\n-x\n+y\n"
    )


def test_returns_none_when_patch_not_engine_shape() -> None:
    good = {"oldStart": 1, "oldLines": 1, "newStart": 1, "newLines": 1, "lines": ["-a", "+b"]}

    assert patch_diff("x.py", []) is None
    assert patch_diff("x.py", None) is None
    assert patch_diff("x.py", [good | {"oldStart": "1"}]) is None
    assert patch_diff("x.py", [good | {"newLines": -1}]) is None
    assert patch_diff("x.py", [good | {"lines": [1]}]) is None
    assert patch_diff("x.py", ["@@"]) is None


def test_caps_patch_diff_when_over_limit() -> None:
    hunk = {
        "oldStart": 1,
        "oldLines": 0,
        "newStart": 1,
        "newLines": 500,
        "lines": ["+" + "x" * 99] * 500,
    }

    diff = patch_diff("x.py", [hunk], limit=2_000)

    assert diff is not None
    assert len(diff.encode()) <= 2_000
    assert diff.endswith(" bytes)\n")
    assert "... diff truncated (" in diff
