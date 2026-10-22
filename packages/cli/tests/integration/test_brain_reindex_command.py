"""``hub brain reindex``: one hub's knowledge rows dropped and rebuilt from its checkout
(AGH-391, ADR 0044: D-reindex, D-skipreport, D-fts5, D-hub).

Every run is in process, in a synthetic hub checkout (``knowledge_hub``: project ``demo``, the
repo ``demo-api`` beside it, both real git repos under ``tmp_path``). The database is the default
one under the test's own ``XDG_DATA_HOME`` (the cli conftest).
"""

import json
import os
import shutil
import sqlite3
import subprocess
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from typer.testing import Result

from agent_hub.cli.database_path import default_database_path
from agent_hub.cli.registry_path import default_registry_path
from agent_hub.core.json_form import dump_json
from agent_hub.storage import knowledge_index
from agent_hub.storage.hub_registry import JsonHubRegistry

pytestmark = pytest.mark.disable_socket

# The conftest's in-process run and hub factory (tests cannot import a conftest in importlib mode).
type CommandRunner = Callable[..., Result]
type KnowledgeHubFactory = Callable[..., Path]

MARKER = b"# Note\n\nmarker\n"
# The same number of bytes as MARKER, with another word.
EDITED = b"# Note\n\nzebras\n"
FTS5_LINE = (
    "hub brain reindex: this Python's SQLite has no FTS5 module; the knowledge index needs it\n"
)


def default_database() -> Path:
    return default_database_path(os.environ)


def rows_of(statement: str, *parameters: Any) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(default_database())) as connection:
        return connection.execute(statement, parameters).fetchall()


def hub_rows(hub: Path) -> list[tuple[Any, ...]]:
    """Every column of the hub's document rows, by path."""
    return rows_of(
        "SELECT * FROM knowledge_documents WHERE hub = ? ORDER BY path", str(hub.resolve())
    )


def hub_paths(hub: Path) -> list[str]:
    """The paths of the hub's document rows."""
    rows = rows_of(
        "SELECT path FROM knowledge_documents WHERE hub = ? ORDER BY path", str(hub.resolve())
    )
    return [path for (path,) in rows]


def paths_found(run_command: CommandRunner, hub: Path, word: str) -> list[str]:
    result = run_command(hub, "search", word, "--json")
    assert result.exit_code == 0, result.output
    return [found["path"] for found in json.loads(result.stdout)["results"]]


def other_hub(tmp_path: Path, demo: Path) -> Path:
    """A second hub, project ``other``, beside ``demo`` (it lists the same repo, so its index
    holds that repo's docs too), as a git repo holding one note with the word ``marker``."""
    other = tmp_path / "other-hub"
    (other / "brain").mkdir(parents=True)
    document = json.loads((demo / "hub.json").read_bytes())
    document["project"]["name"] = "other"
    (other / "hub.json").write_bytes(dump_json(document))
    (other / "brain" / "z.md").write_bytes(MARKER)
    git = shutil.which("git")
    assert git is not None
    subprocess.run(  # noqa: S603 - absolute git, fixed arguments, a tmp_path folder
        [git, "-c", "init.defaultBranch=main", "init", "-q"],
        cwd=other,
        check=True,
        capture_output=True,
    )
    return other


def test_rebuilds_only_named_hub_when_two_hubs_indexed(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner, tmp_path: Path
) -> None:
    demo = knowledge_hub({"brain/a.md": MARKER, "demo-api/docs/guide.md": MARKER})
    other = other_hub(tmp_path, demo)
    assert paths_found(run_command, demo, "marker") == ["brain/a.md", "demo-api/docs/guide.md"]
    assert paths_found(run_command, other, "marker") == ["brain/z.md", "demo-api/docs/guide.md"]
    other_before = hub_rows(other)
    # Same size, same mtime: a search does not see the edit, a reindex does.
    edited = demo / "brain" / "a.md"
    found = edited.stat()
    edited.write_bytes(EDITED)
    os.utime(edited, ns=(found.st_atime_ns, found.st_mtime_ns))
    assert paths_found(run_command, demo, "zebras") == []

    result = run_command(demo, "brain", "reindex")

    assert result.exit_code == 0, result.output
    assert result.stdout == "reindexed 2 files for demo (0 skipped)\n"
    assert result.stderr == ""
    assert paths_found(run_command, demo, "zebras") == ["brain/a.md"]
    assert paths_found(run_command, demo, "marker") == ["demo-api/docs/guide.md"]
    assert hub_rows(other) == other_before


