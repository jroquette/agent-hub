import json
from typing import Any

import pytest

from agent_hub.core.bench.bench_cases import (
    CASE_ID_PATTERN,
    ENV_KEY_PATTERN,
    MAX_CASES,
    MAX_CASES_BYTES,
    MAX_ENV_KEYS,
    MAX_HIDDEN_TESTS,
    MAX_PROMPT_CHARS,
    MAX_SETUP_CMD_CHARS,
    MAX_TEST_CMD_ARG_CHARS,
    MAX_TEST_CMD_ARGS,
    MAX_TEST_PATH_CHARS,
    MERGE_PATTERN,
    TASKS_PATH,
    BenchCase,
    CaseProblem,
    bench_cases,
    case_problems,
    read_cases,
    unknown_repo_line,
)
from agent_hub.core.json_form import JsonValue

REPOS = ("api", "web")
SHA = "0123456789abcdef0123456789abcdef01234567"


def a_case(**changes: Any) -> dict[str, Any]:
    """The hub characterization golden's case shape: duplicated hidden tests, an int env value."""
    case: dict[str, Any] = {
        "id": "T1",
        "repo": "api",
        "merge": SHA,
        "prompt": "Add the fix",
        "hidden_tests": ["t/__main__.py", "a/__main__.py", "t/__main__.py"],
        "test_cmd": ["python3"],
        "setup_cmd": "echo ready > setup.txt",
        "env": {"CHECK_MODE": 1},
    }
    case.update(changes)
    return case


def without(key: str) -> dict[str, Any]:
    case = a_case()
    del case[key]
    return case


def texts(cases: list[JsonValue]) -> list[str]:
    return [problem.text for problem in case_problems(cases, repos=REPOS)]


def test_pins_bounds_when_module_loaded() -> None:
    assert TASKS_PATH == "brain/workflow/bench/tasks.json"
    assert MAX_CASES_BYTES == 1_048_576
    assert MAX_CASES == 200
    assert CASE_ID_PATTERN == "[A-Za-z0-9._-]{1,64}"
    assert MERGE_PATTERN == "[0-9a-f]{7,40}"
    assert MAX_PROMPT_CHARS == 20_000
    assert MAX_HIDDEN_TESTS == 100
    assert MAX_TEST_PATH_CHARS == 1024
    assert MAX_TEST_CMD_ARGS == 32
    assert MAX_TEST_CMD_ARG_CHARS == 1024
    assert MAX_SETUP_CMD_CHARS == 4096
    assert MAX_ENV_KEYS == 32
    assert ENV_KEY_PATTERN == "[A-Za-z_][A-Za-z0-9_]*"


def test_accepts_case_when_shape_valid() -> None:
    cases: list[JsonValue] = [a_case(), a_case(id="T0", repo="gone", excluded=True)]

    assert case_problems(cases, repos=REPOS) == []
    assert bench_cases(cases) == (
        BenchCase(
            id="T1",
            repo="api",
            merge=SHA,
            prompt="Add the fix",
            hidden_tests=("t/__main__.py", "a/__main__.py", "t/__main__.py"),
            test_cmd=("python3",),
            setup_cmd="echo ready > setup.txt",
            env={"CHECK_MODE": "1"},
            excluded=False,
        ),
        BenchCase(
            id="T0",
            repo="gone",
            merge=SHA,
            prompt="Add the fix",
            hidden_tests=("t/__main__.py", "a/__main__.py", "t/__main__.py"),
            test_cmd=("python3",),
            setup_cmd="echo ready > setup.txt",
            env={"CHECK_MODE": "1"},
            excluded=True,
        ),
    )


def test_keeps_defaults_when_optional_keys_absent() -> None:
    case = without("setup_cmd")
    del case["env"]

    assert case_problems([case], repos=REPOS) == []
    [read] = bench_cases([case])
    assert (read.setup_cmd, read.env, read.excluded) == ("", {}, False)


def test_writes_env_values_as_the_script_when_number_or_boolean() -> None:
    case = a_case(env={"A": "x", "B": 1, "C": 1.5, "D": True, "E": False})

    [read] = bench_cases([case])

    assert read.env == {"A": "x", "B": "1", "C": "1.5", "D": "True", "E": "False"}


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        (without("id"), "[0].id: is missing"),
        (without("repo"), "[0].repo: is missing"),
        (without("merge"), "[0].merge: is missing"),
        (without("prompt"), "[0].prompt: is missing"),
        (without("hidden_tests"), "[0].hidden_tests: is missing"),
        (without("test_cmd"), "[0].test_cmd: is missing"),
        (a_case(id=1), "[0].id: must be a string"),
        (a_case(repo=None), "[0].repo: must be a string"),
        (a_case(merge=["x"]), "[0].merge: must be a string"),
        (a_case(prompt={"text": "x"}), "[0].prompt: must be a string"),
        (a_case(hidden_tests="t/__main__.py"), "[0].hidden_tests: must be a list of strings"),
        (a_case(hidden_tests=["t", 1]), "[0].hidden_tests: must be a list of strings"),
        (a_case(test_cmd="python3 -m pytest"), "[0].test_cmd: must be a list of strings"),
        (a_case(test_cmd=[True]), "[0].test_cmd: must be a list of strings"),
        (a_case(setup_cmd=None), "[0].setup_cmd: must be a string"),
        (a_case(env=["A=1"]), "[0].env: must be an object"),
        (a_case(excluded="yes"), "[0].excluded: must be true or false"),
        ("T1", "[0]: must be an object"),
    ],
)
def test_reports_problem_when_field_missing_or_wrong_type(case: JsonValue, expected: str) -> None:
    assert texts([case]) == [expected]


