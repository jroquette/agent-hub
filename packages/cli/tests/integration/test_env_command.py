"""``hub env``: list, show and change the declared environments (AGH-287, spec D-envcmd).

Each test builds a hub folder holding only ``hub.json`` (written with indent 2 and its keys in
the file's order, a ``_comment`` first) and, when asked, the developer's ``hub.local.json``,
then runs the command in process with ``AGENT_HUB_ROOT`` naming it.
"""

import json
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
from agent_hub.core.testing.builders import (
    a_hub_document,
    a_local_environments_document,
    an_environments_document,
)

AWS_KEY = "AK" + "IA" + "A" * 16
SYNC_HINT = "run ./hub sync to update AGENTS.md"
PRODUCTION_LINE = "production environment: live (access read, hub.json)"


def hub_bytes(document: dict[str, Any]) -> bytes:
    """``document`` as ``hub env`` writes it: the file's key order, indent 2, a final newline."""
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode()


def pinned(document: dict[str, Any]) -> dict[str, Any]:
    """``document`` with a ``_comment`` first and the pin of the running CLI."""
    document["platform"]["version"] = version("agent-hub-cli")
    return {"_comment": "A synthetic demo hub.", **document}


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    """A hub with the spec's ``W`` and no ``hub.local.json``."""
    root = tmp_path / "hub"
    root.mkdir()
    (root / "hub.json").write_bytes(hub_bytes(pinned(an_environments_document())))
    return root


@pytest.fixture
def local_hub(hub: Path) -> Path:
    """``hub`` with the spec's ``Lc``, which tightens ``staging`` to ``read``."""
    local = a_local_environments_document()
    local["environments"]["staging"] = {"access": "read"}
    (hub / "hub.local.json").write_bytes(hub_bytes(local))
    return hub


def run_env(root: Path, *args: str) -> Result:
    return CliRunner().invoke(app, ["env", *args], env={"AGENT_HUB_ROOT": str(root)}, input="")


def test_lists_environments_when_files_declare_them(local_hub: Path) -> None:
    result = run_env(local_hub, "list")

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines()[:7] == [
        "local (write, hub.json): docker compose stack on this machine",
        "staging (read, hub.local.json)",
        "live (read, PRODUCTION, hub.json)",
        "jane-cloud (write, hub.local.json)",
        "services:",
        "  demo-api api (api): local, staging, live, jane-cloud",
        "  demo-api orders (dynamodb): staging",
    ]


def test_shows_environment_when_name_declared(local_hub: Path) -> None:
    result = run_env(local_hub, "show", "live")

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == [
        "live (read, PRODUCTION, hub.json)",
        "  aws profile: demo-live-ro",
        "  credential variables: DEMO_LIVE_DB_URL",
        "  endpoints:",
        "    demo-api api: https://api.example.com",
    ]


def test_prints_json_when_json_flag_given(local_hub: Path) -> None:
    listed = run_env(local_hub, "list", "--json")
    shown = run_env(local_hub, "show", "staging", "--json")

    assert (listed.exit_code, listed.stderr, shown.exit_code, shown.stderr) == (0, "", 0, "")
    data = json.loads(listed.stdout)
    assert [item["name"] for item in data["environments"]] == [
        "local",
        "staging",
        "live",
        "jane-cloud",
    ]
    assert data["environments"][1]["source"] == "hub.local.json"
    assert [item["value"] for item in data["blocked_words"]] == ["prod", "production", "demo-live"]
    shown_data = json.loads(shown.stdout)
    assert shown_data["environment"]["access"] == "read"
    assert [item["service"] for item in shown_data["endpoints"]] == ["api", "orders"]
    # The same data, byte for byte, on every run: sorted keys, indent 2.
    assert run_env(local_hub, "list", "--json").stdout == listed.stdout
    assert listed.stdout == json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def test_exits_one_when_show_name_unknown(local_hub: Path) -> None:
    result = run_env(local_hub, "show", "qa")
    hidden = run_env(local_hub, "show", AWS_KEY)

    assert (result.exit_code, result.stdout) == (1, ""), result.output
    assert result.stderr == "hub env show: no environment qa in hub.json or hub.local.json\n"
    assert hidden.exit_code == 1
    assert AWS_KEY not in hidden.output


def test_suggests_names_when_no_environment_declared(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    (root / "hub.json").write_bytes(hub_bytes(pinned(a_hub_document())))

    result = run_env(root, "list")

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout == (
        "no environments declared; for example: ./hub env add local --access write"
        " (suggested names: local, staging, production)\n"
    )


def test_hides_secret_when_hub_json_holds_one(hub: Path) -> None:
    document = json.loads((hub / "hub.json").read_bytes())
    document["environments"]["staging"]["description"] = f"key {AWS_KEY}"
    (hub / "hub.json").write_bytes(hub_bytes(document))

    for args in (("list",), ("show", "staging"), ("list", "--json")):
        result = run_env(hub, *args)

        assert (result.exit_code, result.stdout) == (1, ""), result.output
        assert "environments.staging.description" in result.stderr
        assert AWS_KEY not in result.output
