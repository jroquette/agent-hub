import os
from pathlib import Path

from agent_hub.generator.env_file_reader import env_file_keys


def _workspace(tmp_path: Path) -> tuple[str, Path]:
    hub = tmp_path / "demo-hub"
    repo = tmp_path / "demo-api"
    hub.mkdir()
    repo.mkdir()
    return str(hub), repo


def test_lists_names_only_when_file_is_in_a_declared_repo(tmp_path: Path) -> None:
    root, repo = _workspace(tmp_path)
    (repo / ".env.staging").write_text("DATABASE_URL=postgres://secret@db/app\nAPI_KEY=abc\n")

    found = env_file_keys(root, ["demo-api"], "demo-api/.env.staging")

    assert found.keys == ("DATABASE_URL", "API_KEY")
    assert found.holder == "demo-api"
    assert found.problem is None
    assert "secret" not in found.model_dump_json()


def test_reads_nothing_when_file_is_outside_the_hub_and_repos(tmp_path: Path) -> None:
    root, _repo = _workspace(tmp_path)
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / ".env").write_text("TOKEN=x\n")

    found = env_file_keys(root, ["demo-api"], "other/.env")

    assert found.keys == ()
    assert found.holder is None
    assert found.problem == "It is outside the hub and its repos."


def test_reads_nothing_when_a_link_leads_out(tmp_path: Path) -> None:
    root, repo = _workspace(tmp_path)
    (tmp_path / "outside.env").write_text("TOKEN=x\n")
    os.symlink(tmp_path / "outside.env", repo / ".env.link")

    found = env_file_keys(root, ["demo-api"], "demo-api/.env.link")

    assert found.keys == ()
    assert found.holder is None


def test_says_no_file_yet_when_file_is_missing(tmp_path: Path) -> None:
    root, _repo = _workspace(tmp_path)

    found = env_file_keys(root, ["demo-api"], "demo-api/.env.local")

    assert found.exists is False
    assert found.problem == "No file there yet."


def test_lists_nothing_when_file_is_over_the_cap(tmp_path: Path) -> None:
    root, repo = _workspace(tmp_path)
    (repo / ".env.big").write_bytes(b"A=" + b"x" * (64 * 1024) + b"\n")

    found = env_file_keys(root, ["demo-api"], "demo-api/.env.big")

    assert found.keys == ()
    assert found.problem == "It is too large to list (over 64 KiB)."


def test_lists_nothing_when_path_is_a_folder(tmp_path: Path) -> None:
    root, repo = _workspace(tmp_path)
    (repo / ".env.d").mkdir()

    found = env_file_keys(root, ["demo-api"], "demo-api/.env.d")

    assert found.problem == "It is not a regular file."


def test_reads_nothing_when_a_link_inside_the_repo_lies_on_the_path(tmp_path: Path) -> None:
    root, repo = _workspace(tmp_path)
    (repo / "config").mkdir()
    (repo / "config" / ".env.staging").write_text("TOKEN=x\n")
    os.symlink(repo / "config", repo / "env")

    found = env_file_keys(root, ["demo-api"], "demo-api/env/.env.staging")

    assert found.holder == "demo-api"
    assert found.keys == ()
    assert found.problem == "It is reached through a link."
