import re
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

import agent_hub.core
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import (
    HUB_JSON_PATH,
    HUB_LOCK_PATH,
    build_hub_lock,
    lock_bytes,
)
from agent_hub.core.hub_files.plan_init import (
    FileWrite,
    InitPlan,
    InitRefusal,
    LinkWrite,
    PathProblem,
    plan_init,
)
from agent_hub.core.hub_files.rendered_file import Kind, Ownership, RenderedFile
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.rendered_link import RenderedLink
from agent_hub.core.hub_files.tree_snapshot import (
    FileEntry,
    FolderEntry,
    LinkEntry,
    OtherEntry,
    TreeEntry,
    TreeSnapshot,
)
from agent_hub.core.testing.builders import a_hub_document

HUB_JSON = b'{"project": "demo"}\n'
FOLDERS = (".claude", ".claude/agents", ".claude/skills", "plugin", "plugin/agents", "scripts")
# AGH-19's purity pattern (spec AC-12.26), verbatim: write, tree-read, clock and environment calls.
PURITY = re.compile(
    r"write_text|write_bytes|\bopen\(|os\.(replace|rename|remove|unlink|mkdir|makedirs|chmod|"
    r"symlink|walk|scandir|lstat|environ)|shutil|Path\.cwd|\bPath\(|"
    r"^\s*(import|from) (datetime|time|random|uuid|getpass|socket)\b"
)
CORE_MODULES = (
    "json_form.py",
    "hub_config/conventions.py",
    "hub_files/hub_lock.py",
    "hub_files/tree_snapshot.py",
    "hub_files/plan_init.py",
    "hub_files/plan_sync.py",
    "hub_files/plan_adopt.py",
    "hub_files/extension_inputs.py",
    "doctor/__init__.py",
    "doctor/finding.py",
    "doctor/snapshot.py",
    "doctor/run_rules.py",
    "doctor/config_rules.py",
    "doctor/registry.py",
    "doctor/lock_rules.py",
    "doctor/settings_rules.py",
    "doctor/guard_extension_rule.py",
    "doctor/makefile_rules.py",
    "doctor/features_rule.py",
    "doctor/config_lint.py",
    "doctor/instruction_rules.py",
    "doctor/frontmatter_rule.py",
    "doctor/permission_rules.py",
    "doctor/text_rules.py",
    "doctor/links_rule.py",
    "doctor/brain_leak_rule.py",
    "doctor/bench_rule.py",
    "tracker/__init__.py",
    "tracker/tracker_client.py",
    "workspace/__init__.py",
    "workspace/worktree_name.py",
    "workspace/brief_text.py",
    "workspace/agent_launch.py",
    "runner/__init__.py",
    "runner/ready_list.py",
    "runner/session_prompt.py",
    "runner/verdict.py",
    "runner/run_texts.py",
    "runner/run_record.py",
    "runner/report_writes.py",
    "bench/__init__.py",
    "bench/bench_cases.py",
    "bench/bench_plan.py",
    "bench/bench_session.py",
    "bench/bench_summary.py",
)

# Design decision 4 of the plan, word for word: each refusal names the cause or the way out.
LOCK_PRESENT = "this folder is already a hub; run hub sync"
DIFFERS = "differs from its render; run hub sync --adopt"
HUB_JSON_DIFFERS = "differs from the one this run would write; run hub sync --adopt"
UNKNOWN = "not part of the hub; run hub sync --adopt"
OUTSIDE = "resolves outside the hub"
NOT_REGULAR = "not a regular file"

type HubFactory = Callable[..., RenderedHub]


@pytest.fixture
def config() -> HubConfig:
    return HubConfig.model_validate(a_hub_document())


def a_tree(entries: Mapping[str, TreeEntry] | None = None) -> TreeSnapshot:
    return TreeSnapshot(entries=dict(entries or {}), git_present=False)


def folders(*paths: str) -> dict[str, TreeEntry]:
    return dict.fromkeys(paths, FolderEntry())


