"""Workflow fixtures read from packs and run in memory (AC-213.11), and the engine's acceptance
suite: every sample pack under ``packages/core/tests/data/workflows`` (one per feature: joins and
trigger rules, ``when``, loops, output contracts) with each of its fixtures passing.

TESTING.md: synthetic trees only, written under ``tmp_path``; the sample packs are checked in.
"""

from pathlib import Path

import pytest

from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.dry_run import placeholder
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow
from agent_hub.generator.workflow_discovery import discover_workflows
from agent_hub.generator.workflow_fixtures import (
    MAX_PACK_FIXTURES,
    FixtureFile,
    FixtureRun,
    pack_fixtures,
    run_fixtures,
    skeleton_yaml,
)
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs
from agent_hub.generator.workflow_yaml import WorkflowFileError, load_workflow_bytes

SAMPLES = Path(__file__).parents[3] / "core" / "tests" / "data"
SAMPLE_PACKS = ("conditions", "contracts", "includes", "joins", "loops")
WORKFLOW = (
    "version: 1\nname: demo\nrevision: 1\nnodes:\n  - id: a\n    type: shell\n    command: [make]\n"
)
PASSING = "workflow: demo\nstubs: {a: {text: ok}}\nexpect: {status: done}\nreached: [a]\n"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    write(tmp_path / "workflows" / "pack" / "demo.yaml", WORKFLOW)
    return tmp_path


def runs_of(hub: Path, *, only: str | None = None) -> dict[str, FixtureRun]:
    found = discover_workflows(hub, builtin_root=hub / "no-builtins")
    return {run.path.name: run for run in run_fixtures(found, only=only)}


def test_reads_each_yaml_fixture_by_name_when_the_pack_has_a_fixtures_folder(hub: Path) -> None:
    pack = hub / "workflows" / "pack"
    write(pack / "fixtures" / "b.yaml", PASSING)
    write(pack / "fixtures" / "a.yaml", "workflow: demo\n")
    write(pack / "fixtures" / "notes.md", "not a fixture")
    write(pack / "fixtures" / ".hidden.yaml", PASSING)

    found = pack_fixtures(pack)

    assert [item.path.name for item in found if isinstance(item, FixtureFile)] == [
        "a.yaml",
        "b.yaml",
    ]
    assert found[0].document == {"workflow": "demo"}  # type: ignore[union-attr]


def test_reads_no_fixture_when_the_pack_has_no_fixtures_folder(hub: Path) -> None:
    assert pack_fixtures(hub / "workflows" / "pack") == ()


def test_refuses_the_file_when_it_links_out_of_its_pack(hub: Path, tmp_path: Path) -> None:
    outside = write(tmp_path / "outside.yaml", PASSING)
    link = hub / "workflows" / "pack" / "fixtures" / "linked.yaml"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)

    [refused] = pack_fixtures(hub / "workflows" / "pack")

    assert isinstance(refused, WorkflowFileError)
    assert "leaves its pack" in refused.reason


def test_passes_the_fixture_when_the_run_matches_it(hub: Path) -> None:
    write(hub / "workflows" / "pack" / "fixtures" / "ok.yaml", PASSING)

    assert runs_of(hub)["ok.yaml"].problems == ()


def test_fails_with_line_and_key_when_a_fixture_does_not_parse(hub: Path) -> None:
    write(hub / "workflows" / "pack" / "fixtures" / "bad.yaml", PASSING + "extra: 1\n")

    assert runs_of(hub)["bad.yaml"].problems == ("line 5: extra: unknown key",)


def test_fails_the_fixture_when_the_file_does_not_load(hub: Path) -> None:
    write(hub / "workflows" / "pack" / "fixtures" / "dup.yaml", "workflow: a\nworkflow: b\n")

    [problem] = runs_of(hub)["dup.yaml"].problems

    assert problem.startswith("line 2: ")


def test_fails_the_fixture_when_its_workflow_is_not_in_the_pack(hub: Path) -> None:
    write(hub / "workflows" / "pack" / "fixtures" / "x.yaml", PASSING.replace("demo", "ghost"))

    assert runs_of(hub)["x.yaml"].problems == ("workflow: no workflow named 'ghost' in this pack",)


def test_runs_only_the_named_workflow_fixtures_when_a_name_is_given(hub: Path) -> None:
    write(hub / "workflows" / "pack" / "fixtures" / "ok.yaml", PASSING)
    write(hub / "workflows" / "pack" / "fixtures" / "x.yaml", PASSING.replace("demo", "ghost"))

    assert list(runs_of(hub, only="demo")) == ["ok.yaml"]