ID_BOUND = "must be 1 to 64 characters among A-Z, a-z, 0-9, `.`, `_` and `-`"
MERGE_BOUND = "must be a commit sha: 7 to 40 characters among 0-9 and a-f"
PROMPT_BOUND = "must be 1 to 20000 characters"
HIDDEN_COUNT = "must list 1 to 100 paths"
PATH_BOUND = (
    "is not a literal relative path in the repo (no empty, `.`, `..` or `.git` segment in any"
    " case, no leading `/`, `-` or `:`, no `*`, `?`, `[`, `\\`, control, format or surrogate"
    " character, 1 to 1024 characters)"
)
TEST_CMD_BOUND = "must be 1 to 32 non-empty strings of at most 1024 characters"
SETUP_BOUND = "must be at most 4096 characters"
NUL = "must not hold a NUL character"
ENV_COUNT = "must have at most 32 keys"
ENV_VALUE = "must be a string, a number, true or false"


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"id": ""}, f"[0].id: {ID_BOUND}"),
        ({"id": "x" * 65}, f"[0].id: {ID_BOUND}"),
        ({"id": "T 1"}, f"[0].id: {ID_BOUND}"),
        ({"id": "T1/x"}, f"[0].id: {ID_BOUND}"),
        ({"id": "T1\n"}, f"[0].id: {ID_BOUND}"),
        ({"merge": "abc123"}, f"[0].merge: {MERGE_BOUND}"),
        ({"merge": SHA + "0"}, f"[0].merge: {MERGE_BOUND}"),
        ({"merge": "ABCDEF0"}, f"[0].merge: {MERGE_BOUND}"),
        ({"merge": "--orphan"}, f"[0].merge: {MERGE_BOUND}"),
        ({"merge": "abcdef0\n"}, f"[0].merge: {MERGE_BOUND}"),
        ({"prompt": ""}, f"[0].prompt: {PROMPT_BOUND}"),
        ({"prompt": "x" * 20_001}, f"[0].prompt: {PROMPT_BOUND}"),
        ({"prompt": "a\x00b"}, f"[0].prompt: {NUL}"),
        ({"hidden_tests": []}, f"[0].hidden_tests: {HIDDEN_COUNT}"),
        ({"hidden_tests": ["t.py"] * 101}, f"[0].hidden_tests: {HIDDEN_COUNT}"),
        ({"hidden_tests": ["t/../x.py"]}, f'[0].hidden_tests: "t/../x.py" {PATH_BOUND}'),
        ({"hidden_tests": [".."]}, f'[0].hidden_tests: ".." {PATH_BOUND}'),
        ({"hidden_tests": ["/etc/x.py"]}, f'[0].hidden_tests: "/etc/x.py" {PATH_BOUND}'),
        ({"hidden_tests": ["--force"]}, f'[0].hidden_tests: "--force" {PATH_BOUND}'),
        ({"hidden_tests": [""]}, f'[0].hidden_tests: "" {PATH_BOUND}'),
        ({"hidden_tests": ["t", "a" * 1025]}, f'[0].hidden_tests: "{"a" * 78}… {PATH_BOUND}'),
        ({"hidden_tests": ["t\x00.py"]}, f"[0].hidden_tests: {NUL}"),
        ({"hidden_tests": ["."]}, f"[0].hidden_tests: {json.dumps('.')} {PATH_BOUND}"),
        ({"hidden_tests": ["*"]}, f"[0].hidden_tests: {json.dumps('*')} {PATH_BOUND}"),
        ({"hidden_tests": ["t/*.py"]}, f"[0].hidden_tests: {json.dumps('t/*.py')} {PATH_BOUND}"),
        ({"hidden_tests": ["t/?.py"]}, f"[0].hidden_tests: {json.dumps('t/?.py')} {PATH_BOUND}"),
        (
            {"hidden_tests": ["t/[ab].py"]},
            f"[0].hidden_tests: {json.dumps('t/[ab].py')} {PATH_BOUND}",
        ),
        ({"hidden_tests": [":(top)"]}, f"[0].hidden_tests: {json.dumps(':(top)')} {PATH_BOUND}"),
        ({"hidden_tests": [":!x"]}, f"[0].hidden_tests: {json.dumps(':!x')} {PATH_BOUND}"),
        ({"hidden_tests": ["t/"]}, f"[0].hidden_tests: {json.dumps('t/')} {PATH_BOUND}"),
        ({"hidden_tests": ["a//b"]}, f"[0].hidden_tests: {json.dumps('a//b')} {PATH_BOUND}"),
        ({"hidden_tests": ["./t.py"]}, f"[0].hidden_tests: {json.dumps('./t.py')} {PATH_BOUND}"),
        ({"hidden_tests": ["a/."]}, f"[0].hidden_tests: {json.dumps('a/.')} {PATH_BOUND}"),
        ({"hidden_tests": ["a/./b"]}, f"[0].hidden_tests: {json.dumps('a/./b')} {PATH_BOUND}"),
        ({"hidden_tests": ["a\nb"]}, f"[0].hidden_tests: {json.dumps('a\nb')} {PATH_BOUND}"),
        ({"hidden_tests": ["a\x7fb"]}, f"[0].hidden_tests: {json.dumps('a\x7fb')} {PATH_BOUND}"),
        ({"hidden_tests": [".git/x"]}, f"[0].hidden_tests: {json.dumps('.git/x')} {PATH_BOUND}"),
        (
            {"hidden_tests": ["t/.git/config"]},
            f"[0].hidden_tests: {json.dumps('t/.git/config')} {PATH_BOUND}",
        ),
        ({"hidden_tests": [".git"]}, f"[0].hidden_tests: {json.dumps('.git')} {PATH_BOUND}"),
        (
            {"hidden_tests": ["t\\est.py"]},
            f"[0].hidden_tests: {json.dumps('t\\est.py')} {PATH_BOUND}",
        ),
        (
            {"hidden_tests": [".GIT/config"]},
            f"[0].hidden_tests: {json.dumps('.GIT/config')} {PATH_BOUND}",
        ),
        (
            {"hidden_tests": ["a\ud800b"]},
            f"[0].hidden_tests: {json.dumps('a\ud800b')} {PATH_BOUND}",
        ),
        (
            {"hidden_tests": ["a\u200cb"]},
            f"[0].hidden_tests: {json.dumps('a\u200cb')} {PATH_BOUND}",
        ),
        ({"test_cmd": []}, f"[0].test_cmd: {TEST_CMD_BOUND}"),
        ({"test_cmd": ["x"] * 33}, f"[0].test_cmd: {TEST_CMD_BOUND}"),
        ({"test_cmd": ["python3", ""]}, f"[0].test_cmd: {TEST_CMD_BOUND}"),
        ({"test_cmd": ["python3\x00"]}, f"[0].test_cmd: {NUL}"),
        ({"test_cmd": ["python3", "x" * 1025]}, f"[0].test_cmd: {TEST_CMD_BOUND}"),
        ({"setup_cmd": "x" * 4097}, f"[0].setup_cmd: {SETUP_BOUND}"),
        ({"setup_cmd": "echo\x00"}, f"[0].setup_cmd: {NUL}"),
        ({"env": {f"K{n}": "v" for n in range(33)}}, f"[0].env: {ENV_COUNT}"),
        ({"env": {"1A": "v"}}, '[0].env: key "1A" must match [A-Za-z_][A-Za-z0-9_]*'),
        ({"env": {"A-B": "v"}}, '[0].env: key "A-B" must match [A-Za-z_][A-Za-z0-9_]*'),
        ({"env": {"": "v"}}, '[0].env: key "" must match [A-Za-z_][A-Za-z0-9_]*'),
        ({"env": {"A": None}}, f'[0].env: "A" {ENV_VALUE}'),
        ({"env": {"A": [1]}}, f'[0].env: "A" {ENV_VALUE}'),
        ({"env": {"A": "a\x00"}}, f"[0].env: {NUL}"),
    ],
)
def test_reports_problem_when_field_out_of_bounds(changes: dict[str, Any], expected: str) -> None:
    assert texts([a_case(**changes)]) == [expected]


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "x" * 64, "merge": "abcdef0"},
        {"id": "a.b_c-D9", "merge": SHA},
        {"prompt": "x" * 20_000, "setup_cmd": "x" * 4096},
        {"hidden_tests": ["t.py"] * 100, "test_cmd": ["x"] * 32},
        {"hidden_tests": ["a" * 1024, "t..py", "a/.../b", "a/-b", ".github/t.py", "a/.gitx"]},
        {"test_cmd": ["python3", "x" * 1024]},
        {"env": {f"_K{n}": n for n in range(32)}},
        {"setup_cmd": "", "excluded": False},
    ],
)
def test_accepts_case_when_field_at_bound(changes: dict[str, Any]) -> None:
    assert texts([a_case(**changes)]) == []