def written_tree(rendered: RenderedHub) -> dict[str, TreeEntry]:
    """The tree a finished init leaves: every folder, file and link, and ``hub.json``."""
    entries = folders(*FOLDERS)
    for file in rendered.files:
        entries[file.path] = FileEntry(executable=file.executable, content=file.content)
    for link in rendered.links:
        entries[link.path] = LinkEntry(target=link.target, outside=False)
    entries[HUB_JSON_PATH] = FileEntry(executable=False, content=HUB_JSON)
    return entries


def planned(rendered: RenderedHub, config: HubConfig, tree: TreeSnapshot) -> InitPlan:
    plan = plan_init(rendered=rendered, config=config, hub_json=HUB_JSON, tree=tree)
    assert isinstance(plan, InitPlan)
    return plan


def problems(rendered: RenderedHub, config: HubConfig, tree: TreeSnapshot) -> list[PathProblem]:
    refusal = plan_init(rendered=rendered, config=config, hub_json=HUB_JSON, tree=tree)
    assert isinstance(refusal, InitRefusal)
    return list(refusal.problems)


def written_paths(plan: InitPlan) -> list[str]:
    return [write.path for write in plan.writes]


def test_writes_everything_when_tree_empty(a_rendered_hub: HubFactory, config: HubConfig) -> None:
    rendered = a_rendered_hub()

    plan = planned(rendered, config, a_tree())

    assert plan.folders == FOLDERS
    assert plan.leftovers == ()
    assert plan.lock == build_hub_lock(rendered=rendered, config=config)
    files = [
        FileWrite(path=f.path, content=f.content, executable=f.executable) for f in rendered.files
    ]
    links = [LinkWrite(path=link.path, target=link.target) for link in rendered.links]
    assert plan.writes == (
        *files,
        *links,
        FileWrite(path=HUB_JSON_PATH, content=HUB_JSON, executable=False),
        FileWrite(path=HUB_LOCK_PATH, content=lock_bytes(plan.lock), executable=False),
    )


def test_keeps_file_when_equal_to_render(a_rendered_hub: HubFactory, config: HubConfig) -> None:
    tree = folders(*FOLDERS) | {
        "AGENTS.md": FileEntry(executable=False, content=b"# Rules\n"),
        "scripts/run.sh": FileEntry(executable=True, content=b"#!/bin/sh\n"),
    }

    plan = planned(a_rendered_hub(), config, a_tree(tree))

    assert plan.kept_equal == ("AGENTS.md", "scripts/run.sh")
    assert "AGENTS.md" not in written_paths(plan)
    assert "scripts/run.sh" not in written_paths(plan)


def test_keeps_link_when_target_equal(a_rendered_hub: HubFactory, config: HubConfig) -> None:
    link = LinkEntry(target="../../plugin/agents/x.md", outside=False)
    tree = folders(*FOLDERS) | {".claude/agents/x.md": link}

    plan = planned(a_rendered_hub(), config, a_tree(tree))

    assert plan.kept_links == (".claude/agents/x.md",)
    assert plan.kept_equal == ()
    assert ".claude/agents/x.md" not in written_paths(plan)
    assert plan.created_links == (".claude/skills/y",)


def test_keeps_seeded_file_when_bytes_differ(a_rendered_hub: HubFactory, config: HubConfig) -> None:
    tree = {"README.md": FileEntry(executable=True, content=b"# My own readme\n")}

    plan = planned(a_rendered_hub(), config, a_tree(tree))

    assert plan.kept_seeded == ("README.md",)
    assert "README.md" not in written_paths(plan)


def test_keeps_hub_json_when_byte_equal(a_rendered_hub: HubFactory, config: HubConfig) -> None:
    tree = {HUB_JSON_PATH: FileEntry(executable=False, content=HUB_JSON)}

    plan = planned(a_rendered_hub(), config, a_tree(tree))

    assert plan.kept_seeded == (HUB_JSON_PATH,)
    assert HUB_JSON_PATH not in written_paths(plan)
    assert written_paths(plan)[-1] == HUB_LOCK_PATH


