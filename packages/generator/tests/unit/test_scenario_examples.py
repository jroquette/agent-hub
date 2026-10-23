"""The scenario examples ``hub init`` writes (AGH-350 AM-6, docs/design/scenarios.md)."""

import re

import yaml

from agent_hub.core.hub_files.tree_snapshot import FileEntry, FolderEntry, LinkEntry, TreeSnapshot
from agent_hub.generator.scenario_examples import EXAMPLE_FILES, without_examples

ACTION, SCRIPT, SCENARIO = (example.path for example in EXAMPLE_FILES)
# Any URL host in the examples: only localhost and example.com are allowed (AC-350.33).
URL_HOST = re.compile(rb"https?://([^/\s\"']+)")


def test_names_demo_action_and_scenario_when_examples_listed() -> None:
    action = yaml.safe_load(EXAMPLE_FILES[0].content)
    scenario = yaml.safe_load(EXAMPLE_FILES[2].content)

    assert (action["name"], action["effect"], action["script"]) == (
        "demo-get-status",
        "read",
        SCRIPT.removeprefix("actions/demo/"),
    )
    assert f"actions/demo/{action['name']}.yaml" == ACTION
    assert (scenario["kind"], scenario["name"]) == ("scenario", "demo-service-up")
    assert f"scenarios/demo/{scenario['name']}.yaml" == SCENARIO
    assert {node["action"] for node in scenario["nodes"]} == {action["name"]}
    assert not any(example.executable for example in EXAMPLE_FILES)
    assert not [host for e in EXAMPLE_FILES for host in URL_HOST.findall(e.content)]


def test_drops_example_files_and_folders_when_examples_present() -> None:
    mine = FileEntry(executable=False, content=None)
    tree = TreeSnapshot(
        entries={
            "actions": FolderEntry(),
            "actions/demo": FolderEntry(),
            "actions/demo/scripts": FolderEntry(),
            ACTION: mine,
            SCRIPT: mine,
            "actions/demo/mine.yaml": mine,
            "scenarios": FolderEntry(),
            "scenarios/demo": LinkEntry(target="elsewhere", outside=True),
            "README.md": mine,
        },
        git_present=True,
    )

    kept = without_examples(tree)

    assert dict(kept.entries) == {
        "actions/demo/mine.yaml": mine,
        "scenarios/demo": LinkEntry(target="elsewhere", outside=True),
        "README.md": mine,
    }
    assert kept.git_present


def test_keeps_tree_when_examples_absent() -> None:
    tree = TreeSnapshot(
        entries={"README.md": FileEntry(executable=False, content=b"")}, git_present=False
    )

    assert dict(without_examples(tree).entries) == dict(tree.entries)


def test_keeps_link_when_example_path_is_link() -> None:
    link = LinkEntry(target="../elsewhere.yaml", outside=True)
    tree = TreeSnapshot(entries={"scenarios": FolderEntry(), SCENARIO: link}, git_present=True)

    assert dict(without_examples(tree).entries) == {SCENARIO: link}