def test_reports_duplicate_when_ids_repeat() -> None:
    cases: list[JsonValue] = [a_case(), a_case(id="T2"), a_case(), a_case(id="T2", excluded=True)]

    assert texts(cases) == ['[2].id: duplicate id "T1"', '[3].id: duplicate id "T2"']


def test_reports_duplicate_when_ids_differ_only_in_case() -> None:
    """An id is a worktree path part, and macOS folders ignore case."""
    cases: list[JsonValue] = [a_case(id="Fix-1"), a_case(id="fix-1"), a_case(id="FIX-1")]

    assert texts(cases) == ['[1].id: duplicate id "fix-1"', '[2].id: duplicate id "FIX-1"']


def test_reports_unknown_repo_when_case_not_excluded() -> None:
    cases: list[JsonValue] = [a_case(repo="zz"), a_case(id="T2", repo="web")]

    problems = case_problems(cases, repos=REPOS)

    assert problems == [CaseProblem(index=0, key="repo", message='"zz" is not in repos (api, web)')]
    assert [problem.text for problem in problems] == ['[0].repo: "zz" is not in repos (api, web)']


def test_skips_repo_check_when_case_excluded() -> None:
    assert texts([a_case(repo="gone", excluded=True)]) == []


def test_reports_each_problem_in_order_when_case_has_several() -> None:
    case = a_case(id="", repo="zz", merge=None, env={"1": "x"})
    del case["prompt"]

    assert texts([a_case(), case, 7]) == [
        f"[1].id: {ID_BOUND}",
        "[1].merge: must be a string",
        "[1].prompt: is missing",
        '[1].env: key "1" must match [A-Za-z_][A-Za-z0-9_]*',
        '[1].repo: "zz" is not in repos (api, web)',
        "[2]: must be an object",
    ]