def test_creates_only_missing_folders_when_some_exist(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    plan = planned(a_rendered_hub(), config, a_tree(folders(".claude", "plugin")))

    assert plan.folders == (".claude/agents", ".claude/skills", "plugin/agents", "scripts")


def test_builds_same_lock_when_files_kept_or_written(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()

    fresh = planned(rendered, config, a_tree())
    rerun = planned(rendered, config, a_tree(written_tree(rendered)))

    assert rerun.lock == fresh.lock
    assert rerun.folders == ()
    assert rerun.writes == (fresh.writes[-1],)


@pytest.mark.parametrize("path", [HUB_JSON_PATH, HUB_LOCK_PATH])
@pytest.mark.parametrize("as_link", [False, True], ids=["file", "link"])
def test_raises_when_render_holds_hub_json_or_lock(
    a_rendered_hub: HubFactory, config: HubConfig, path: str, *, as_link: bool
) -> None:
    common = {"kind": Kind.GENERIC, "ownership": Ownership.MANAGED, "module": None}
    if as_link:
        rendered = a_rendered_hub(links=[RenderedLink(path=path, target="AGENTS.md", **common)])
    else:
        rendered = a_rendered_hub(
            files=[RenderedFile(path=path, content=b"{}\n", executable=False, **common)]
        )

    with pytest.raises(ValueError, match=re.escape(path)):
        plan_init(rendered=rendered, config=config, hub_json=HUB_JSON, tree=a_tree())


def test_counts_created_and_kept_when_planned(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()
    tree = folders(*FOLDERS) | {
        "AGENTS.md": FileEntry(executable=False, content=b"# Rules\n"),
        "README.md": FileEntry(executable=False, content=b"# Mine\n"),
        ".claude/agents/x.md": LinkEntry(target="../../plugin/agents/x.md", outside=False),
        HUB_JSON_PATH: FileEntry(executable=False, content=HUB_JSON),
    }

    fresh = planned(rendered, config, a_tree())
    rerun = planned(rendered, config, a_tree(tree))

    assert fresh.created_managed == ("AGENTS.md", "plugin/agents/x.md", "scripts/run.sh")
    assert fresh.created_seeded == ("README.md", HUB_JSON_PATH)
    assert fresh.created_links == (".claude/agents/x.md", ".claude/skills/y")
    assert (fresh.kept_seeded, fresh.kept_equal, fresh.kept_links) == ((), (), ())
    assert rerun.created_managed == ("plugin/agents/x.md", "scripts/run.sh")
    assert rerun.created_seeded == ()
    assert rerun.created_links == (".claude/skills/y",)
    assert rerun.kept_seeded == ("README.md", HUB_JSON_PATH)
    assert rerun.kept_equal == ("AGENTS.md",)
    assert rerun.kept_links == (".claude/agents/x.md",)


def test_keeps_link_whatever_ownership_when_target_equal(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    tree = folders(*FOLDERS) | {
        ".claude/agents/x.md": LinkEntry(target="../../plugin/agents/x.md", outside=False),
        ".claude/skills/y": LinkEntry(target="../../plugin/skills/y", outside=False),
    }

    plan = planned(a_rendered_hub(), config, a_tree(tree))

    assert plan.kept_links == (".claude/agents/x.md", ".claude/skills/y")
    assert (plan.kept_seeded, plan.kept_equal, plan.created_links) == ((), (), ())


@pytest.mark.parametrize("path", ["AGENTS.md", HUB_JSON_PATH])
def test_raises_when_compared_file_content_not_read(
    a_rendered_hub: HubFactory, config: HubConfig, path: str
) -> None:
    tree = {path: FileEntry(executable=False, content=None)}

    with pytest.raises(ValueError, match=re.escape(f"{path}: content was not read")):
        plan_init(rendered=a_rendered_hub(), config=config, hub_json=HUB_JSON, tree=a_tree(tree))


def test_keeps_seeded_file_when_content_not_read(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    tree = {"README.md": FileEntry(executable=False, content=None)}

    plan = planned(a_rendered_hub(), config, a_tree(tree))

    assert plan.kept_seeded == ("README.md",)


def test_calls_no_io_when_core_modules_scanned() -> None:
    core_root = Path(agent_hub.core.__file__).parent
    scanned = [core_root / name for name in CORE_MODULES]
    assert all(path.is_file() for path in scanned)
    assert PURITY.search("    os.replace(a, b)")

    hits = [
        f"{path.name}:{number}: {line}"
        for path in scanned
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if PURITY.search(line)
    ]

    assert hits == []


@pytest.mark.parametrize(
    "entry",
    [
        FileEntry(executable=False, content=None),
        FolderEntry(),
        LinkEntry(target="AGENTS.md", outside=False),
    ],
    ids=["file", "folder", "link"],
)
def test_refuses_when_lock_present(
    a_rendered_hub: HubFactory, config: HubConfig, entry: TreeEntry
) -> None:
    found = problems(a_rendered_hub(), config, a_tree({HUB_LOCK_PATH: entry}))

    assert found == [PathProblem(HUB_LOCK_PATH, LOCK_PRESENT)]
    assert "hub sync" in found[0].message
    assert "--adopt" not in found[0].message


def test_refuses_when_hub_json_differs(a_rendered_hub: HubFactory, config: HubConfig) -> None:
    tree = {HUB_JSON_PATH: FileEntry(executable=False, content=HUB_JSON + b" ")}

    found = problems(a_rendered_hub(), config, a_tree(tree))

    assert found == [PathProblem(HUB_JSON_PATH, HUB_JSON_DIFFERS)]


def test_refuses_when_managed_bytes_differ(a_rendered_hub: HubFactory, config: HubConfig) -> None:
    tree = {"AGENTS.md": FileEntry(executable=False, content=b"# Other rules\n")}

    found = problems(a_rendered_hub(), config, a_tree(tree))

    assert found == [PathProblem("AGENTS.md", DIFFERS)]


def test_refuses_when_executable_bit_differs(a_rendered_hub: HubFactory, config: HubConfig) -> None:
    tree = folders("scripts") | {
        "scripts/run.sh": FileEntry(executable=False, content=b"#!/bin/sh\n")
    }

    found = problems(a_rendered_hub(), config, a_tree(tree))

    assert found == [PathProblem("scripts/run.sh", DIFFERS)]


# The fixture's managed and seeded links: a link is compared whatever its ownership.
LINKS = [
    pytest.param(".claude/agents/x.md", "../../plugin/agents/x.md", id="managed"),
    pytest.param(".claude/skills/y", "../../plugin/skills/y", id="seeded"),
]


@pytest.mark.parametrize(("path", "target"), LINKS)
def test_refuses_when_link_target_differs(
    a_rendered_hub: HubFactory, config: HubConfig, *, path: str, target: str
) -> None:
    link = LinkEntry(target=f"{target}-other", outside=False)
    tree = folders(*FOLDERS) | {path: link}

    found = problems(a_rendered_hub(), config, a_tree(tree))

    assert found == [PathProblem(path, DIFFERS)]


@pytest.mark.parametrize(("path", "target"), LINKS)
def test_refuses_when_link_resolves_outside(
    a_rendered_hub: HubFactory, config: HubConfig, *, path: str, target: str
) -> None:
    link = LinkEntry(target=target, outside=True)
    tree = folders(*FOLDERS) | {path: link}

    found = problems(a_rendered_hub(), config, a_tree(tree))

    assert found == [PathProblem(path, OUTSIDE)]


@pytest.mark.parametrize(
    ("path", "entry", "message"),
    [
        pytest.param(
            "AGENTS.md", FolderEntry(), "a folder where a file belongs", id="folder-at-file"
        ),
        pytest.param(
            "AGENTS.md",
            LinkEntry(target="README.md", outside=False),
            "a link where a file belongs",
            id="link-at-file",
        ),
        pytest.param(
            ".claude/agents/x.md",
            FileEntry(executable=False, content=None),
            "a file where a link belongs",
            id="file-at-link",
        ),
        pytest.param(
            ".claude/agents/x.md",
            FolderEntry(),
            "a folder where a link belongs",
            id="folder-at-link",
        ),
        pytest.param(
            "README.md",
            LinkEntry(target="AGENTS.md", outside=False),
            "a link where a file belongs",
            id="link-at-seeded",
        ),
        pytest.param(
            "README.md", FolderEntry(), "a folder where a file belongs", id="folder-at-seeded"
        ),
        pytest.param(
            HUB_JSON_PATH,
            LinkEntry(target="AGENTS.md", outside=False),
            "a link where a file belongs",
            id="link-at-hub-json",
        ),
        pytest.param(
            HUB_JSON_PATH, FolderEntry(), "a folder where a file belongs", id="folder-at-hub-json"
        ),
    ],
)
def test_refuses_when_type_differs(
    a_rendered_hub: HubFactory, config: HubConfig, *, path: str, entry: TreeEntry, message: str
) -> None:
    tree = folders(*FOLDERS) | {path: entry}

    found = problems(a_rendered_hub(), config, a_tree(tree))

    assert found == [PathProblem(path, message)]


@pytest.mark.parametrize(
    "path", ["AGENTS.md", "README.md", ".claude/agents/x.md", HUB_JSON_PATH], ids=str
)
def test_refuses_when_not_regular_file(
    a_rendered_hub: HubFactory, config: HubConfig, path: str
) -> None:
    tree = folders(*FOLDERS) | {path: OtherEntry(kind="fifo")}

    found = problems(a_rendered_hub(), config, a_tree(tree))

    assert found == [PathProblem(path, NOT_REGULAR)]


@pytest.mark.parametrize(
    ("ancestor", "outside", "below"),
    [
        pytest.param("plugin", False, ["plugin/agents/x.md"], id="top"),
        pytest.param("plugin", True, ["plugin/agents/x.md"], id="top-outside"),
        pytest.param(".claude/agents", False, [".claude/agents/x.md"], id="nested"),
        pytest.param(".claude", False, [".claude/agents/x.md", ".claude/skills/y"], id="two-below"),
    ],
)
def test_refuses_when_ancestor_is_symlink(
    a_rendered_hub: HubFactory,
    config: HubConfig,
    *,
    ancestor: str,
    below: list[str],
    outside: bool,
) -> None:
    kept = [f for f in FOLDERS if f != ancestor and not f.startswith(f"{ancestor}/")]
    tree = folders(*kept) | {ancestor: LinkEntry(target="/elsewhere", outside=outside)}

    found = problems(a_rendered_hub(), config, a_tree(tree))

    assert found == [PathProblem(path, f"symlinked ancestor {ancestor}") for path in below]


@pytest.mark.parametrize(
    "entry",
    [FileEntry(executable=False, content=None), OtherEntry(kind="socket")],
    ids=["file", "other"],
)
def test_refuses_when_ancestor_is_file(
    a_rendered_hub: HubFactory, config: HubConfig, entry: TreeEntry
) -> None:
    tree = folders(".claude", ".claude/agents", ".claude/skills", "plugin", "plugin/agents")
    tree["scripts"] = entry

    found = problems(a_rendered_hub(), config, a_tree(tree))

    assert found == [PathProblem("scripts/run.sh", "a file where a folder belongs: scripts")]


BRAIN_NOW = RenderedFile(
    path="brain/now.md",
    content=b"# Now\n",
    executable=False,
    kind=Kind.GENERIC,
    ownership=Ownership.SEEDED,
    module=None,
)
TEMP_SHAPED = ".x.hub-tmp-0a1b2c3d"


@pytest.mark.parametrize(
    ("entries", "unknown"),
    [
        pytest.param(
            {"notes.txt": FileEntry(executable=False, content=None)}, ["notes.txt"], id="file"
        ),
        pytest.param(
            folders("brain/extra")
            | {"brain/extra/x.md": FileEntry(executable=False, content=None)},
            ["brain/extra", "brain/extra/x.md"],
            id="file-in-unknown-folder",
        ),
        pytest.param(folders("docs"), ["docs"], id="empty-folder"),
        pytest.param(
            {".DS_Store": FileEntry(executable=False, content=None)}, [".DS_Store"], id="ds-store"
        ),
        pytest.param(folders(TEMP_SHAPED), [TEMP_SHAPED], id="temp-named-folder"),
        pytest.param({TEMP_SHAPED: OtherEntry(kind="fifo")}, [TEMP_SHAPED], id="temp-named-fifo"),
        pytest.param({"notes": LinkEntry(target="AGENTS.md", outside=False)}, ["notes"], id="link"),
    ],
)
def test_refuses_when_entry_unknown(
    a_rendered_hub: HubFactory,
    config: HubConfig,
    *,
    entries: dict[str, TreeEntry],
    unknown: list[str],
) -> None:
    rendered = a_rendered_hub(files=(*a_rendered_hub().files, BRAIN_NOW))
    tree = folders(*FOLDERS, "brain") | entries

    found = problems(rendered, config, a_tree(tree))

    assert found == [PathProblem(path, UNKNOWN) for path in unknown]


def test_cleans_leftover_when_file_or_link_has_temp_shape(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()
    leftovers = {
        ".Makefile.hub-tmp-0a1b2c3d": FileEntry(executable=False, content=None),
        "plugin/agents/.x.md.hub-tmp-ffffffff": LinkEntry(target="x.md", outside=False),
        "scripts/.run.sh.hub-tmp-00000000": LinkEntry(target="/etc/passwd", outside=True),
    }

    fresh = planned(rendered, config, a_tree(folders(*FOLDERS)))
    plan = planned(rendered, config, a_tree(folders(*FOLDERS) | leftovers))

    assert plan.leftovers == tuple(sorted(leftovers))
    assert plan.writes == fresh.writes
    assert plan.lock == fresh.lock
    assert not set(leftovers) & set(plan.lock.files)


def test_sorts_leftovers_when_tree_lists_them_out_of_order(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    leftovers = {
        "scripts/.run.sh.hub-tmp-00000000": FileEntry(executable=False, content=None),
        ".Makefile.hub-tmp-0a1b2c3d": LinkEntry(target="Makefile", outside=False),
        "plugin/agents/.x.md.hub-tmp-ffffffff": FileEntry(executable=False, content=None),
    }

    plan = planned(a_rendered_hub(), config, a_tree(leftovers | folders(*FOLDERS)))

    assert plan.leftovers == (
        ".Makefile.hub-tmp-0a1b2c3d",
        "plugin/agents/.x.md.hub-tmp-ffffffff",
        "scripts/.run.sh.hub-tmp-00000000",
    )


SETUP_MD = RenderedFile(
    path="setup.md",
    content=b"# Setup\n",
    executable=False,
    kind=Kind.GENERIC,
    ownership=Ownership.SEEDED,
    module=None,
)


def test_sorts_seeded_paths_when_seeded_file_follows_hub_json(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    # ``setup.md`` sorts after ``hub.json``, which the planner decides last.
    rendered = a_rendered_hub(files=(*a_rendered_hub().files, SETUP_MD))
    tree = {
        HUB_JSON_PATH: FileEntry(executable=False, content=HUB_JSON),
        "README.md": FileEntry(executable=False, content=b"# Mine\n"),
        "setup.md": FileEntry(executable=False, content=b"# Mine\n"),
    }

    fresh = planned(rendered, config, a_tree())
    rerun = planned(rendered, config, a_tree(tree))

    assert fresh.created_seeded == ("README.md", HUB_JSON_PATH, "setup.md")
    assert rerun.kept_seeded == ("README.md", HUB_JSON_PATH, "setup.md")


def test_returns_every_problem_sorted_when_several_refused(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    tree = folders(".claude", ".claude/agents", ".claude/skills", "plugin") | {
        HUB_LOCK_PATH: FileEntry(executable=False, content=None),
        "notes.txt": FileEntry(executable=False, content=None),
        "AGENTS.md": FileEntry(executable=False, content=b"# Other\n"),
        ".DS_Store": FileEntry(executable=False, content=None),
        "scripts": LinkEntry(target="../scripts", outside=True),
        ".claude/skills/y": FileEntry(executable=False, content=None),
        "plugin/.agents.hub-tmp-0a1b2c3d": FolderEntry(),
    }

    result = plan_init(
        rendered=a_rendered_hub(), config=config, hub_json=HUB_JSON, tree=a_tree(tree)
    )

    assert result == InitRefusal(
        problems=(
            PathProblem(".DS_Store", UNKNOWN),
            PathProblem(".claude/skills/y", "a file where a link belongs"),
            PathProblem("AGENTS.md", DIFFERS),
            PathProblem(HUB_LOCK_PATH, LOCK_PRESENT),
            PathProblem("notes.txt", UNKNOWN),
            PathProblem("plugin/.agents.hub-tmp-0a1b2c3d", UNKNOWN),
            PathProblem("scripts/run.sh", "symlinked ancestor scripts"),
        )
    )