def test_drops_rows_of_vanished_files_when_reindexed(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER, "brain/b.md": MARKER})
    assert paths_found(run_command, hub, "marker") == ["brain/a.md", "brain/b.md"]
    (hub / "brain" / "a.md").unlink()

    result = run_command(hub, "brain", "reindex")

    assert result.exit_code == 0, result.output
    assert result.stdout == "reindexed 1 files for demo (0 skipped)\n"
    assert hub_paths(hub) == ["brain/b.md"]


def secret_token() -> str:
    """A GitHub token shape r1 matches, built from parts so no literal is a token."""
    return "gh" + "p_" + "A1b2C3d4E5f6G7h8" * 2 + "xyzw"


def test_reports_secret_skip_again_when_reindexed(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = knowledge_hub(
        {
            "brain/_inbox/leak.md": f"# Leak\n\nmarker {secret_token()}\n".encode(),
            "brain/a.md": MARKER,
        }
    )
    skip_line = "skipped brain/_inbox/leak.md: matches a secret rule\n"
    first = run_command(hub, "search", "marker")
    second = run_command(hub, "search", "marker")

    result = run_command(hub, "brain", "reindex")

    assert first.stderr == f"hub search: {skip_line}"
    assert second.stderr == ""
    assert result.exit_code == 0, result.output
    assert result.stdout == "reindexed 1 files for demo (1 skipped)\n"
    assert result.stderr == f"hub brain reindex: {skip_line}"


def test_exits_one_when_sqlite_has_no_fts5(
    knowledge_hub: KnowledgeHubFactory,
    run_command: CommandRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER})
    monkeypatch.setattr(knowledge_index, "fts5_available", lambda *_: False)

    result = run_command(hub, "brain", "reindex")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == FTS5_LINE
    assert not default_database().exists()


def registered(tmp_path: Path, *hubs: Path) -> dict[str, str]:
    """``hubs`` in a ``hubs.json`` under the test's own config folder, and the environment that
    names that folder."""
    config = tmp_path / "config"
    registry = JsonHubRegistry(default_registry_path({"XDG_CONFIG_HOME": str(config)}))
    for hub in hubs:
        registry.add(str(hub))
    return {"XDG_CONFIG_HOME": str(config)}


def test_reindexes_registered_hub_when_hub_option_given(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner, tmp_path: Path
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER})
    env = registered(tmp_path, hub)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    result = run_command(elsewhere, "brain", "reindex", "--hub", "demo", env=env)

    assert result.exit_code == 0, result.output
    assert result.stdout == "reindexed 1 files for demo (0 skipped)\n"
    assert hub_paths(hub) == ["brain/a.md"]


def test_exits_one_when_hub_option_names_unknown_hub(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner, tmp_path: Path
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER})
    env = registered(tmp_path, hub)

    result = run_command(hub, "brain", "reindex", "--hub", "nope", env=env)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "hub brain reindex: no registered hub named nope\n"
    assert not default_database().exists()


def test_writes_index_to_database_when_db_option_given(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner, tmp_path: Path
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER})
    database = tmp_path / "given" / "index.db"

    result = run_command(hub, "brain", "reindex", "--db", str(database))

    assert result.exit_code == 0, result.output
    with closing(sqlite3.connect(database)) as connection:
        paths = connection.execute("SELECT path FROM knowledge_documents").fetchall()
    assert paths == [("brain/a.md",)]
    assert not default_database().exists()