def test_skips_builtin_fixtures_when_the_hub_overrides_their_workflow(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    write(builtin / "pack" / "demo.yaml", WORKFLOW)
    write(builtin / "pack" / "fixtures" / "old.yaml", PASSING.replace("ok}", "old}"))
    write(tmp_path / "hub" / "workflows" / "mine" / "demo.yaml", WORKFLOW)
    write(tmp_path / "hub" / "workflows" / "mine" / "fixtures" / "new.yaml", PASSING)

    found = discover_workflows(tmp_path / "hub", builtin_root=builtin)

    assert [run.path.name for run in run_fixtures(found)] == ["new.yaml"]


def test_writes_yaml_that_loads_and_passes_when_a_skeleton_is_asked(hub: Path) -> None:
    plan = plan_workflow(
        parse_workflow(load_workflow_bytes(WORKFLOW.encode(), source="w").document)
    )
    write(hub / "workflows" / "pack" / "fixtures" / "demo.yaml", skeleton_yaml(plan).text)

    assert runs_of(hub)["demo.yaml"].problems == ()


def test_finds_every_sample_pack_when_the_suite_is_discovered() -> None:
    found = discover_workflows(SAMPLES, builtin_root=SAMPLES / "no-builtins")
    runs = run_fixtures(found)

    assert found.problems == ()
    assert sorted({workflow.pack for workflow in found.workflows}) == list(SAMPLE_PACKS)
    assert {run.path.parent.parent.name for run in runs} == set(SAMPLE_PACKS)


@pytest.mark.parametrize(
    "fixture",
    sorted(SAMPLES.glob("workflows/*/fixtures/*.yaml")),
    ids=lambda path: f"{path.parent.parent.name}/{path.stem}",
)
def test_passes_without_warnings_when_a_sample_fixture_runs_through_the_engine(
    fixture: Path,
) -> None:
    found = discover_workflows(SAMPLES, builtin_root=SAMPLES / "no-builtins")
    [run] = [run for run in run_fixtures(found) if run.path == fixture]

    assert (run.problems, run.warnings) == ((), ())


def plan_of(text: str) -> WorkflowPlan:
    return plan_workflow(parse_workflow(load_workflow_bytes(text.encode(), source="w").document))


def test_fails_the_fixture_when_its_workflow_is_not_text(hub: Path) -> None:
    write(hub / "workflows" / "pack" / "fixtures" / "list.yaml", "workflow: [demo]\n")
    write(hub / "workflows" / "pack" / "fixtures" / "map.yaml", "workflow: {a: 1}\n")

    runs = runs_of(hub)

    assert runs["list.yaml"].problems[0] == "line 1: workflow: Input should be a valid string"
    assert runs["map.yaml"].problems[0] == "line 1: workflow: Input should be a valid string"


def test_reads_no_more_files_when_the_pack_is_past_the_fixture_cap(hub: Path) -> None:
    folder = hub / "workflows" / "pack" / "fixtures"
    for index in range(MAX_PACK_FIXTURES + 1):
        write(folder / f"f{index:03}.yaml", PASSING)

    found = pack_fixtures(hub / "workflows" / "pack")

    *read, refused = found
    assert [item.path.name for item in read] == [  # type: ignore[union-attr]
        f"f{index:03}.yaml" for index in range(MAX_PACK_FIXTURES)
    ]
    assert isinstance(refused, WorkflowFileError)
    assert (refused.source, refused.reason) == (
        str(folder),
        f"more than {MAX_PACK_FIXTURES} fixture files; the rest is not read",
    )


def test_reports_unreadable_files_only_in_the_named_pack_when_a_name_is_given(hub: Path) -> None:
    write(hub / "workflows" / "pack" / "fixtures" / "bad.yaml", "workflow: a\nworkflow: b\n")
    write(hub / "workflows" / "other" / "solo.yaml", WORKFLOW.replace("demo", "solo"))
    write(hub / "workflows" / "other" / "fixtures" / "bad.yaml", "workflow: [x]\n")

    assert [run.path.parent.parent.name for run in runs_of_all(hub, only="demo")] == ["pack"]
    assert [run.path.parent.parent.name for run in runs_of_all(hub, only="solo")] == ["other"]


def runs_of_all(hub: Path, *, only: str) -> tuple[FixtureRun, ...]:
    return run_fixtures(discover_workflows(hub, builtin_root=hub / "no-builtins"), only=only)


@pytest.mark.parametrize(
    "schema",
    [
        {
            "type": "object",
            "properties": {"n": {"type": "integer", "minimum": 1}},
            "required": ["n"],
        },
        {"type": "array", "items": {"enum": ["a", "b"]}, "minItems": 2},
        {"type": ["string", "null"], "default": "x"},
    ],
)
def test_passes_the_json_schema_check_when_a_simple_schema_gets_a_placeholder(
    schema: dict[str, JsonValue],
) -> None:
    JsonSchemaOutputs().check(schema, placeholder(schema))


def test_tells_the_run_status_when_the_skeleton_dry_run_does_not_end_done() -> None:
    broken = WORKFLOW + '    output_format: {type: string, pattern: "^ok$"}\n'

    assert (skeleton_yaml(plan_of(WORKFLOW)).status, skeleton_yaml(plan_of(broken)).status) == (
        "done",
        "failed",
    )
