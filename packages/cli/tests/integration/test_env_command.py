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
# A synthetic JWT shape: three base64url parts, the first two starting as a JSON object does.
JWT = "eyJ" + "a" * 20 + ".eyJ" + "b" * 20 + "." + "c" * 20
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
    """A hub with the spec's ``W``, comment keys in its maps, and no ``hub.local.json``."""
    root = tmp_path / "hub"
    root.mkdir()
    document = pinned(an_environments_document())
    document["environments"]["_note"] = "a comment, not an environment"
    services = document["repos"][0]["services"]
    services["_note"] = "a comment, not a service"
    services["api"]["endpoints"]["_note"] = "a comment, not an endpoint"
    (root / "hub.json").write_bytes(hub_bytes(document))
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


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file of the hub folder and its bytes: a refused write must leave them all."""
    return {path.name: path.read_bytes() for path in sorted(root.iterdir())}


def test_adds_environment_when_name_new(hub: Path) -> None:
    document = json.loads((hub / "hub.json").read_bytes())

    result = run_env(hub, "add", "qa", "--access", "ask", "--description", "a shared test stack")

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == ["hub.json: added environment qa", SYNC_HINT]
    document["environments"]["qa"] = {"access": "ask", "description": "a shared test stack"}
    # Every other key, its order and the _comment kept; only qa is new, last.
    assert (hub / "hub.json").read_bytes() == hub_bytes(document)
    assert sorted(path.name for path in hub.iterdir()) == ["hub.json"]


def test_adds_local_environment_when_local_flag_given(hub: Path) -> None:
    before = (hub / "hub.json").read_bytes()

    created = run_env(
        hub, "add", "jane-box", "--access", "write", "--aws-profile", "jane-sandbox", "--local"
    )

    assert (created.exit_code, created.stderr) == (0, ""), created.output
    assert created.stdout.splitlines() == ["hub.local.json: added environment jane-box"]
    assert (hub / "hub.local.json").read_bytes() == hub_bytes(
        {
            "environments": {
                "jane-box": {"access": "write", "credentials": {"aws_profile": "jane-sandbox"}}
            }
        }
    )
    assert (hub / "hub.json").read_bytes() == before

    identity = {"project": {"branch_prefix": "jane/", "author_name": "Jane Doe"}}
    (hub / "hub.local.json").write_bytes(hub_bytes(identity))
    kept = run_env(
        hub,
        "add",
        "jane-box",
        "--access",
        "read",
        "--credential-env",
        "JANE_DB_URL",
        "--credential-env",
        "JANE_TOKEN_NAME",
        "--local",
    )

    assert (kept.exit_code, kept.stderr) == (0, ""), kept.output
    assert (hub / "hub.local.json").read_bytes() == hub_bytes(
        {
            **identity,
            "environments": {
                "jane-box": {
                    "access": "read",
                    "credentials": {"env": ["JANE_DB_URL", "JANE_TOKEN_NAME"]},
                }
            },
        }
    )


@pytest.mark.parametrize(
    "args",
    [
        ("add", "staging", "--access", "ask"),
        ("add", "Jane-Cloud", "--access", "ask"),
        ("add", "jane-cloud", "--access", "ask", "--local"),
        ("add", "qa", "--access", "admin"),
        ("add", "qa", "--access", "ask", "--description", "x" * 81),
        ("add", "qa", "--access", "ask", "--description", f"key {AWS_KEY}"),
        ("add", AWS_KEY, "--access", "ask"),
        ("add", "qa", "--access", "ask", "--aws-profile", "a b"),
        ("add", "qa", "--access", "ask", "--credential-env", "lower"),
        (
            "service",
            "add",
            "demo-api",
            "cache",
            "--env",
            "local",
            "--url",
            "https://u:pw@x.example.com",
        ),
        (
            "service",
            "add",
            "demo-api",
            "cache",
            "--env",
            "local",
            "--url",
            "https://x.example.com/?token=x",
        ),
        ("remove", "staging"),
        ("remove", "qa"),
        ("set", "qa", "--access", "ask"),
        ("set", "live", "--access", "ask", "--local"),
        ("remove", "jane-cloud", "--local"),
        (
            "service",
            "add",
            "demo-api",
            "cache",
            "--env",
            "local",
            "--url",
            "https://x.example.com/#k",
        ),
        (
            "service",
            "add",
            "demo-api",
            "cache",
            "--env",
            "local",
            "--url",
            "http://localhost:6379",
            "--note",
            f"token {JWT}",
        ),
        (
            "service",
            "add",
            AWS_KEY,
            "cache",
            "--env",
            "jane-cloud",
            "--url",
            "http://localhost:1",
            "--local",
        ),
        ("add", "_x", "--access", "ask"),
        ("set", "_note", "--access", "ask"),
        ("remove", "_note"),
        ("service", "add", "demo-api", "_cache", "--env", "local", "--url", "http://localhost:1"),
        ("service", "remove", "demo-api", "_note"),
        ("service", "remove", "demo-api", "api", "--env", "_note"),
    ],
    ids=[
        "add-existing",
        "add-existing-other-file-ignoring-case",
        "add-local-existing",
        "add-bad-access",
        "add-long-description",
        "add-secret-description",
        "add-secret-name",
        "add-secret-bad-profile",
        "add-secret-bad-variable",
        "service-secret-url-user-info",
        "service-secret-url-query",
        "remove-used",
        "remove-unknown",
        "set-unknown",
        "set-local-looser",
        "remove-local-used",
        "service-secret-url-fragment",
        "service-secret-jwt-note",
        "service-secret-local-repo-dir",
        "add-comment-key",
        "set-comment-key",
        "remove-comment-key",
        "service-add-comment-service",
        "service-remove-comment-service",
        "service-remove-comment-env",
    ],
)
def test_exits_one_when_add_refused(local_hub: Path, args: tuple[str, ...]) -> None:
    before = snapshot(local_hub)

    result = run_env(local_hub, *args)

    assert (result.exit_code, result.stdout) == (1, ""), result.output
    assert result.stderr.count("\n") >= 1
    assert snapshot(local_hub) == before
    for secret in (AWS_KEY, "pw@", "token=x", "#k", JWT):
        assert secret not in result.output


def test_names_refusal_when_add_or_remove_refused(local_hub: Path) -> None:
    taken = run_env(local_hub, "add", "Jane-Cloud", "--access", "ask")
    used = run_env(local_hub, "remove", "staging")
    looser = run_env(local_hub, "add", "qa", "--access", "admin")

    assert taken.stderr == "environment jane-cloud is already declared in hub.local.json\n"
    assert used.stderr == (
        "environment staging still has endpoints (demo-api api, demo-api orders);"
        " remove them first: ./hub env service remove\n"
    )
    assert looser.stderr.startswith("hub.json: environments.qa.access: ")


def test_exits_one_when_file_changed_since_read(hub: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_hub.cli import env_command

    real = env_command.document_bytes
    changed = b'{"changed": true}\n'

    def change_then_dump(document: Any) -> bytes:
        (hub / "hub.json").write_bytes(changed)
        return real(document)

    monkeypatch.setattr(env_command, "document_bytes", change_then_dump)

    result = run_env(hub, "add", "qa", "--access", "ask")

    assert (result.exit_code, result.stdout) == (1, ""), result.output
    assert result.stderr == "hub.json changed since it was read; run the command again\n"
    assert (hub / "hub.json").read_bytes() == changed


def test_prints_production_line_when_add_declares_one(hub: Path) -> None:
    added = run_env(hub, "add", "eu-live", "--access", "read", "--production")
    kept = run_env(hub, "set", "live", "--access", "ask")
    cleared = run_env(hub, "set", "eu-live", "--no-production")

    assert (added.exit_code, kept.exit_code, cleared.exit_code) == (0, 0, 0), added.output
    assert added.stdout.splitlines() == [
        "hub.json: added environment eu-live",
        "production environment: eu-live (access read, hub.json)",
        SYNC_HINT,
    ]
    assert kept.stdout.splitlines() == [
        "hub.json: updated environment live",
        "production environment: live (access ask, hub.json)",
        SYNC_HINT,
    ]
    assert cleared.stdout.splitlines() == ["hub.json: updated environment eu-live", SYNC_HINT]
    environments = json.loads((hub / "hub.json").read_bytes())["environments"]
    assert environments["eu-live"] == {"access": "read"}


def test_writes_tighten_when_local_access_stricter(local_hub: Path) -> None:
    local = a_local_environments_document()
    (local_hub / "hub.local.json").write_bytes(hub_bytes(local))
    hub_before = (local_hub / "hub.json").read_bytes()

    result = run_env(local_hub, "set", "staging", "--access", "read", "--local")

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == ["hub.local.json: updated environment staging"]
    local["environments"]["staging"] = {"access": "read"}
    assert (local_hub / "hub.local.json").read_bytes() == hub_bytes(local)
    assert (local_hub / "hub.json").read_bytes() == hub_before
    assert "staging (read, hub.local.json)" in run_env(local_hub, "list").stdout.splitlines()


def test_refuses_tighten_when_access_looser(local_hub: Path) -> None:
    (local_hub / "hub.local.json").write_bytes(hub_bytes(a_local_environments_document()))
    before = snapshot(local_hub)

    for access in ("write", "ask"):
        result = run_env(local_hub, "set", "staging", "--access", access, "--local")

        assert (result.exit_code, result.stdout) == (1, ""), result.output
        assert result.stderr == (
            "hub.local.json: environments.staging.access: may only tighten hub.json's ask\n"
        )
    assert snapshot(local_hub) == before


def test_prints_reformat_line_when_hub_json_not_indent_two(hub: Path) -> None:
    document = json.loads((hub / "hub.json").read_bytes())
    (hub / "hub.json").write_bytes(json.dumps(document, indent=4).encode() + b"\n")

    result = run_env(hub, "add", "qa", "--access", "ask")

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == [
        "hub.json: rewritten with indent 2",
        "hub.json: added environment qa",
        SYNC_HINT,
    ]
    document["environments"]["qa"] = {"access": "ask"}
    assert (hub / "hub.json").read_bytes() == hub_bytes(document)
    again = run_env(hub, "remove", "qa")
    assert again.stdout.splitlines() == ["hub.json: removed environment qa", SYNC_HINT]


def test_never_prompts_when_stdin_closed(hub: Path) -> None:
    start = (hub / "hub.json").read_bytes()

    for args in (
        ("add", "qa", "--access", "ask"),
        ("set", "qa", "--access", "read", "--description", "a shared test stack"),
        ("remove", "qa"),
    ):
        result = CliRunner().invoke(
            app, ["env", *args], env={"AGENT_HUB_ROOT": str(hub)}, input=None
        )

        assert (result.exit_code, result.stderr) == (0, ""), result.output
        assert "?" not in result.stdout
    # add then remove gives the file back, byte for byte.
    assert (hub / "hub.json").read_bytes() == start


def test_exits_two_when_usage_wrong(hub: Path) -> None:
    before = snapshot(hub)

    for args in (
        ("set", "live"),
        ("add", "qa"),
        ("service", "add", "demo-api", "cache", "--env", "local"),
        (
            "service",
            "add",
            "demo-api",
            "cache",
            "--env",
            "local",
            "--url",
            "http://localhost:1",
            "--resource",
            "x",
        ),
    ):
        assert run_env(hub, *args).exit_code == 2, args
    assert snapshot(hub) == before


def test_round_trips_service_when_added_then_removed(local_hub: Path) -> None:
    before = snapshot(local_hub)

    added = run_env(
        local_hub,
        "service",
        "add",
        "demo-api",
        "cache",
        "--env",
        "local",
        "--url",
        "redis://localhost:6379",
        "--kind",
        "redis",
        "--note",
        "no auth locally",
    )

    assert (added.exit_code, added.stderr) == (0, ""), added.output
    assert added.stdout.splitlines() == ["hub.json: added endpoint demo-api cache local", SYNC_HINT]
    services = json.loads((local_hub / "hub.json").read_bytes())["repos"][0]["services"]
    assert services["cache"] == {
        "kind": "redis",
        "endpoints": {"local": {"url": "redis://localhost:6379", "note": "no auth locally"}},
    }
    shown = run_env(local_hub, "show", "local").stdout
    assert "    demo-api cache: redis://localhost:6379, note: no auth locally" in shown.splitlines()

    removed = run_env(local_hub, "service", "remove", "demo-api", "cache")

    assert (removed.exit_code, removed.stderr) == (0, ""), removed.output
    assert removed.stdout.splitlines() == ["hub.json: removed service demo-api cache", SYNC_HINT]
    assert snapshot(local_hub) == before

    mine = run_env(
        local_hub,
        "service",
        "add",
        "demo-api",
        "api",
        "--env",
        "jane-cloud",
        "--resource",
        "jane-api-fn",
        "--local",
    )
    assert (mine.exit_code, mine.stdout) == (1, ""), mine.output
    assert mine.stderr == "demo-api api already has an endpoint in jane-cloud\n"
    one = run_env(
        local_hub, "service", "remove", "demo-api", "api", "--env", "jane-cloud", "--local"
    )
    assert one.stdout.splitlines() == ["hub.local.json: removed endpoint demo-api api jane-cloud"]
    back = run_env(
        local_hub,
        "service",
        "add",
        "demo-api",
        "api",
        "--env",
        "jane-cloud",
        "--url",
        "https://api.jane.example.com",
        "--local",
    )
    assert (back.exit_code, back.stderr) == (0, ""), back.output
    local = json.loads((local_hub / "hub.local.json").read_bytes())
    assert local["repos"] == [
        {
            "dir": "demo-api",
            "services": {
                "api": {"endpoints": {"jane-cloud": {"url": "https://api.jane.example.com"}}}
            },
        }
    ]


def test_exits_one_when_service_env_undeclared(local_hub: Path) -> None:
    before = snapshot(local_hub)

    committed = run_env(
        local_hub,
        "service",
        "add",
        "demo-api",
        "cache",
        "--env",
        "qa",
        "--url",
        "redis://localhost:6379",
    )
    own = run_env(
        local_hub,
        "service",
        "add",
        "demo-api",
        "cache",
        "--env",
        "staging",
        "--url",
        "redis://localhost:6379",
        "--local",
    )
    unknown_repo = run_env(
        local_hub,
        "service",
        "add",
        "demo-web",
        "cache",
        "--env",
        "jane-cloud",
        "--url",
        "redis://localhost:6379",
        "--local",
    )

    for result in (committed, own, unknown_repo):
        assert (result.exit_code, result.stdout) == (1, ""), result.output
    assert committed.stderr.startswith("hub.json: repos[0].services.cache.endpoints")
    assert own.stderr.startswith("hub.local.json: repos[0].services.cache.endpoints.staging: ")
    # Refused before the local file's check: a dir not in hub.json is never written there.
    assert unknown_repo.stderr == "no repo demo-web in hub.json\n"
    assert snapshot(local_hub) == before


def test_exits_one_when_local_file_would_grow_too_large(hub: Path) -> None:
    # Just under the reader's 64 KiB: one more environment would make a file it refuses.
    environments: dict[str, Any] = {}
    while len(hub_bytes({"environments": environments})) < 65_536 - 150:
        environments[f"jane-{len(environments)}"] = {"access": "write", "description": "x" * 60}
    (hub / "hub.local.json").write_bytes(hub_bytes({"environments": environments}))
    assert len((hub / "hub.local.json").read_bytes()) < 65_536
    before = snapshot(hub)

    result = run_env(
        hub, "add", "jane-more", "--access", "write", "--description", "y" * 80, "--local"
    )

    assert (result.exit_code, result.stdout) == (1, ""), result.output
    assert result.stderr == "hub.local.json: $: larger than 65536 bytes once written\n"
    assert snapshot(hub) == before


def test_exits_one_when_local_file_unusable(hub: Path) -> None:
    (hub / "hub.local.json").write_bytes(b"{not json")
    before = snapshot(hub)

    for args in (("add", "qa", "--access", "ask"), ("list",)):
        result = run_env(hub, *args)

        assert (result.exit_code, result.stdout) == (1, ""), result.output
        assert result.stderr.startswith("hub.local.json: $: ")
    assert snapshot(hub) == before


def test_names_refusal_when_secret_repo_dir_or_comment_key_given(local_hub: Path) -> None:
    repo = run_env(
        local_hub,
        "service",
        "add",
        AWS_KEY,
        "cache",
        "--env",
        "jane-cloud",
        "--url",
        "http://localhost:1",
        "--local",
    )
    comment = run_env(local_hub, "add", "_x", "--access", "ask")

    assert repo.stderr == "no repo <name> in hub.json\n"
    assert comment.stderr == "_x: a name starting with _ is a comment key; choose another name\n"


def test_refuses_remove_when_local_file_tightens_environment(local_hub: Path) -> None:
    document = json.loads((local_hub / "hub.json").read_bytes())
    document["environments"]["qa"] = {"access": "ask"}
    (local_hub / "hub.json").write_bytes(hub_bytes(document))
    local = json.loads((local_hub / "hub.local.json").read_bytes())
    local["environments"]["qa"] = {"access": "read"}
    (local_hub / "hub.local.json").write_bytes(hub_bytes(local))
    before = snapshot(local_hub)

    result = run_env(local_hub, "remove", "qa")

    assert (result.exit_code, result.stdout) == (1, ""), result.output
    assert result.stderr == (
        "hub.local.json still holds qa; remove it there first: ./hub env remove qa --local\n"
    )
    assert snapshot(local_hub) == before


def test_says_local_file_refused_when_hub_json_change_breaks_it(local_hub: Path) -> None:
    before = snapshot(local_hub)

    result = run_env(local_hub, "set", "staging", "--access", "read")

    assert (result.exit_code, result.stdout) == (1, ""), result.output
    assert result.stderr == (
        "hub.json: not changed: hub.local.json would no longer be valid\n"
        "hub.local.json: environments.staging.access: may only tighten hub.json's read\n"
    )
    assert snapshot(local_hub) == before


def test_refuses_write_when_file_is_symlink(local_hub: Path, tmp_path: Path) -> None:
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    for name in ("hub.json", "hub.local.json"):
        (local_hub / name).rename(dotfiles / name)
        (local_hub / name).symlink_to(dotfiles / name)
    targets = snapshot(dotfiles)

    committed = run_env(local_hub, "add", "qa", "--access", "ask")
    own = run_env(local_hub, "add", "jane-box", "--access", "write", "--local")

    assert (committed.exit_code, committed.stdout) == (1, ""), committed.output
    assert committed.stderr == "hub.json: is a symlink; edit its target\n"
    assert (own.exit_code, own.stdout) == (1, ""), own.output
    assert own.stderr == "hub.local.json: is a symlink; edit its target\n"
    assert snapshot(dotfiles) == targets
    assert all((local_hub / name).is_symlink() for name in ("hub.json", "hub.local.json"))


def test_hides_secret_repo_dir_when_local_file_names_one(hub: Path) -> None:
    (hub / "hub.local.json").write_bytes(hub_bytes({"repos": [{"dir": AWS_KEY, "services": {}}]}))

    result = run_env(hub, "list")

    assert (result.exit_code, result.stdout) == (1, ""), result.output
    assert result.stderr == (
        'hub.local.json: repos[0].dir: repo dir "<name>" is not in hub.json\'s repos\n'
    )


ENV_FILE = "demo-api/environment/.env.test"


def test_writes_env_file_when_add_given_env_file(hub: Path) -> None:
    # AC-350.43: hub env add --env-file writes credentials.env_file in hub.json.
    document = json.loads((hub / "hub.json").read_bytes())

    result = run_env(hub, "add", "demo", "--access", "write", "--env-file", ENV_FILE)

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == ["hub.json: added environment demo", SYNC_HINT]
    document["environments"]["demo"] = {"access": "write", "credentials": {"env_file": ENV_FILE}}
    assert (hub / "hub.json").read_bytes() == hub_bytes(document)
    assert sorted(path.name for path in hub.iterdir()) == ["hub.json"]


def test_writes_local_env_file_when_set_local_env_file(local_hub: Path) -> None:
    # AC-350.43: hub env set --local --env-file writes it on the developer's own environment.
    local = json.loads((local_hub / "hub.local.json").read_bytes())
    hub_before = (local_hub / "hub.json").read_bytes()

    result = run_env(local_hub, "set", "jane-cloud", "--local", "--env-file", ENV_FILE)

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == ["hub.local.json: updated environment jane-cloud"]
    local["environments"]["jane-cloud"]["credentials"]["env_file"] = ENV_FILE
    assert (local_hub / "hub.local.json").read_bytes() == hub_bytes(local)
    assert (local_hub / "hub.json").read_bytes() == hub_before


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/etc/x", id="absolute"),
        pytest.param("../x", id="parent"),
        pytest.param("demo-api/../../x", id="inner_parent"),
        pytest.param("~/x", id="home"),
        pytest.param("a" * 201, id="201_chars"),
        pytest.param(AWS_KEY, id="aws_key"),
    ],
)
def test_refuses_env_file_when_path_unsafe(local_hub: Path, path: str) -> None:
    # AC-350.43: an unsafe path exits 1, changes nothing and is never echoed.
    before = snapshot(local_hub)

    added = run_env(local_hub, "add", "demo", "--access", "write", "--env-file", path)
    set_local = run_env(local_hub, "set", "jane-cloud", "--local", "--env-file", path)

    for result in (added, set_local):
        assert (result.exit_code, result.stdout) == (1, ""), result.output
        assert "credentials.env_file" in result.stderr
        assert path not in result.stderr
    assert snapshot(local_hub) == before


def test_writes_values_when_add_given_values(hub: Path) -> None:
    document = json.loads((hub / "hub.json").read_bytes())

    result = run_env(
        hub, "add", "demo", "--access", "write", "--value", "user_name=demo-user", "--value", "n=3"
    )

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    document["environments"]["demo"] = {
        "access": "write",
        "values": {"user_name": "demo-user", "n": "3"},
    }
    assert (hub / "hub.json").read_bytes() == hub_bytes(document)


def test_round_trips_own_values_when_local_sets_then_unsets_them(local_hub: Path) -> None:
    before = snapshot(local_hub)

    added = run_env(local_hub, "set", "local", "--local", "--value", "user_name=jane")
    written = json.loads((local_hub / "hub.local.json").read_bytes())
    shown = run_env(local_hub, "show", "local").stdout.splitlines()
    removed = run_env(local_hub, "set", "local", "--local", "--unset-value", "user_name")

    assert (added.exit_code, added.stderr) == (0, ""), added.output
    assert added.stdout.splitlines() == ["hub.local.json: updated environment local"]
    assert written["environments"]["local"] == {"values": {"user_name": "jane"}}
    assert "  values: user_name=jane" in shown
    assert (removed.exit_code, removed.stderr) == (0, ""), removed.output
    assert snapshot(local_hub) == before


def test_refuses_value_when_secret_shaped_or_not_a_pair(local_hub: Path) -> None:
    before = snapshot(local_hub)

    secret = run_env(local_hub, "set", "live", "--local", "--value", f"account_ref={AWS_KEY}")
    no_pair = run_env(local_hub, "set", "live", "--local", "--value", "user_name")

    assert (secret.exit_code, secret.stdout) == (1, ""), secret.output
    assert "values.account_ref" in secret.stderr
    assert AWS_KEY not in secret.stderr
    assert no_pair.exit_code == 2
    assert snapshot(local_hub) == before
