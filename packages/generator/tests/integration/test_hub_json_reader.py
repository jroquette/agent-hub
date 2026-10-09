"""The hooks' ``hub.json`` reader, as rendered at ``plugin/hub-workflow/hooks/stdlib_reader.py``.

Every read runs in a child, on ``hook_python`` (this interpreter and a real 3.9): the child loads
the rendered reader, prints ``dataclasses.asdict`` of what it read as JSON, and evaluates the
equality checks it is given with the reader's own classes. Those checks stay in the child because
dataclass equality holds only between classes of one loaded module, and a tuple is not a list.
"""

import ast
import importlib.util
import json
import os
import re
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.local_config import LOCAL_FILE, LOCAL_FILE_MAX_BYTES
from agent_hub.core.hub_config.model import (
    Doctor,
    Guard,
    GuardInfra,
    HubConfig,
    Platform,
    Project,
    Repo,
    Tracker,
)
from agent_hub.core.testing.builders import a_conventions_document, a_hub_document, a_second_repo
from agent_hub.core.testing.platform_repository_cases import REPOSITORY_CASES, RepositoryCase
from agent_hub.generator.render_hub import render_hub

READER = "plugin/hub-workflow/hooks/stdlib_reader.py"

# The optional fields of AC-1.5, as paths into the JSON document.
OPTIONAL_PATHS: tuple[tuple[str | int, ...], ...] = (
    ("project", "default_branch"),
    ("tracker", "ready_label"),
    ("tracker", "failed_label"),
    ("tracker", "transport"),
    ("repos", 0, "role"),
    ("guard", "ask_before_edit"),
    ("guard", "deny_hosts"),
    ("guard", "deny_paths"),
    ("modules",),
    ("doctor", "rules"),
)

# Optional keys with no model default: absent means the value is inherited, so the reader's
# effective value is compared with ``HubConfig.default_branch_for``, not with the model dump.
INHERITED_PATHS: tuple[tuple[str | int, ...], ...] = (("repos", 0, "default_branch"),)

# Optional keys resolved per developer (hub.local.json, else hub.json, else git config): the
# CLI and the hooks resolve them alike, which the shared identity cases check.
LOCAL_PATHS: tuple[tuple[str | int, ...], ...] = (
    ("project", "branch_prefix"),
    ("project", "author_name"),
    ("project", "author_email"),
)

# Either-or keys: compared through ``Tracker.team_keys``, not one by one
# (``test_matches_model_teams_when_document_valid``).
TEAM_PATHS: tuple[tuple[str | int, ...], ...] = (("tracker", "team"), ("tracker", "teams"))

# Keys no hook reads: the reader leaves them out, which ``test_reads_same_values_when_hub_sets_
# conventions`` checks.
IGNORED_PATHS: tuple[tuple[str | int, ...], ...] = (
    ("project", "conventions"),
    ("repos", 0, "conventions"),
)

# Read leniently by the hooks; absent is ``None`` in both; agreement is the shared cases'
# (``test_platform_repository_parity.py``).
PLATFORM_SOURCE_PATHS: tuple[tuple[str | int, ...], ...] = (("platform", "repository"),)

# The model gives ``None`` when absent; the reader gives the gate's own default (``""`` = no fast
# gate, ``None`` = ``TIMEOUT``): inherited-style, not compared with the model dump.
GATE_DEFAULT_PATHS: tuple[tuple[str | int, ...], ...] = (
    ("repos", 0, "check_fast"),
    ("repos", 0, "check_fast_timeout"),
)

# ``guard.infra`` and its lists: absent: ``None`` in both; present: compared by
# ``test_reads_infra_as_model_when_document_valid``.
INFRA_PATHS: tuple[tuple[str | int, ...], ...] = (
    ("guard", "infra"),
    ("guard", "infra", "allow"),
    ("guard", "infra", "prod_markers"),
)

# argv: mode, reader file, hub.json path, checks (JSON: name -> [actual, expected] expressions,
# evaluated with the reader's names and ``hub_file``). Modes: ``import`` (a sibling import, as the
# hooks do), ``by_path`` (the registration the reader's docstring asks for, as the scripts do),
# ``cwd_gone`` (``import``, after the child removes its own working directory). Prints what it
# read, each check's result, and whether the model or pydantic came along.
READ = """
import dataclasses, importlib.util, json, os
mode, reader_file, hub_json, checks = sys.argv[1:5]
if mode == "by_path":
    spec = importlib.util.spec_from_file_location("hub_stdlib_reader", reader_file)
    reader = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = reader
    spec.loader.exec_module(reader)
else:
    import stdlib_reader as reader
if mode == "cwd_gone":
    os.rmdir(os.getcwd())
hub_file = reader.load_hub_file(hub_json)
scope = dict(vars(reader), hub_file=hub_file)
heavy = ("pydantic", "agent_hub.core.hub_config.model")
print(json.dumps({
    "hub_file": dataclasses.asdict(hub_file),
    "equal": {
        name: eval(actual, scope) == eval(expected, scope)
        for name, (actual, expected) in json.loads(checks).items()
    },
    "imported": [name for name in heavy if name in sys.modules],
}))
"""


type Reader = Callable[..., Any]


@pytest.fixture
def reader_file(rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig) -> Path:
    """The reader in a rendered demo hub."""
    return rendered_hub(demo_config) / READER


