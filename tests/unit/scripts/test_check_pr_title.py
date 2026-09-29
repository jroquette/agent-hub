import pytest

from scripts.check_pr_title import main, problems


@pytest.mark.parametrize(
    "title",
    [
        "feat(collector): ingest hook events",
        "chore(repo): foundation workspace, gates, ADRs and English docs",
        "fix(cli)!: rename flag",
    ],
)
def test_accepts_title_when_type_scope_and_subject_valid(title: str) -> None:
    assert problems(title) == []


@pytest.mark.parametrize(
    "title",
    ["feat(): ingest hook events", "feat(core):", "feat(core):ingest", "Feat(core): ingest"],
)
def test_rejects_title_when_shape_malformed(title: str) -> None:
    assert problems(title) != []


def test_accepts_title_when_generator_scope_used() -> None:
    assert problems("feat(generator): render the hub templates") == []


def test_rejects_title_when_scope_missing() -> None:
    assert problems("feat: ingest hook events") != []


def test_rejects_title_when_type_unknown() -> None:
    assert problems("feature(core): ingest hook events") != []


def test_rejects_title_when_scope_unknown() -> None:
    assert problems("feat(server): ingest hook events") != []


@pytest.mark.parametrize("title", ["feat(core): x\n", "feat(core): x ", "feat(core): x\t"])
def test_rejects_title_when_trailing_whitespace(title: str) -> None:
    assert problems(title) != []


def test_accepts_title_when_subject_single_char() -> None:
    assert problems("feat(core): x") == []


def test_rejects_title_when_subject_empty() -> None:
    assert problems("feat(core): ") != []


def test_rejects_title_when_longer_than_72_chars() -> None:
    title = "feat(core): " + "x" * 61

    assert len(title) == 73
    assert any("72" in problem for problem in problems(title))


def test_accepts_title_when_exactly_72_chars() -> None:
    assert problems("feat(core): " + "x" * 60) == []


def test_rejects_title_when_ends_with_period() -> None:
    assert any("period" in problem for problem in problems("feat(core): ingest events."))


def test_exits_nonzero_when_title_invalid(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["feat: no scope"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "collector" in out
    assert "refactor" in out


def test_exits_zero_when_title_valid(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["feat(collector): ingest hook events"]) == 0
    assert capsys.readouterr().out == ""


def test_exits_with_usage_error_when_title_argument_missing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 2
    assert "usage" in capsys.readouterr().err
