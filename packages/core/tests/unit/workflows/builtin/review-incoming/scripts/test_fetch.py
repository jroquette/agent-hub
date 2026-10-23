"""The review-incoming pack's ``fetch.py`` (AGH-493), in process: the PR's facts from the files
``/review`` wrote and the local clone, every untrusted field bounded, read-only."""

import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REF = "refs/agent-hub/review/7"
WIDE = "\U0001d11e"
OUTPUT_CAP = 131072
# The conftest's ``Clone``: a hub, its repo's clone, ``base`` and ``head``.
type Clone = Any


@pytest.fixture
def fetch(script: Any) -> ModuleType:
    module: ModuleType = script("fetch")
    return module


def a_pr(clone: Clone, **changes: Any) -> dict[str, Any]:
    pr: dict[str, Any] = {
        "number": 7,
        "state": "open",
        "merged": False,
        "merged_at": None,
        "html_url": "https://github.com/example/api/pull/7",
        "title": "Adds the run step",
        "body": "Runs a job.",
        "user": {"login": "someone"},
        "head": {"sha": clone.head, "ref": "feature/run", "repo": {"full_name": "example/api"}},
        "base": {"ref": "main", "repo": {"full_name": "example/api"}},
    }
    return pr | changes


def a_run(name: str, status: str = "completed", conclusion: str | None = "success") -> Any:
    return {"name": name, "status": status, "conclusion": conclusion}


def given(
    clone: Clone,
    pr: Any = None,
    *,
    ci: Any = None,
    spec: str = "",
    ref: str = REF,
    extra: tuple[str, ...] = (),
) -> list[str]:
    folder = clone.hub.parent / "files"
    folder.mkdir(exist_ok=True)
    pr_file, ci_file, spec_file = folder / "pr.json", folder / "ci.json", folder / "spec.txt"
    pr_file.write_text(json.dumps(a_pr(clone) if pr is None else pr), encoding="utf-8")
    checks = {"total_count": 1, "check_runs": [a_run("test")]} if ci is None else ci
    ci_file.write_text(checks if isinstance(checks, str) else json.dumps(checks), encoding="utf-8")
    spec_file.write_text(spec, encoding="utf-8")
    return [
        "--repo",
        "api",
        "--pr",
        "7",
        "--ref",
        ref,
        "--pr-file",
        str(pr_file),
        "--ci-file",
        str(ci_file),
        "--spec-file",
        str(spec_file),
        "--config",
        clone.config,
        *extra,
    ]


@pytest.fixture
def run(fetch: ModuleType, capsys: pytest.CaptureFixture[str]) -> Any:
    def running(argv: list[str]) -> tuple[int, Any, str]:
        return outcome(fetch, argv, capsys)

    return running


def outcome(
    fetch: ModuleType, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, Any, str]:
    code = fetch.main(argv)
    captured = capsys.readouterr()
    return code, json.loads(captured.out) if code == 0 else None, captured.err


def test_prints_pr_facts_and_changed_files_when_files_and_ref_agree(clone: Clone, run: Any) -> None:
    code, facts, _ = run(given(clone, spec="AC-1 Given a job, then it runs."))

    assert code == 0
    assert facts["number"] == 7
    assert facts["url"] == "https://github.com/example/api/pull/7"
    assert facts["title"] == "Adds the run step"
    assert facts["author"] == "someone"
    assert facts["fork"] is False
    assert facts["head_sha"] == clone.head
    assert facts["head_ref"] == "feature/run"
    assert facts["base_ref"] == "main"
    assert facts["merge_base"] == clone.base
    assert facts["path"] == str(clone.repo)
    assert facts["hub"] == str(clone.hub)
    assert facts["check"] == "make check"
    assert facts["files"] == [{"status": "A", "path": "app/run.py"}]
    assert facts["more_files"] is False
    assert facts["spec"] == "AC-1 Given a job, then it runs."
    assert facts["ci"] == {
        "state": "success",
        "runs": [{"name": "test", "status": "completed", "conclusion": "success"}],
        "more": False,
    }