@pytest.fixture
def read(reader_file: Path, run_python: Callable[..., Any]) -> Reader:
    """Run ``READ`` on an interpreter: what the rendered reader makes of a ``hub.json`` path."""

    def run(
        python: str,
        hub_json: Path | str,
        *,
        mode: str = "import",
        checks: Mapping[str, tuple[str, str]] | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> Any:
        args = [mode, str(reader_file), str(hub_json), json.dumps(checks or {})]
        limit = {} if timeout is None else {"timeout": timeout}
        return run_python(python, READ, path=reader_file.parent, args=args, cwd=cwd, **limit)

    return run


def write_hub_file(directory: Path, document: object) -> Path:
    path = directory / "hub.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def value_at(data: Any, path: tuple[str | int, ...]) -> Any:
    for segment in path:
        data = data[segment]
    return data


def a_minimal_document() -> dict[str, Any]:
    """Required keys only: no ``$schema``, ``guard``, ``modules``, ``doctor``, ``repos[].role``."""
    document = a_hub_document()
    for key in ("$schema", "guard", "modules"):
        del document[key]
    return document


def test_returns_version_when_three_numbers(tmp_path: Path, hook_python: str, read: Reader) -> None:
    path = write_hub_file(tmp_path, a_hub_document() | {"platform": {"version": "0.2.0"}})

    hub_file = read(hook_python, path)["hub_file"]

    assert hub_file["platform"]["version"] == "0.2.0"
    assert hub_file["schema_version"] == 1
    assert hub_file["project"]["name"] == "demo"
    assert [repo["dir"] for repo in hub_file["repos"]] == ["demo-api"]


@pytest.mark.parametrize("version", ["1.2", "v1.2.3", "0.2.0\n", "０.2.0", "", "1.2.3.4"])
def test_reports_version_absent_when_not_three_numbers(
    tmp_path: Path, *, hook_python: str, read: Reader, version: str
) -> None:
    path = write_hub_file(tmp_path, a_hub_document() | {"platform": {"version": version}})

    hub_file = read(hook_python, path)["hub_file"]

    assert hub_file["platform"]["version"] is None
    assert hub_file["project"]["name"] == "demo"


GOOD_REPOSITORIES = [case for case in REPOSITORY_CASES if case.is_valid]
BAD_REPOSITORIES = [case for case in REPOSITORY_CASES if not case.is_valid]


def with_repository(value: object) -> dict[str, Any]:
    document = a_hub_document()
    document["platform"]["repository"] = value
    return document


@pytest.mark.parametrize("case", GOOD_REPOSITORIES, ids=[case.name for case in GOOD_REPOSITORIES])
def test_reads_repository_when_value_good(
    tmp_path: Path, *, hook_python: str, read: Reader, case: RepositoryCase
) -> None:
    path = write_hub_file(tmp_path, with_repository(case.value))

    hub_file = read(hook_python, path)["hub_file"]

    assert hub_file["platform"] == {
        "version": "0.2.0",
        "repository": case.value,
        "has_bad_repository": False,
    }


@pytest.mark.parametrize("case", BAD_REPOSITORIES, ids=[case.name for case in BAD_REPOSITORIES])
def test_flags_bad_repository_when_value_bad(
    tmp_path: Path, *, hook_python: str, read: Reader, case: RepositoryCase
) -> None:
    path = write_hub_file(tmp_path, with_repository(case.value))

    hub_file = read(hook_python, path)["hub_file"]

    # Only that key is affected: the pin and the rest of the file are still read.
    assert hub_file["platform"] == {
        "version": "0.2.0",
        "repository": None,
        "has_bad_repository": True,
    }
    assert hub_file["project"]["name"] == "demo"
    assert [repo["dir"] for repo in hub_file["repos"]] == ["demo-api"]


def test_reads_no_repository_when_key_absent(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    path = write_hub_file(tmp_path, a_minimal_document())

    hub_file = read(hook_python, path)["hub_file"]

    assert hub_file["platform"] == {
        "version": "0.2.0",
        "repository": None,
        "has_bad_repository": False,
    }


def test_ignores_unknown_and_comment_keys_when_present(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    document = a_hub_document()
    document["_comment"] = "top"
    document["unknown"] = {"x": 1}
    document["project"]["_note"] = "p"
    document["project"]["extra"] = 1
    document["repos"][0]["_note"] = "r"
    document["modules"] = {"_comment": "m", "cloud": {"_note": "x", "region": "eu"}}
    document["doctor"] = {"_c": 1, "rules": {"_c": 2, "links.dead": {"_c": 3, "enabled": False}}}
    path = write_hub_file(tmp_path, document)

    reader = read(hook_python, path)["hub_file"]

    assert "unknown" not in reader
    assert "_comment" not in reader
    assert reader["project"]["name"] == "demo"
    assert "extra" not in reader["project"]
    assert "_note" not in reader["repos"][0]
    assert reader["modules"] == {"cloud": {"region": "eu"}}
    assert reader["doctor"] == {"rules": {"links.dead": {"enabled": False}}}


@pytest.mark.parametrize(
    "settings",
    [
        {"source": "demo-api", "target": "demo-web"},
        # What HubConfig rejects (a number, a dir not in repos, an extra key) is still read.
        {"source": 1, "target": "nope", "branch": "main"},
    ],
    ids=["valid", "invalid"],
)
def test_reads_contract_sync_settings_as_written_when_present(
    tmp_path: Path, *, hook_python: str, read: Reader, settings: dict[str, object]
) -> None:
    document = a_hub_document()
    document["repos"].append(a_second_repo())
    document["modules"]["contract-sync"] = {"_note": "api to web", **settings}
    path = write_hub_file(tmp_path, document)

    reader = read(hook_python, path)["hub_file"]

    assert reader["modules"] == {"cloud": {}, "bench": {}, "contract-sync": settings}
    assert [repo["dir"] for repo in reader["repos"]] == ["demo-api", "demo-web"]


def test_matches_schema_defaults_when_hub_json_minimal(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    document = a_minimal_document()
    path = write_hub_file(tmp_path, document)

    model = HubConfig.model_validate(document).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    reader = read(hook_python, path)["hub_file"]

    for path_in_document in OPTIONAL_PATHS:
        assert value_at(reader, path_in_document) == value_at(model, path_in_document), (
            path_in_document
        )


def test_lists_every_optional_field_when_model_inspected() -> None:
    """``OPTIONAL_PATHS``, ``INHERITED_PATHS``, ``LOCAL_PATHS``, ``TEAM_PATHS``,
    ``IGNORED_PATHS``, ``PLATFORM_SOURCE_PATHS`` and ``GATE_DEFAULT_PATHS`` (seven tuples) list
    every optional key: a new one fails here."""
    owners: tuple[tuple[tuple[str | int, ...], type[Any]], ...] = (
        ((), HubConfig),
        (("platform",), Platform),
        (("project",), Project),
        (("tracker",), Tracker),
        (("repos", 0), Repo),
        (("guard",), Guard),
        (("guard", "infra"), GuardInfra),
        (("doctor",), Doctor),
    )
    defaulted = {
        (*prefix, field.alias or name)
        for prefix, model in owners
        for name, field in model.model_fields.items()
        if not field.is_required()
    }
    # ``$schema`` is an editor hint, not a default; ``guard`` and ``doctor`` are listed per field.
    containers = {("$schema",), ("guard",), ("doctor",)}

    # ``INFRA_PATHS`` is the eighth tuple.
    assert defaulted - containers == (
        set(OPTIONAL_PATHS)
        | set(INHERITED_PATHS)
        | set(LOCAL_PATHS)
        | set(TEAM_PATHS)
        | set(IGNORED_PATHS)
        | set(PLATFORM_SOURCE_PATHS)
        | set(GATE_DEFAULT_PATHS)
        | set(INFRA_PATHS)
    )


def test_reads_gate_defaults_when_check_keys_absent(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    document = a_minimal_document()
    del document["repos"][0]["check_fast"]
    path = write_hub_file(tmp_path, document)

    model = HubConfig.model_validate(document).repos[0]
    [repo] = read(hook_python, path)["hub_file"]["repos"]

    assert (model.check_fast, model.check_fast_timeout) == (None, None)
    assert repo["check_fast"] == ""
    assert repo["check_fast_timeout"] is None
    assert repo["check"] == "make check"


def with_check_fast_timeout(value: object) -> dict[str, Any]:
    document = a_hub_document()
    document["repos"][0]["check_fast_timeout"] = value
    return document


@pytest.mark.parametrize("timeout", [1, 150, 160])
def test_reads_check_fast_timeout_when_value_in_range(
    tmp_path: Path, *, hook_python: str, read: Reader, timeout: int
) -> None:
    path = write_hub_file(tmp_path, with_check_fast_timeout(timeout))

    [repo] = read(hook_python, path)["hub_file"]["repos"]

    assert repo["check_fast_timeout"] == timeout


@pytest.mark.parametrize("timeout", [0, 161, 1.5, 150.0, "10", True, None, -1])
def test_treats_check_fast_timeout_absent_when_value_bad(
    tmp_path: Path, *, hook_python: str, read: Reader, timeout: object
) -> None:
    path = write_hub_file(tmp_path, with_check_fast_timeout(timeout))

    [repo] = read(hook_python, path)["hub_file"]["repos"]

    # Only that key is affected: the rest of the repo entry is still read.
    assert repo["check_fast_timeout"] is None
    assert repo["dir"] == "demo-api"
    assert repo["check_fast"] == "make check-fast"
    assert repo["check"] == "make check"


def test_reads_same_values_when_hub_sets_conventions(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    document = a_conventions_document()
    plain = a_conventions_document()
    del plain["project"]["conventions"]
    del plain["repos"][0]["conventions"]
    for name in ("mixed", "plain"):
        (tmp_path / name).mkdir()

    with_conventions = read(hook_python, write_hub_file(tmp_path / "mixed", document))
    without = read(hook_python, write_hub_file(tmp_path / "plain", plain))

    assert with_conventions["hub_file"] == without["hub_file"]


def repo_branches(hub_file: Mapping[str, Any]) -> dict[str, str]:
    return {repo["dir"]: repo["default_branch"] for repo in hub_file["repos"]}


@pytest.mark.parametrize("branch", ["master", "release/2", "v1.0"])
def test_reads_repo_branch_when_value_matches_pattern(
    tmp_path: Path, *, hook_python: str, read: Reader, branch: str
) -> None:
    document = a_hub_document()
    document["project"]["default_branch"] = "trunk"
    document["repos"][0]["default_branch"] = branch
    document["repos"].append(a_second_repo())
    path = write_hub_file(tmp_path, document)

    hub_file = read(hook_python, path)["hub_file"]

    assert repo_branches(hub_file) == {"demo-api": branch, "demo-web": "trunk"}
    assert hub_file["project"]["default_branch"] == "trunk"


@pytest.mark.parametrize(
    ("project_branch", "branch", "expected"),
    [
        ("trunk", 7, "trunk"),
        ("trunk", "", "trunk"),
        ("trunk", "-x", "trunk"),
        ("trunk", "a..b", "trunk"),
        ("trunk", "main/", "trunk"),
        ("trunk", "a b", "trunk"),
        ("trunk", None, "trunk"),
        (None, "-x", "main"),
        ("trunk", "_" * 64 + "!", "trunk"),
    ],
    ids=[
        "int",
        "empty",
        "dash",
        "dots",
        "slash",
        "space",
        "null",
        "no-project-branch",
        "backtracking-bait",
    ],
)
def test_inherits_project_branch_when_repo_value_invalid(
    tmp_path: Path,
    *,
    hook_python: str,
    read: Reader,
    project_branch: str | None,
    branch: object,
    expected: str,
) -> None:
    document = a_hub_document()
    if project_branch is None:
        document["project"].pop("default_branch", None)
    else:
        document["project"]["default_branch"] = project_branch
    document["repos"][0]["default_branch"] = branch
    path = write_hub_file(tmp_path, document)

    # ``read`` fails the test when the child exits non-zero: the read never raises.
    hub_file = read(hook_python, path)["hub_file"]

    assert repo_branches(hub_file) == {"demo-api": expected}
    assert hub_file["repos"][0]["github"] == "acme/demo-api"
    assert hub_file["project"]["default_branch"] == expected


def a_project_trunk_document() -> dict[str, Any]:
    document = a_minimal_document()
    document["project"]["default_branch"] = "trunk"
    return document


def a_repo_master_document() -> dict[str, Any]:
    document = a_project_trunk_document()
    document["repos"][0]["default_branch"] = "master"
    document["repos"].append(a_second_repo())
    return document


def a_both_repos_set_document() -> dict[str, Any]:
    document = a_repo_master_document()
    document["repos"][1]["default_branch"] = "release/2"
    return document


@pytest.mark.parametrize(
    "make_document",
    [
        a_minimal_document,
        a_project_trunk_document,
        a_repo_master_document,
        a_both_repos_set_document,
    ],
    ids=["minimal", "project-trunk", "one-repo-set", "both-repos-set"],
)
def test_matches_model_branch_when_document_valid(
    tmp_path: Path,
    *,
    hook_python: str,
    read: Reader,
    make_document: Callable[[], dict[str, Any]],
) -> None:
    document = make_document()
    path = write_hub_file(tmp_path, document)

    config = HubConfig.model_validate(document)
    hub_file = read(hook_python, path)["hub_file"]

    assert repo_branches(hub_file) == {
        repo.dir: config.default_branch_for(repo.dir) for repo in config.repos
    }


def test_uses_model_branch_pattern_when_source_checked(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    pattern = Project.model_json_schema()["properties"]["default_branch"]["pattern"]
    assert pattern.startswith("^")
    assert pattern.endswith("$")
    path = write_hub_file(tmp_path, a_hub_document())

    checks = {"pattern": ("BRANCH_NAME.pattern", repr(pattern[1:-1]))}
    loaded = read(hook_python, path, checks=checks)

    assert loaded["equal"] == {"pattern": True}


def character_set(character_class: str) -> frozenset[str]:
    """The ASCII characters a ``[...]`` class matches."""
    return frozenset(
        character for character in map(chr, range(128)) if re.fullmatch(character_class, character)
    )


@pytest.mark.parametrize("pattern_name", ["BRANCH_NAME", "BRANCH_PREFIX"])
def test_keeps_separator_out_of_segment_when_branch_pattern_parsed(
    reader_file: Path, monkeypatch: pytest.MonkeyPatch, *, pattern_name: str
) -> None:
    """A separator character that is also a segment one makes ``re`` backtrack exponentially."""
    spec = importlib.util.spec_from_file_location("hub_stdlib_reader_pattern", reader_file)
    assert spec is not None
    assert spec.loader is not None
    reader = importlib.util.module_from_spec(spec)
    # The reader's dataclasses look their module up while the class is built.
    monkeypatch.setitem(sys.modules, spec.name, reader)
    spec.loader.exec_module(reader)
    classes = re.findall(r"(\[[^\]]+\])(\+?)", getattr(reader, pattern_name).pattern)
    segment = {cls for cls, repeated in classes if repeated}
    separator = {cls for cls, repeated in classes if not repeated}
    assert segment
    assert separator

    segment_characters = frozenset().union(*map(character_set, segment))
    separator_characters = frozenset().union(*map(character_set, separator))

    assert segment_characters & separator_characters == frozenset()


def write_invalid_utf8(path: Path) -> None:
    path.write_bytes(b'{"project": {"name": "\xff"}}')


def write_json_syntax_error(path: Path) -> None:
    path.write_text('{"project": ', encoding="utf-8")


def write_top_level_array(path: Path) -> None:
    path.write_text(json.dumps([a_hub_document()]), encoding="utf-8")


def write_deep_nesting(path: Path) -> None:
    path.write_text("[" * 100_000, encoding="utf-8")


def make_directory(path: Path) -> None:
    path.mkdir()


def leave_missing(path: Path) -> None:
    del path


@pytest.mark.parametrize(
    "make_hub_file",
    [
        leave_missing,
        make_directory,
        write_invalid_utf8,
        write_json_syntax_error,
        write_top_level_array,
        write_deep_nesting,
    ],
)
def test_returns_defaults_when_file_unreadable_or_malformed(
    tmp_path: Path,
    *,
    hook_python: str,
    read: Reader,
    make_hub_file: Callable[[Path], None],
) -> None:
    hub_dir = tmp_path / "demo-hub"
    hub_dir.mkdir()
    path = hub_dir / "hub.json"
    make_hub_file(path)

    checks = {"defaults": ("hub_file", "HubFile(project=ProjectSection(name='demo-hub'))")}
    loaded = read(hook_python, path, checks=checks)

    assert loaded["equal"] == {"defaults": True}, loaded["hub_file"]


def test_keeps_other_fields_when_one_field_has_wrong_type(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    document = a_hub_document()
    document["tracker"]["ready_label"] = 5
    document["guard"]["deny_hosts"] = ["example.com", 7]
    document["platform"]["version"] = 2
    document["modules"] = {"cloud": True, "bench": {}}
    path = write_hub_file(tmp_path, document)

    checks = {
        "ready_label": ("hub_file.tracker.ready_label", "TrackerSection().ready_label"),
        "deny_hosts": ("hub_file.guard.deny_hosts", "()"),
        "ask_before_edit": ("hub_file.guard.ask_before_edit", "('demo-api/docs/adr',)"),
    }
    loaded = read(hook_python, path, checks=checks)
    hub_file = loaded["hub_file"]

    assert hub_file["modules"] == {"bench": {}}
    assert loaded["equal"]["ready_label"] is True
    assert hub_file["tracker"]["team"] == "DEM"
    assert loaded["equal"]["deny_hosts"] is True
    assert loaded["equal"]["ask_before_edit"] is True
    assert hub_file["platform"]["version"] is None
    assert hub_file["schema_version"] == 1

    document["repos"] = {}
    document["schema_version"] = True
    path = write_hub_file(tmp_path, document)
    loaded = read(hook_python, path, checks={"repos": ("hub_file.repos", "()")})
    hub_file = loaded["hub_file"]

    assert loaded["equal"]["repos"] is True
    assert hub_file["schema_version"] is None
    assert hub_file["project"]["name"] == "demo"


@pytest.mark.parametrize("transport", ["api", "mcp"])
def test_reads_transport_when_value_known(
    tmp_path: Path, hook_python: str, read: Reader, *, transport: str
) -> None:
    document = a_hub_document()
    document["tracker"]["transport"] = transport
    path = write_hub_file(tmp_path, document)

    assert read(hook_python, path)["hub_file"]["tracker"]["transport"] == transport


@pytest.mark.parametrize(
    "transport", [5, None, True, ["mcp"], ""], ids=["int", "null", "bool", "list", "empty"]
)
def test_defaults_transport_when_value_wrong_type(
    tmp_path: Path, hook_python: str, read: Reader, *, transport: object
) -> None:
    document = a_hub_document()
    document["tracker"]["transport"] = transport
    path = write_hub_file(tmp_path, document)

    checks = {"transport": ("hub_file.tracker.transport", "TrackerSection().transport")}
    loaded = read(hook_python, path, checks=checks)

    assert loaded["equal"] == {"transport": True}
    assert loaded["hub_file"]["tracker"]["transport"] == "api"
    assert loaded["hub_file"]["tracker"]["team"] == "DEM"


def test_falls_back_when_required_keys_missing(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    hub_dir = tmp_path / "acme-hub"
    hub_dir.mkdir()
    document = {
        "project": {"name": "", "hub_repo": 3},
        "tracker": [],
        "repos": [{"github": "acme/a"}, {"dir": ""}, {"dir": 5}, "b", {"dir": "b"}],
    }
    path = write_hub_file(hub_dir, document)

    checks = {
        "project": ("hub_file.project", "ProjectSection(name='acme-hub', hub_repo='')"),
        "tracker": ("hub_file.tracker", "TrackerSection()"),
        "repos": ("hub_file.repos", "(RepoEntry(dir='b'),)"),
    }
    loaded = read(hook_python, path, checks=checks)
    hub_file = loaded["hub_file"]

    assert loaded["equal"]["project"] is True
    assert loaded["equal"]["tracker"] is True
    assert hub_file["tracker"]["team"] == ""
    assert loaded["equal"]["repos"] is True
    assert hub_file["schema_version"] is None


def a_tracker_document(tracker: Mapping[str, object]) -> dict[str, Any]:
    """``a_hub_document()`` with ``tracker`` in place of its team keys (``kind`` kept)."""
    document = a_hub_document()
    document["tracker"] = {"kind": "linear", **tracker}
    return document


@pytest.mark.parametrize(
    ("tracker", "team_keys", "team"),
    [
        ({"team": "AGH"}, ["AGH"], "AGH"),
        ({"teams": ["APP", "OPS"]}, ["APP", "OPS"], ""),
    ],
    ids=["team", "teams"],
)
def test_reads_team_keys_when_tracker_sets_either_key(
    tmp_path: Path,
    *,
    hook_python: str,
    read: Reader,
    tracker: dict[str, object],
    team_keys: list[str],
    team: str,
) -> None:
    path = write_hub_file(tmp_path, a_tracker_document(tracker))

    hub_file = read(hook_python, path)["hub_file"]

    assert hub_file["tracker"]["team_keys"] == team_keys
    assert hub_file["tracker"]["team"] == team


# E4 (owner O2): ``teams`` counts only as a non-empty list of non-empty strings; anything else is
# absent, so the reader falls back to ``team``, else to no team.
INVALID_TEAMS: tuple[object, ...] = ("APP", [], ["APP", 7], ["APP", ""], {}, None)


@pytest.mark.parametrize(
    "teams", INVALID_TEAMS, ids=["string", "empty", "non-string", "empty-key", "object", "null"]
)
@pytest.mark.parametrize(
    ("team", "team_keys"), [("AGH", ["AGH"]), (None, [])], ids=["team", "none"]
)
def test_falls_back_to_team_when_teams_value_invalid(
    tmp_path: Path,
    *,
    hook_python: str,
    read: Reader,
    teams: object,
    team: str | None,
    team_keys: list[str],
) -> None:
    tracker: dict[str, object] = {"teams": teams}
    if team is not None:
        tracker["team"] = team
    path = write_hub_file(tmp_path, a_tracker_document(tracker))

    # ``read`` fails the test when the child exits non-zero: the read never raises.
    hub_file = read(hook_python, path)["hub_file"]

    assert hub_file["tracker"]["team_keys"] == team_keys
    assert hub_file["project"]["name"] == "demo"


@pytest.mark.parametrize(
    "tracker",
    [{"team": "AGH"}, {"teams": ["APP", "OPS"]}, {"teams": ["AP", "APP", "app9"]}],
    ids=["team", "teams", "prefix-keys"],
)
def test_matches_model_teams_when_document_valid(
    tmp_path: Path, *, hook_python: str, read: Reader, tracker: dict[str, object]
) -> None:
    """The ``TEAM_PATHS`` pair: the reader's ``team_keys`` are the model's ``Tracker.team_keys``."""
    document = a_tracker_document(tracker)
    path = write_hub_file(tmp_path, document)

    config = HubConfig.model_validate(document)
    hub_file = read(hook_python, path)["hub_file"]

    assert hub_file["tracker"]["team_keys"] == list(config.tracker.team_keys)


def test_names_project_hub_when_directory_has_no_name(hook_python: str, read: Reader) -> None:
    hub_file = read(hook_python, "/hub.json")["hub_file"]

    assert hub_file["project"]["name"] == "hub"


def test_names_project_hub_when_working_directory_gone(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    # The child removes its own working directory, so a relative path cannot be resolved.
    gone = tmp_path / "gone"
    gone.mkdir()

    checks = {"defaults": ("hub_file", "HubFile()")}
    loaded = read(hook_python, "hub.json", mode="cwd_gone", checks=checks, cwd=gone)

    assert not gone.exists()
    assert loaded["equal"] == {"defaults": True}, loaded["hub_file"]


def make_fifo(path: Path) -> None:
    os.mkfifo(path)


def link_to_fifo(path: Path) -> None:
    fifo = path.with_name("hub.fifo")
    os.mkfifo(fifo)
    path.symlink_to(fifo)


@pytest.mark.parametrize("make_hub_file", [make_fifo, link_to_fifo])
def test_returns_defaults_when_path_not_regular_file(
    tmp_path: Path,
    *,
    hook_python: str,
    read: Reader,
    make_hub_file: Callable[[Path], None],
) -> None:
    hub_dir = tmp_path / "demo-hub"
    hub_dir.mkdir()
    path = hub_dir / "hub.json"
    make_hub_file(path)

    # Opening a FIFO with no writer blocks forever: the child's timeout shows the reader returned.
    checks = {"defaults": ("hub_file", "HubFile(project=ProjectSection(name='demo-hub'))")}
    loaded = read(hook_python, path, mode="by_path", checks=checks, timeout=10)

    assert loaded["equal"] == {"defaults": True}, loaded["hub_file"]


def test_parses_as_python39_when_source_checked(reader_file: Path) -> None:
    source = reader_file.read_text(encoding="utf-8")

    ast.parse(source, filename=str(reader_file), feature_version=(3, 9))


def test_imports_only_stdlib_when_source_checked(reader_file: Path) -> None:
    tree = ast.parse(reader_file.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import"
            imported.append(node.module or "")

    assert imported
    assert {name.split(".")[0] for name in imported} <= sys.stdlib_module_names


def test_loads_without_pydantic_when_imported_by_path(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    path = write_hub_file(tmp_path, a_minimal_document())

    loaded = read(hook_python, path, mode="by_path")

    assert loaded["imported"] == []
    assert loaded["hub_file"] == read(hook_python, path)["hub_file"]


def test_reads_same_values_when_run_on_python39(
    tmp_path: Path, python39: str, read: Reader
) -> None:
    document = a_hub_document()
    document["_comment"] = "x"
    document["doctor"] = {"rules": {"links.dead": {"enabled": False}}}
    valid = write_hub_file(tmp_path, document)
    malformed = tmp_path / "malformed" / "hub.json"
    malformed.parent.mkdir()
    malformed.write_text("[" * 100_000, encoding="utf-8")

    for path in (valid, malformed, tmp_path / "missing" / "hub.json"):
        loaded = read(python39, path, mode="by_path")

        assert loaded["imported"] == []
        assert loaded["hub_file"] == read(sys.executable, path)["hub_file"], path


# argv: the modules to import, as JSON. Prints the names that imported. A 3.10+ stdlib module, or
# a form 3.9 evaluates at import time (``X | None`` outside an annotation) fails here, where
# ``ast.parse`` and ruff at py39 cannot tell.
IMPORT_ALL = """
import importlib, json
names = json.loads(sys.argv[1])
print(json.dumps([importlib.import_module(name).__name__ for name in names]))
"""


def test_imports_every_rendered_module_when_run_on_python39(
    *,
    python39: str,
    demo_config: HubConfig,
    rendered_hub: Callable[[HubConfig], Path],
    run_python: Callable[..., Any],
) -> None:
    hub = rendered_hub(demo_config)
    # The scripts read hub.json when imported, found by walking up from the script.
    write_hub_file(hub, a_hub_document())
    folders: dict[str, list[str]] = {}
    for file in render_hub(demo_config).files:
        folder, _, name = file.path.rpartition("/")
        if name.endswith(".py"):
            folders.setdefault(folder, []).append(name.removesuffix(".py"))

    for folder, names in folders.items():
        imported = run_python(
            python39, IMPORT_ALL, path=hub / folder, args=[json.dumps(names)], cwd=hub
        )

        assert imported == names, folder
    assert set(folders) == {"plugin/demo/hooks", "plugin/hub-workflow/hooks", "scripts"}


# argv: hub.json path, hub.local.json path, git's answers (JSON: config key -> output), the values
# to ask (JSON list of ``ASKED`` names), and a race while the local file loads (``grown``,
# ``swapped`` or ``""``). Loads both files with the reader and resolves the asked values through
# ``EffectiveValues``, each twice (the second call must not run git again). Prints the local file,
# each asked value and the git keys asked in order.
LOCAL_READ = """
import dataclasses, json, os
import stdlib_reader as reader
hub_json, local_json, answers, ask, race = sys.argv[1:6]
answers = json.loads(answers)
real = (os.fstat, os.path.getsize, os.path.isfile)
if race == "grown":
    # Every size check sees one byte: the file grew after it was checked.
    os.fstat = lambda fd: os.stat_result(real[0](fd)[:6] + (1,) + real[0](fd)[7:10])
    os.path.getsize = lambda path: 1
elif race == "swapped":
    # Every regular-file check by path passes: a FIFO took the file's place after it.
    os.path.isfile = lambda path: True
asked = []
def git_value(key):
    asked.append(key)
    return answers.get(key, "")
local_file = reader.load_local_file(local_json)
os.fstat, os.path.getsize, os.path.isfile = real
values = reader.EffectiveValues(reader.load_hub_file(hub_json), local_file, git_value)
getters = {
    "project.branch_prefix": values.branch_prefix,
    "project.author_name": values.author_name,
    "project.author_email": values.author_email,
    "tracker.transport": lambda: values.transport,
    "prefix_source": values.prefix_source,
}
effective = {}
for name in json.loads(ask):
    effective[name] = getters[name]()
    assert getters[name]() == effective[name], name
print(json.dumps({
    "local_file": dataclasses.asdict(local_file),
    "effective": effective,
    "git": asked,
}))
"""

ASKED = (
    "project.branch_prefix",
    "project.author_name",
    "project.author_email",
    "tracker.transport",
    "prefix_source",
)
NO_LOCAL_FILE = {"branch_prefix": "", "author_name": "", "author_email": "", "transport": ""}
HUB_VALUES = {
    "project.branch_prefix": "jdoe/",
    "project.author_name": "Jane Doe",
    "project.author_email": "jane@example.com",
    "tracker.transport": "api",
    "prefix_source": "hub.json",
}
GIT_ANSWERS = {"user.name": "Jane Roe", "user.email": "jane.doe@example.com"}
IDENTITY_KEYS = ("branch_prefix", "author_name", "author_email")


type LocalReader = Callable[..., Any]


@pytest.fixture
def local_read(reader_file: Path, run_python: Callable[..., Any]) -> LocalReader:
    """Run ``LOCAL_READ`` on an interpreter: the local file and the effective values it gives."""

    def run(
        python: str,
        hub_json: Path,
        local_json: Path,
        *,
        git: Mapping[str, str] | None = None,
        ask: tuple[str, ...] = ASKED,
        race: str = "",
        timeout: float | None = None,
    ) -> Any:
        args = [
            str(hub_json),
            str(local_json),
            json.dumps(dict(git or {})),
            json.dumps(ask),
            race,
        ]
        limit = {} if timeout is None else {"timeout": timeout}
        return run_python(python, LOCAL_READ, path=reader_file.parent, args=args, **limit)

    return run


def a_team_document(**identity: str) -> dict[str, Any]:
    """``a_hub_document`` whose ``project`` sets only the identity keys given."""
    document = a_hub_document()
    for key in IDENTITY_KEYS:
        document["project"].pop(key)
    document["project"].update(identity)
    return document


def write_local_file(directory: Path, document: object) -> Path:
    path = directory / LOCAL_FILE
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def a_full_local_document() -> dict[str, Any]:
    return {
        "_note": "mine",
        "project": {
            "_note": "mine",
            "branch_prefix": "me/",
            "author_name": "Jane Roe",
            "author_email": "me@example.com",
        },
        "tracker": {"_note": "mine", "transport": "mcp"},
    }


FULL_LOCAL_FILE = {
    "branch_prefix": "me/",
    "author_name": "Jane Roe",
    "author_email": "me@example.com",
    "transport": "mcp",
}


def padded_local_text(size: int) -> str:
    """A valid local file setting ``branch_prefix`` to ``me/``, exactly ``size`` bytes long."""
    head, tail = '{"project": {"branch_prefix": "me/"}, "_note": "', '"}'
    return head + "x" * (size - len(head) - len(tail)) + tail


def test_reads_local_values_when_local_file_valid(
    tmp_path: Path, hook_python: str, local_read: LocalReader
) -> None:
    hub_json = write_hub_file(tmp_path, a_hub_document())
    local_json = write_local_file(tmp_path, a_full_local_document())

    loaded = local_read(hook_python, hub_json, local_json, git=GIT_ANSWERS)

    assert loaded["local_file"] == FULL_LOCAL_FILE
    assert loaded["effective"] == {
        "project.branch_prefix": "me/",
        "project.author_name": "Jane Roe",
        "project.author_email": "me@example.com",
        "tracker.transport": "mcp",
        "prefix_source": "hub.local.json",
    }
    assert loaded["git"] == []


def test_reads_local_file_when_size_at_cap(
    tmp_path: Path, hook_python: str, local_read: LocalReader
) -> None:
    hub_json = write_hub_file(tmp_path, a_hub_document())
    local_json = tmp_path / LOCAL_FILE
    local_json.write_text(padded_local_text(LOCAL_FILE_MAX_BYTES), encoding="utf-8")
    assert local_json.stat().st_size == LOCAL_FILE_MAX_BYTES

    loaded = local_read(hook_python, hub_json, local_json)

    assert loaded["local_file"] == NO_LOCAL_FILE | {"branch_prefix": "me/"}


def write_oversize(path: Path) -> None:
    path.write_text(padded_local_text(LOCAL_FILE_MAX_BYTES + 1), encoding="utf-8")


def write_local_invalid_utf8(path: Path) -> None:
    path.write_bytes(b'{"project": {"branch_prefix": "me/", "author_name": "\xff"}}')


def write_local_not_json(path: Path) -> None:
    path.write_text('{"project": {"branch_prefix": "me/"', encoding="utf-8")


def write_local_array(path: Path) -> None:
    path.write_text(json.dumps([a_full_local_document()]), encoding="utf-8")


def write_local_deep_nesting(path: Path) -> None:
    path.write_text('{"project": ' + "[" * 10_000, encoding="utf-8")


@pytest.mark.parametrize(
    "make_local_file",
    [
        leave_missing,
        write_local_not_json,
        write_local_array,
        make_fifo,
        make_directory,
        write_oversize,
        write_local_invalid_utf8,
        write_local_deep_nesting,
    ],
    ids=["missing", "not-json", "array", "fifo", "directory", "oversize", "bad-utf8", "deep"],
)
def test_ignores_local_file_when_unreadable(
    tmp_path: Path,
    *,
    hook_python: str,
    local_read: LocalReader,
    make_local_file: Callable[[Path], None],
) -> None:
    hub_json = write_hub_file(tmp_path, a_hub_document())
    local_json = tmp_path / LOCAL_FILE
    make_local_file(local_json)

    # ``local_read`` fails the test when the child exits non-zero, and a FIFO read would block
    # until the timeout: the read returned and never raised.
    loaded = local_read(hook_python, hub_json, local_json, git=GIT_ANSWERS, timeout=10)

    assert loaded["local_file"] == NO_LOCAL_FILE
    assert loaded["effective"] == HUB_VALUES
    assert loaded["git"] == []


@pytest.mark.parametrize(
    ("race", "make_local_file"), [("grown", write_oversize), ("swapped", make_fifo)]
)
def test_ignores_local_file_when_changed_after_check(
    tmp_path: Path,
    *,
    hook_python: str,
    local_read: LocalReader,
    race: str,
    make_local_file: Callable[[Path], None],
) -> None:
    hub_json = write_hub_file(tmp_path, a_hub_document())
    local_json = tmp_path / LOCAL_FILE
    make_local_file(local_json)

    # What was opened is what counts: a FIFO read would block until the timeout.
    loaded = local_read(hook_python, hub_json, local_json, race=race, timeout=10)

    assert loaded["local_file"] == NO_LOCAL_FILE
    assert loaded["effective"] == HUB_VALUES


@pytest.mark.parametrize(
    ("section", "key", "value", "local_field"),
    [
        ("project", "branch_prefix", 7, "branch_prefix"),
        ("project", "branch_prefix", "", "branch_prefix"),
        ("project", "branch_prefix", "-x/", "branch_prefix"),
        ("project", "branch_prefix", "me/\n", "branch_prefix"),
        ("project", "branch_prefix", None, "branch_prefix"),
        ("tracker", "transport", "ftp", "transport"),
        ("tracker", "transport", "MCP", "transport"),
        ("project", "author_email", "x", "author_email"),
        ("project", "author_email", "Jane <j@example.com>", "author_email"),
        ("project", "author_name", "", "author_name"),
        ("project", "author_name", "a\u0007", "author_name"),
        ("project", "author_name", ["Jane"], "author_name"),
        ("project", "author_name", "\ud800x", "author_name"),
    ],
    ids=[
        "prefix-int",
        "prefix-empty",
        "prefix-dash",
        "prefix-newline",
        "prefix-null",
        "transport-unknown",
        "transport-case",
        "email-no-at",
        "email-named",
        "name-empty",
        "name-control",
        "name-list",
        "name-lone-surrogate",
    ],
)
def test_skips_local_key_when_wrong_type_empty_or_off_pattern(
    tmp_path: Path,
    *,
    hook_python: str,
    local_read: LocalReader,
    section: str,
    key: str,
    value: object,
    local_field: str,
) -> None:
    document = a_full_local_document()
    document[section][key] = value
    hub_json = write_hub_file(tmp_path, a_hub_document())
    local_json = write_local_file(tmp_path, document)

    loaded = local_read(hook_python, hub_json, local_json, git=GIT_ANSWERS)

    assert loaded["local_file"] == FULL_LOCAL_FILE | {local_field: ""}
    path = f"{section}.{key}"
    expected = {
        "project.branch_prefix": "me/",
        "project.author_name": "Jane Roe",
        "project.author_email": "me@example.com",
        "tracker.transport": "mcp",
        "prefix_source": "hub.local.json",
    } | {path: HUB_VALUES[path]}
    if path == "project.branch_prefix":
        expected["prefix_source"] = "hub.json"
    assert loaded["effective"] == expected
    assert loaded["git"] == []


def test_ignores_unknown_local_keys_when_present(
    tmp_path: Path, hook_python: str, local_read: LocalReader
) -> None:
    document = {
        "_note": "mine",
        "guard": {"deny_paths": ["x"]},
        "repos": [{"dir": "x"}],
        "project": {"default_branch": "x", "name": "x", "branch_prefix": "me/"},
        "tracker": {"team": "X"},
    }
    hub_json = write_hub_file(tmp_path, a_hub_document())
    local_json = write_local_file(tmp_path, document)

    loaded = local_read(hook_python, hub_json, local_json)

    assert loaded["local_file"] == NO_LOCAL_FILE | {"branch_prefix": "me/"}
    assert loaded["effective"] == HUB_VALUES | {
        "project.branch_prefix": "me/",
        "prefix_source": "hub.local.json",
    }


def effective(prefix: str, name: str, email: str, *, source: str) -> dict[str, str]:
    """The asked values of a hub whose transport is the default."""
    return dict(zip(ASKED, (prefix, name, email, "api", source), strict=True))


@pytest.mark.parametrize(
    ("hub_identity", "local_project", "git", "expected", "git_asked"),
    [
        (
            dict(zip(IDENTITY_KEYS, ("jdoe/", "Jane Doe", "jane@example.com"), strict=True)),
            None,
            GIT_ANSWERS,
            effective("jdoe/", "Jane Doe", "jane@example.com", source="hub.json"),
            [],
        ),
        (
            dict(zip(IDENTITY_KEYS, ("jdoe/", "Jane Doe", "jane@example.com"), strict=True)),
            {"author_email": "me@example.com"},
            GIT_ANSWERS,
            effective("jdoe/", "Jane Doe", "me@example.com", source="hub.json"),
            [],
        ),
        (
            {},
            None,
            GIT_ANSWERS,
            effective("jane.doe/", "Jane Roe", "jane.doe@example.com", source="derived"),
            ["user.email", "user.name"],
        ),
        (
            {},
            {"author_email": "me@example.com"},
            GIT_ANSWERS,
            effective("me/", "Jane Roe", "me@example.com", source="derived"),
            ["user.name"],
        ),
        (
            {"author_email": "jane@example.com"},
            None,
            GIT_ANSWERS,
            effective("jane/", "Jane Roe", "jane@example.com", source="derived"),
            ["user.name"],
        ),
        (
            {"author_name": "Jane Doe"},
            None,
            GIT_ANSWERS,
            effective("jane.doe/", "Jane Doe", "jane.doe@example.com", source="derived"),
            ["user.email"],
        ),
        (
            {},
            {"branch_prefix": "me/"},
            GIT_ANSWERS,
            effective("me/", "Jane Roe", "jane.doe@example.com", source="hub.local.json"),
            ["user.name", "user.email"],
        ),
        (
            {},
            None,
            {"user.name": "Jane Roe", "user.email": "j+x@example.com"},
            effective("", "Jane Roe", "j+x@example.com", source=""),
            ["user.email", "user.name"],
        ),
        (
            {},
            None,
            {"user.email": ".a@example.com"},
            effective("", "", ".a@example.com", source=""),
            ["user.email", "user.name"],
        ),
        (
            {},
            None,
            {"user.email": "jé@example.com"},
            effective("", "", "", source=""),
            ["user.email", "user.name"],
        ),
        (
            {},
            None,
            {"user.name": "Jane\u0007", "user.email": "Jane <jane@example.com>"},
            effective("", "", "", source=""),
            ["user.email", "user.name"],
        ),
        (
            {},
            None,
            {"user.name": "Jane Roe ", "user.email": "jane.doe@example.com "},
            effective("", "Jane Roe ", "", source=""),
            ["user.email", "user.name"],
        ),
        (
            {},
            None,
            {"user.name": "Jane \ud800", "user.email": "jane.doe@example.com"},
            effective("jane.doe/", "", "jane.doe@example.com", source="derived"),
            ["user.email", "user.name"],
        ),
        (
            {},
            None,
            {"user.name": "Jane Roe\n", "user.email": "jane.doe@example.com\n"},
            effective("jane.doe/", "Jane Roe", "jane.doe@example.com", source="derived"),
            ["user.email", "user.name"],
        ),
        (
            {},
            None,
            {"user.name": "Jane Roe\n\n", "user.email": "jane.doe@example.com\n\n"},
            effective("", "", "", source=""),
            ["user.email", "user.name"],
        ),
        (
            {},
            None,
            {},
            effective("", "", "", source=""),
            ["user.email", "user.name"],
        ),
    ],
    ids=[
        "hub-sets-all",
        "local-email-keeps-hub-prefix",
        "team-git",
        "team-local-email-derives",
        "team-hub-email-derives",
        "team-mixed",
        "team-local-prefix",
        "derived-plus",
        "derived-leading-dot",
        "git-email-non-ascii",
        "git-bad-shape",
        "git-spaced",
        "git-name-lone-surrogate",
        "git-one-newline",
        "git-two-newlines",
        "team-no-source",
    ],
)
def test_resolves_effective_values_when_git_answers(
    tmp_path: Path,
    *,
    hook_python: str,
    local_read: LocalReader,
    hub_identity: dict[str, str],
    local_project: dict[str, str] | None,
    git: dict[str, str],
    expected: dict[str, str],
    git_asked: list[str],
) -> None:
    hub_json = write_hub_file(tmp_path, a_team_document(**hub_identity))
    local_json = tmp_path / LOCAL_FILE
    if local_project is not None:
        write_local_file(tmp_path, {"project": local_project})

    loaded = local_read(hook_python, hub_json, local_json, git=git)

    assert loaded["effective"] == expected
    assert loaded["git"] == git_asked


@pytest.mark.parametrize(
    ("hub_identity", "git_asked"),
    [
        ({"branch_prefix": "jdoe/"}, []),
        ({"author_email": "jane@example.com"}, []),
        ({"author_name": "Jane Doe"}, ["user.email"]),
    ],
    ids=["hub-prefix", "hub-email", "team"],
)
def test_asks_git_email_only_when_prefix_needs_it(
    tmp_path: Path,
    *,
    hook_python: str,
    local_read: LocalReader,
    hub_identity: dict[str, str],
    git_asked: list[str],
) -> None:
    hub_json = write_hub_file(tmp_path, a_team_document(**hub_identity))

    ask = ("project.branch_prefix", "prefix_source")
    loaded = local_read(hook_python, hub_json, tmp_path / LOCAL_FILE, git=GIT_ANSWERS, ask=ask)

    assert loaded["git"] == git_asked


def test_uses_model_patterns_when_source_checked(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    properties = Project.model_json_schema()["properties"]
    patterns = {
        "BRANCH_PREFIX": properties["branch_prefix"]["pattern"],
        "EMAIL_ADDRESS": properties["author_email"]["pattern"],
        "FREE_STRING": properties["author_name"]["pattern"],
    }
    assert all(p.startswith("^") and p.endswith("$") for p in patterns.values())
    path = write_hub_file(tmp_path, a_hub_document())

    checks = {name: (f"{name}.pattern", repr(p[1:-1])) for name, p in patterns.items()}
    loaded = read(hook_python, path, checks=checks)

    assert loaded["equal"] == dict.fromkeys(patterns, True)


def test_uses_model_timeout_bounds_when_source_checked(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    timeout = Repo.model_json_schema()["properties"]["check_fast_timeout"]
    bounds = {
        "CHECK_FAST_TIMEOUT_MIN": timeout["minimum"],
        "CHECK_FAST_TIMEOUT_MAX": timeout["maximum"],
    }
    path = write_hub_file(tmp_path, a_hub_document())

    checks = {name: (name, repr(value)) for name, value in bounds.items()}
    loaded = read(hook_python, path, checks=checks)

    assert loaded["equal"] == dict.fromkeys(bounds, True)


def test_uses_core_local_file_when_source_checked(
    tmp_path: Path, hook_python: str, read: Reader
) -> None:
    path = write_hub_file(tmp_path, a_hub_document())

    checks = {
        "name": ("LOCAL_FILE", repr(LOCAL_FILE)),
        "cap": ("LOCAL_FILE_MAX_BYTES", repr(LOCAL_FILE_MAX_BYTES)),
    }
    loaded = read(hook_python, path, checks=checks)

    assert loaded["equal"] == {"name": True, "cap": True}


def test_keeps_linear_time_when_prefix_hostile(
    tmp_path: Path, hook_python: str, local_read: LocalReader
) -> None:
    """Backtracking bait gets its exact result; the pattern's shape, not a clock, proves it linear
    (``test_keeps_separator_out_of_segment_when_branch_pattern_parsed``)."""
    hub_json = write_hub_file(tmp_path, a_team_document())
    local_json = write_local_file(tmp_path, {"project": {"branch_prefix": "_" * 40 + "!/"}})
    git = {"user.email": "_" * 40 + "%@example.com"}

    loaded = local_read(hook_python, hub_json, local_json, git=git)

    assert loaded["local_file"] == NO_LOCAL_FILE
    assert loaded["effective"]["project.branch_prefix"] == ""
    assert loaded["effective"]["project.author_email"] == "_" * 40 + "%@example.com"
    assert loaded["effective"]["prefix_source"] == ""
