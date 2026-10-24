"""The canonical scenario writer: a tree file reads back to its own bytes (AC-507.6), and a
graph document keeps the order it had."""

from pathlib import Path

import pytest

from agent_hub.generator.scenario_yaml import render_document
from agent_hub.generator.workflow_yaml import load_workflow_bytes

TREES = Path(__file__).parents[3] / "core" / "tests" / "data" / "scenarios" / "blocks" / "tree"
TREE_FILES = sorted(TREES.glob("*.yaml"))


def test_finds_the_tree_fixtures_when_collected() -> None:
    assert len(TREE_FILES) >= 6


@pytest.mark.parametrize("path", TREE_FILES, ids=lambda path: path.stem)
def test_writes_the_same_bytes_when_tree_file_round_trips(path: Path) -> None:
    data = path.read_bytes()

    text = render_document(load_workflow_bytes(data, source=path.name).document)

    assert text.encode() == data


@pytest.mark.parametrize("path", TREE_FILES, ids=lambda path: path.stem)
def test_changes_no_byte_when_written_twice(path: Path) -> None:
    once = render_document(load_workflow_bytes(path.read_bytes(), source=path.name).document)

    twice = render_document(load_workflow_bytes(once.encode(), source=path.name).document)

    assert twice == once


def test_writes_tree_keys_in_canonical_order_when_given_in_another() -> None:
    document = {
        "stages": [
            {
                "steps": [
                    {"retry": {"max": 2}, "capture": {"a": "$self.output.a"}, "with": {"x": 1}}
                    | {"description": "Send", "id": "send", "do": "queue-send"},
                    {"repeat": {"steps": [{"you": "Check"}], "until": "$CTX.a == 1", "max": 3}},
                    {"else": [{"you": "No"}], "then": [{"you": "Yes"}], "if": "$CTX.a == 1"},
                    {"timeout": "1m", "every": "5s", "until": "$self.output.ok == true"}
                    | {"wait_until": "order-state"},
                ],
                "description": "First",
                "name": "Stage",
            }
        ],
        "inputs": {"a": {"default": 1}},
        "description": "Sample",
        "revision": 3,
        "name": "sample",
        "kind": "scenario",
        "version": 2,
    }

    text = render_document(document)

    assert text == (
        "version: 2\nkind: scenario\nname: sample\nrevision: 3\ndescription: Sample\n"
        "inputs:\n  a:\n    default: 1\nstages:\n- name: Stage\n  description: First\n  steps:\n"
        "  - do: queue-send\n    id: send\n    description: Send\n    with:\n      x: 1\n"
        "    capture:\n      a: $self.output.a\n    retry:\n      max: 2\n"
        "  - repeat:\n      max: 3\n      until: $CTX.a == 1\n      steps:\n      - you: Check\n"
        "  - if: $CTX.a == 1\n    then:\n    - you: 'Yes'\n    else:\n    - you: 'No'\n"
        "  - wait_until: order-state\n    until: $self.output.ok == true\n    every: 5s\n"
        "    timeout: 1m\n"
    )


def test_writes_graph_keys_in_their_order_when_version_is_one() -> None:
    document = {
        "nodes": [{"action": "send", "type": "action", "id": "send"}],
        "name": "walk",
        "version": 1,
        "kind": "scenario",
    }

    text = render_document(document)

    assert text == (
        "version: 1\nkind: scenario\nname: walk\nnodes:\n- id: send\n  type: action\n"
        "  action: send\n"
    )