@pytest.mark.parametrize(
    "head_repo", [None, {"full_name": "someone/api"}], ids=["deleted", "other"]
)
def test_marks_fork_when_head_repo_is_deleted(clone: Clone, run: Any, head_repo: Any) -> None:
    pr = a_pr(clone)
    pr["head"] = pr["head"] | {"repo": head_repo}

    code, facts, _ = run(given(clone, pr))

    assert code == 0
    assert facts["fork"] is True


def test_finds_issue_keys_in_title_branch_and_body_when_team_key_set(
    clone: Clone, run: Any
) -> None:
    pr = a_pr(clone, title="DEM-3: run", body="Also dem-12, not XDEM-5 nor DEM-0.")
    pr["head"] = pr["head"] | {"ref": "jo/dem-9-run"}

    code, facts, _ = run(given(clone, pr))

    assert code == 0
    assert facts["issues"] == ["DEM-3", "DEM-9", "DEM-12"]


@pytest.mark.parametrize(
    "case",
    [
        ([a_run("lint"), a_run("test", conclusion="failure")], "failure"),
        ([a_run("lint"), a_run("test", status="in_progress", conclusion=None)], "pending"),
        ([], "none"),
        ([a_run("lint"), a_run("test")], "success"),
    ],
    ids=["failure", "pending", "none", "success"],
)
def test_summarizes_ci_as_failure_when_one_run_failed(
    clone: Clone, run: Any, case: tuple[list[Any], str]
) -> None:
    runs, state = case
    code, facts, _ = run(given(clone, ci={"total_count": len(runs), "check_runs": runs}))

    assert code == 0
    assert facts["ci"]["state"] == state
    assert len(facts["ci"]["runs"]) == len(runs)


def test_reads_ci_as_unknown_when_ci_file_is_not_json(clone: Clone, run: Any) -> None:
    code, facts, _ = run(given(clone, ci="not json"))

    assert code == 0
    assert facts["ci"] == {"state": "unknown", "runs": [], "more": False}


def test_bounds_title_and_body_when_long(clone: Clone, run: Any) -> None:
    pr = a_pr(clone, title="T\x1b[31m```x" + "t" * 400, body="a\x00b\tc\r\n````fence" + "b" * 20000)

    code, facts, _ = run(given(clone, pr))

    assert code == 0
    assert facts["title"].startswith("T[31m`x")
    assert len(facts["title"]) == 256
    assert facts["body"].startswith("ab\tc\n`fence")
    assert len(facts["body"]) == 16384
    assert facts["body_cut"] is True


@pytest.mark.parametrize("ref", ["refs/heads/feature", "refs/agent-hub/review/8"])
def test_exits_two_when_ref_is_not_the_review_ref(clone: Clone, run: Any, ref: str) -> None:
    code, _, err = run(given(clone, ref=ref))

    assert code == 2
    assert "ref must be refs/agent-hub/review/<pr>" in err


def test_exits_two_when_ref_differs_from_head(clone: Clone, run: Any) -> None:
    pr = a_pr(clone)
    pr["head"] = pr["head"] | {"sha": clone.base}

    code, _, err = run(given(clone, pr))

    assert code == 2
    assert "the PR moved or the ref is missing; fetch again" in err


@pytest.mark.parametrize(
    "changes",
    [{"state": "closed"}, {"merged": True}, {"merged_at": "2026-10-01T00:00:00Z"}],
    ids=["closed", "merged", "merged-at"],
)
def test_exits_two_when_pr_is_closed(clone: Clone, run: Any, changes: dict[str, Any]) -> None:
    code, _, err = run(given(clone, a_pr(clone, **changes)))

    assert code == 2
    assert "PR #7 is closed or merged" in err


def test_exits_two_when_repo_is_unknown(clone: Clone, run: Any) -> None:
    argv = given(clone)
    argv[argv.index("--repo") + 1] = "web"

    code, _, err = run(argv)

    assert code == 2
    assert "no repo web in the config" in err


