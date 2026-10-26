"""The web's copy of the tree fixtures (AC-507.24): the strict loader's parse of each scenario of
``packages/core/tests/data/scenarios/blocks/tree``, as the API gives it as ``document``, and the
scenario writer's key order, in ``apps/web/src/testing/treeDocuments.ts``. ``GOLDEN_UPDATE=1``
rewrites it through the golden harness (refused under ``CI``); review and commit the diff."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.json_form import JsonValue
from agent_hub.generator.scenario_yaml import render_document
from agent_hub.generator.workflow_yaml import load_workflow_bytes

_PACKAGES = Path(__file__).parents[3]
TREES = _PACKAGES / "core" / "tests" / "data" / "scenarios" / "blocks" / "tree"
# The web's copy of what the API gives as a tree scenario's ``document`` (this loader's parse),
# which the builder's round trip is checked against (AC-507.24).
WEB_TREES = _PACKAGES.parent / "apps" / "web" / "src" / "testing" / "treeDocuments.ts"
WEB_TREES_HINT = (
    "Update: GOLDEN_UPDATE=1 uv run --locked --all-packages pytest "
    "packages/generator/tests/integration/test_web_tree_documents.py -q, then review and commit "
    "the diff"
)
WEB_TREES_HEADER = """\
// Generated: the strict loader's parse of each scenario of
// packages/core/tests/data/scenarios/blocks/tree, as GET /api/v1/scenarios/{project}/{name}
// gives it as `document`, and the scenario writer's key order. test_web_tree_documents.py
// (packages/generator/tests/integration) checks it and rewrites it with GOLDEN_UPDATE=1. Tests
// read it through aTreeDocument and anEveryKeyTree (builders.ts).
"""
# A synthetic tree holding every key the scenario writer orders. The web's module holds it as
# the writer writes it from its keys in reverse order, read back: the builder writes a file in
# the writer's key order, which its round trip of this document checks.
EVERY_KEY: JsonValue = {
    "version": 2,
    "kind": "scenario",
    "name": "every-key",
    "revision": 3,
    "description": "Every step key of the tree format",
    "inputs": {"order_id": {"required": True}},
    "stages": [
        {
            "name": "Every key",
            "description": "Each step with its optional keys",
            "steps": [
                {
                    "do": "order-get",
                    "id": "get-order",
                    "description": "Reads the order",
                    "with": {"order_id": "$INPUTS.order_id"},
                    "timeout": "5m",
                    "capture": {"status": "$self.output.status"},
                    "retry": {"max_attempts": 3, "delay": "5s", "on_error": "all"},
                },
                {
                    "wait_until": "order-state",
                    "until": "$self.output.status == 'DONE'",
                    "every": "15s",
                    "timeout": "10m",
                    "retry": {"max_attempts": 1},
                },
                {
                    "you": "Approve the order, or reject it.",
                    "description": "A person decides",
                    "decisions": [
                        {"id": "approve", "label": "Approve"},
                        {"id": "reject", "label": "Reject"},
                    ],
                    "capture_response": True,
                },
                {"wait": {"duration": "1m", "until": "2030-01-01T00:00:00Z"}},
                {
                    "wait": {
                        "attention": "Pick a carrier",
                        "options": [
                            {"id": "fast", "label": "Fast"},
                            {"id": "slow", "label": "Slow"},
                        ],
                    },
                    "id": "pick-carrier",
                    "description": "Waits for a choice",
                },
                {
                    "include": "blocks-repeat",
                    "description": "Polls the review",
                    "with": {"shop_order_id": "$INPUTS.order_id"},
                },
                {
                    "if": "$CTX.status == 'DONE'",
                    "description": "Only when done",
                    "then": [{"wait": {"duration": "1m"}}],
                    "else": [{"do": "order-d"}],
                },
                {
                    "together": [[{"do": "order-a"}], [{"do": "order-b"}]],
                    "description": "Both at once",
                },
                {
                    "repeat": {
                        "max": 3,
                        "until": "$get-order.output.status == 'DONE'",
                        "steps": [{"do": "order-c"}],
                    },
                    "id": "again",
                    "description": "Tries again",
                },
            ],
        }
    ],
}


def web_tree_module(documents: Mapping[str, object], every_key: object) -> str:
    """The web's module of ``documents`` by scenario name and the writer's ``every_key``, as the
    check writes it."""
    body = json.dumps(dict(sorted(documents.items())), indent=2, ensure_ascii=False)
    declared = "export const TREE_DOCUMENTS: Readonly<Record<string, unknown>> ="
    ordered = json.dumps(every_key, indent=2, ensure_ascii=False)
    written = (
        "// The scenario writer's key order: a tree holding every key it orders, written from its\n"
        "// keys in reverse order and read back.\n"
        "export const EVERY_KEY_DOCUMENT: Readonly<Record<string, unknown>> ="
    )
    return f"{WEB_TREES_HEADER}{declared} {body};\n\n{written} {ordered};\n"


def reversed_keys(value: JsonValue) -> JsonValue:
    """``value`` with the keys of each mapping in it in reverse order."""
    if isinstance(value, dict):
        return {key: reversed_keys(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [reversed_keys(item) for item in value]
    return value


def check_web_tree_documents(golden: Any, module: Path) -> int:
    """Checks ``module`` holds the web's tree documents (rewrites it first under
    ``GOLDEN_UPDATE=1``); the number of tree fixtures it holds."""
    documents = {
        path.stem: load_workflow_bytes(path.read_bytes(), source=path.name).document
        for path in sorted(TREES.glob("*.yaml"))
    }
    scrambled = reversed_keys(EVERY_KEY)
    assert isinstance(scrambled, dict)
    text = render_document(scrambled)
    every_key = load_workflow_bytes(text.encode(), source="every-key.yaml").document
    expected = web_tree_module(documents, every_key)
    if golden.update_mode():
        module.write_text(expected, encoding="utf-8", newline="\n")

    assert module.read_text(encoding="utf-8") == expected, WEB_TREES_HINT
    return len(documents)


def test_refuses_to_rewrite_web_tree_documents_when_ci_set(
    golden: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GOLDEN_UPDATE", "1")
    monkeypatch.setenv("CI", "true")
    module = tmp_path / "treeDocuments.ts"
    module.write_text("// stale\n", encoding="utf-8")

    with pytest.raises(pytest.fail.Exception, match="GOLDEN_UPDATE=1 is refused when CI is set"):
        check_web_tree_documents(golden, module)
    assert module.read_text(encoding="utf-8") == "// stale\n"


def test_holds_the_loaders_parse_when_web_tree_documents_read(golden: Any) -> None:
    assert check_web_tree_documents(golden, WEB_TREES) >= 6