def test_reads_empty_list_as_clean_when_file_holds_none() -> None:
    cases = read_cases(b"[]\n")

    assert cases == []
    assert case_problems([], repos=REPOS) == []
    assert bench_cases([]) == ()
    assert unknown_repo_line([], repos=REPOS) is None


def test_reads_cases_when_document_is_list() -> None:
    assert read_cases(b'[{"id": "T1"}, 1]') == [{"id": "T1"}, 1]
    assert read_cases(b"[" + b",".join([b"{}"] * 200) + b"]") == [{}] * 200
    assert read_cases(b" " * (MAX_CASES_BYTES - 2) + b"[]") == []


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b'{"id": "T1"}', "the top level must be a list of cases"),
        (b"null", "the top level must be a list of cases"),
        (b"[" + b",".join([b"{}"] * 201) + b"]", "more than 200 cases"),
        (b'[{"id": "T1", "id": "T2"}]', 'not valid JSON here: the key "id" appears more than once'),
        (b'[{"env": {"A": NaN}}]', "not valid JSON here: NaN is not a JSON number"),
        (b"[", "not valid JSON: Expecting value at line 1 column 2"),
        (b"\xff[]", "not UTF-8 text: byte 0 cannot be decoded"),
        (b" " * (MAX_CASES_BYTES - 1) + b"[]", "larger than 1048576 bytes"),
    ],
    ids=["object", "null", "too-many", "repeated-key", "nan", "syntax", "not-utf8", "too-large"],
)
def test_rejects_document_when_not_list_or_not_strict_json(content: bytes, expected: str) -> None:
    assert read_cases(content) == expected


def test_formats_script_line_when_repos_unknown() -> None:
    cases: list[JsonValue] = [
        {"id": "T1", "repo": "zz"},
        {"id": "T2", "repo": "nope"},
        {"id": "T3", "repo": "zz"},
        {"id": "T4"},
        {"id": "T5", "repo": "api"},
        {"id": "T6", "repo": "gone", "excluded": True},
        "not a case",
    ]

    line = unknown_repo_line(cases, repos=["web", "api", "web"])

    assert line == (
        "ERROR bench: case repo(s) ['None', 'nope', 'zz'] not in hub.json repos ['api', 'web']"
    )


def test_gives_no_line_when_every_case_repo_known_or_excluded() -> None:
    cases: list[JsonValue] = [a_case(), a_case(id="T2", repo="web"), a_case(repo="x", excluded=1)]

    assert unknown_repo_line(cases, repos=REPOS) is None


@pytest.mark.parametrize(
    "case", ["T1", without("merge"), a_case(env=None)], ids=["text", "no-merge", "env-null"]
)
def test_raises_value_error_when_case_not_checked_first(case: JsonValue) -> None:
    with pytest.raises(ValueError, match="merge|object|env"):
        bench_cases([case])