@pytest.mark.parametrize("config", ["not json", "[]", '{"repos": {}}'])
def test_exits_two_when_config_is_unreadable(clone: Clone, run: Any, config: str) -> None:
    argv = given(clone)
    argv[argv.index("--config") + 1] = config

    code, _, err = run(argv)

    assert code == 2
    assert "the config" in err


def test_reads_no_hub_json_when_config_given(clone: Clone, run: Any) -> None:
    (clone.hub / "hub.json").write_text(json.dumps({"repos": []}), encoding="utf-8")

    code, facts, _ = run(given(clone))

    assert code == 0
    assert facts["check"] == "make check"


@pytest.mark.parametrize("number", ["0", "07", "7a", "-7", "1234567890", ""])
def test_exits_two_when_pr_is_not_a_number(clone: Clone, run: Any, number: str) -> None:
    argv = given(clone)
    argv[3] = number

    code, _, err = run(argv)

    assert code == 2
    assert "pr must be a PR number" in err


def test_exits_two_when_pr_number_differs_from_file(clone: Clone, run: Any) -> None:
    code, _, err = run(given(clone, a_pr(clone, number=8)))

    assert code == 2
    assert "not a PR: number" in err


def test_exits_two_when_pr_file_is_a_link(clone: Clone, run: Any) -> None:
    argv = given(clone)
    target = Path(argv[7])
    link = target.with_name("link.json")
    link.symlink_to(target)
    argv[7] = str(link)

    code, _, err = run(argv)

    assert code == 2
    assert "cannot read pr_file" in err


def test_exits_two_when_pr_file_is_relative(clone: Clone, run: Any) -> None:
    argv = given(clone)
    argv[7] = "../files/pr.json"

    code, _, err = run(argv)

    assert code == 2
    assert "cannot read pr_file: not an absolute path" in err


def test_exits_two_when_pr_file_is_over_cap(clone: Clone, run: Any) -> None:
    code, _, err = run(given(clone, a_pr(clone, body="b" * (1024 * 1024))))

    assert code == 2
    assert "cannot read pr_file: over 1048576 bytes" in err


def test_exits_two_when_spec_file_is_over_cap(clone: Clone, run: Any) -> None:
    code, _, err = run(given(clone, spec="s" * 32769))

    assert code == 2
    assert "cannot read spec_file: over 32768 bytes" in err


def test_stays_under_output_cap_when_every_field_is_full(clone: Clone, run: Any) -> None:
    # 250 files, each path 300 four-byte characters in folders a file system accepts.
    component = WIDE * 49
    changes = {"/".join([f"{n:03d}{component}" for _ in range(6)])[:300]: "x\n" for n in range(250)}
    clone.commit(changes)
    pr = a_pr(clone, title=WIDE * 1000, body=WIDE * 40000, html_url="h" * 2000)
    pr["user"] = {"login": WIDE * 400}
    pr["head"] = pr["head"] | {"ref": WIDE * 400}
    runs = [a_run(WIDE * 400, status=WIDE * 50, conclusion=WIDE * 50) for _ in range(100)]
    ci = {"total_count": 100, "check_runs": runs}

    code, facts, _ = run(given(clone, pr, ci=ci, spec=WIDE * 8192))

    assert code == 0
    assert facts["more_files"] is True
    assert facts["ci"]["more"] is True
    assert len(facts["ci"]["runs"]) == 30
    assert len(json.dumps(facts, ensure_ascii=False).encode()) <= OUTPUT_CAP


def test_leaves_repo_unchanged_when_facts_read(clone: Clone, run: Any) -> None:
    before = clone.state()

    code, _, _ = run(given(clone))

    assert code == 0
    assert clone.state() == before
    assert clone.git("rev-parse", REF) == clone.head


def test_reads_body_as_whole_when_cleaning_shortens_nothing_it_keeps(
    clone: Clone, run: Any
) -> None:
    code, facts, _ = run(given(clone, a_pr(clone, body="a``\x00`b")))

    assert code == 0
    assert facts["body"] == "a`b"
    assert facts["body_cut"] is False
