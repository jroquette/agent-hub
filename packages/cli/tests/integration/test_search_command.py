"""``hub search``: the hub's knowledge index brought up to date, then searched (AGH-391, ADR 0044).

Every run is in process, in a synthetic hub checkout (``knowledge_hub``: project ``demo``, the
repo ``demo-api`` beside it, both real git repos under ``tmp_path``). The database is the default
one under the test's own ``XDG_DATA_HOME`` (the cli conftest), unless a test names another.
"""

import faulthandler
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
from typer.testing import CliRunner, Result

from agent_hub.cli.database_path import default_database_path
from agent_hub.cli.main import app
from agent_hub.core.json_form import dump_json
from agent_hub.core.testing.builders import a_second_repo, an_event, events_to_jsonl
from agent_hub.storage import knowledge_index

pytestmark = pytest.mark.disable_socket

# The conftest's in-process run and hub factory (tests cannot import a conftest in importlib mode).
type CommandRunner = Callable[..., Result]
type KnowledgeHubFactory = Callable[..., Path]

DECISION = b"---\nstatus: accepted\n---\n# Worktrees from origin\n\nCreate worktrees from origin.\n"
PLAYBOOK = b"# Cleanup\n\nRemove old worktrees after the merge.\n"
UNRELATED = b"# Release\n\nTag the release.\n"


def ranked_hub(knowledge_hub: KnowledgeHubFactory) -> Path:
    """The spec's AC-391.1 hub: a decision titled after worktrees, a playbook naming them."""
    return knowledge_hub(
        {
            "brain/decisions/0001-worktrees.md": DECISION,
            "brain/playbooks/cleanup.md": PLAYBOOK,
            "brain/playbooks/release.md": UNRELATED,
        }
    )


def default_database() -> Path:
    """The database a run without ``--db`` or ``AGENT_HUB_DB`` uses, under the test's home."""
    return default_database_path(os.environ)


def json_of(result: Result) -> Any:
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_prints_ranked_blocks_when_words_match(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = ranked_hub(knowledge_hub)

    result = run_command(hub, "search", "worktrees")

    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "brain/decisions/0001-worktrees.md  decision  accepted\n"
        "Worktrees from origin\n"
        "# Worktrees from origin Create worktrees from origin.\n"
        "\n"
        "brain/playbooks/cleanup.md  playbook\n"
        "Cleanup\n"
        "# Cleanup Remove old worktrees after the merge.\n"
    )
    assert result.stderr == ""


def test_prints_json_object_when_json_option_given(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = ranked_hub(knowledge_hub)

    found = json_of(run_command(hub, "search", "worktrees", "--json"))

    assert found == {
        "hub": "demo",
        "query": "worktrees",
        "results": [
            {
                "path": "brain/decisions/0001-worktrees.md",
                "kind": "decision",
                "title": "Worktrees from origin",
                "status": "accepted",
                "provenance": None,
                "snippet": "# Worktrees from origin Create worktrees from origin.",
            },
            {
                "path": "brain/playbooks/cleanup.md",
                "kind": "playbook",
                "title": "Cleanup",
                "status": None,
                "provenance": None,
                "snippet": "# Cleanup Remove old worktrees after the merge.",
            },
        ],
        "sync": {"listed": 3, "read": 3, "indexed": 3, "dropped": 0},
        "skipped": [],
    }


def test_prints_json_object_with_one_line_snippets_when_body_long(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    lines = "".join(f"line {number} of the worktrees note\r\n" for number in range(200))
    hub = knowledge_hub({"brain/long.md": f"# Long\n\n{lines}".encode()})

    found = json_of(run_command(hub, "search", "worktrees", "--json"))

    (snippet,) = (result["snippet"] for result in found["results"])
    assert "worktrees" in snippet
    assert "\n" not in snippet
    assert "\r" not in snippet
    assert len(snippet) <= 160


def test_prints_no_results_line_when_nothing_matches(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = ranked_hub(knowledge_hub)

    result = run_command(hub, "search", "zebra")
    as_json = json_of(run_command(hub, "search", "zebra", "--json"))

    assert result.exit_code == 0, result.output
    assert result.stdout == "no results for zebra\n"
    assert as_json["results"] == []
    assert as_json["query"] == "zebra"


MARKER = b"# Note\n\nmarker\n"
# AC-391.3: one file holding the word in each folder, and the kind each one is given.
KIND_FILES = {
    "brain/decisions/0001-a.md": "decision",
    "brain/domain/a.md": "domain",
    "brain/learnings/a.md": "learning",
    "brain/playbooks/a.md": "playbook",
    "brain/system/a.md": "system",
    "brain/_inbox/a.md": "inbox",
    "brain/features/x/a.md": "feature",
    "brain/journal/2026/10/a.md": "journal",
    "brain/now.md": "doc",
    "demo-api/docs/adr/0001-a.md": "adr",
    "demo-api/docs/guide.md": "doc",
}
KINDS_LINE = (
    "hub search: unknown kind nope; the kinds are adr, decision, doc, domain, feature, inbox,"
    " journal, learning, playbook, system\n"
)


def test_names_kind_per_folder_when_marker_in_each(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = knowledge_hub(dict.fromkeys(KIND_FILES, MARKER))

    found = json_of(run_command(hub, "search", "marker", "--json"))

    assert {result["path"]: result["kind"] for result in found["results"]} == KIND_FILES


def test_keeps_listed_kinds_when_kind_option_repeated(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = knowledge_hub(dict.fromkeys(KIND_FILES, MARKER))

    found = json_of(
        run_command(hub, "search", "marker", "--kind", "feature", "--kind", "adr", "--json")
    )

    assert [result["path"] for result in found["results"]] == [
        "brain/features/x/a.md",
        "demo-api/docs/adr/0001-a.md",
    ]


def test_exits_two_when_kind_unknown(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER})

    result = run_command(hub, "search", "marker", "--kind", "feature", "--kind", "nope")

    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr == KINDS_LINE
    assert not default_database().exists()


def test_treats_fts_syntax_as_words_when_query_given(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = knowledge_hub(
        {
            "brain/both.md": b"# Both\n\na b or near and unclosed title foo\n",
            "brain/only-a.md": b"# Only\n\na\n",
        }
    )
    queries = ("a OR b", "NEAR(a b)", '"unclosed', "title:foo", "foo*", "-foo", "^foo", "a AND")

    # ``--`` ends the options, as in a shell, so ``-foo`` reaches the command as a query.
    found = {query: json_of(run_command(hub, "search", "--json", "--", query)) for query in queries}

    for query, answer in found.items():
        assert [result["path"] for result in answer["results"]] == ["brain/both.md"], query


@pytest.mark.parametrize("query", ["", "   ", "!!!", "("])
def test_exits_two_when_query_has_no_words(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner, query: str
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER})

    result = run_command(hub, "search", query)

    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr == "hub search: the query has no words\n"
    assert not default_database().exists()


def test_requires_every_word_when_query_has_several(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = knowledge_hub(
        {
            "brain/alpha.md": b"# One\n\nalpha\n",
            "brain/beta.md": b"# Two\n\nbeta\n",
            "brain/both.md": b"# Three\n\nbeta then alpha\n",
        }
    )

    found = json_of(run_command(hub, "search", "alpha", "beta", "--json"))

    assert [result["path"] for result in found["results"]] == ["brain/both.md"]
    assert found["query"] == "alpha beta"


def test_caps_query_results_when_sixty_match(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = knowledge_hub({f"brain/notes/{number:02}.md": MARKER for number in range(60)})

    result = run_command(hub, "search", "marker")

    assert result.exit_code == 0, result.output
    blocks = result.stdout.split("\n\n")
    assert len(blocks) == 50
    assert [block.split("\n")[0] for block in blocks] == [
        f"brain/notes/{number:02}.md  doc" for number in range(50)
    ]


def test_finds_inflected_word_when_query_singular(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = knowledge_hub({"brain/plural.md": b"# Plural\n\nTwo worktrees.\n"})

    found = json_of(run_command(hub, "search", "worktree", "--json"))

    assert [result["path"] for result in found["results"]] == ["brain/plural.md"]


def secret_token() -> str:
    """A GitHub token shape r1 matches, built from parts so no literal is a token."""
    return "gh" + "p_" + "A1b2C3d4E5f6G7h8" * 2 + "xyzw"


def database_bytes() -> bytes:
    """The default database's bytes, with its write-ahead log and shared memory when present."""
    database = default_database()
    parts = [database, database.with_name(database.name + "-wal")]
    parts.append(database.with_name(database.name + "-shm"))
    return b"".join(part.read_bytes() for part in parts if part.exists())


def sized(prefix: bytes, size: int) -> bytes:
    """``prefix`` padded with line breaks to exactly ``size`` bytes."""
    return prefix + b"\n" * (size - len(prefix))


def test_indexes_only_eligible_files_when_checkout_holds_others(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner, tmp_path: Path
) -> None:
    limit = 262_144
    hub = knowledge_hub(
        {
            ".gitignore": b"brain/ignored.md\n",
            "notes.md": MARKER,
            "brain/auto/workspace/me.md": MARKER,
            "brain/x.txt": MARKER,
            "brain/session.jsonl": b'{"type": "user", "message": "marker"}\n',
            "brain/big.md": sized(MARKER, limit + 1),
            "brain/exact.md": sized(MARKER, limit),
            "brain/latin.md": b"# Latin\n\nmarker caf\xe9\n",
            "brain/pipe.md": MARKER,
        }
    )
    outside = tmp_path / "outside"
    (outside / "folder").mkdir(parents=True)
    (outside / "target.md").write_bytes(MARKER)
    (outside / "folder" / "a.md").write_bytes(MARKER)
    brain = hub / "brain"
    (brain / "link.md").symlink_to(outside / "target.md")
    (brain / "linked").symlink_to(outside / "folder")
    (brain / "pipe.md").unlink()
    os.mkfifo(brain / "pipe.md")
    (brain / "ignored.md").write_bytes(MARKER)
    (brain / "untracked.md").write_bytes(MARKER)

    # A read that blocked on the FIFO would stop the test here, with a traceback.
    faulthandler.dump_traceback_later(60, exit=True)
    try:
        result = run_command(hub, "search", "marker", "--json")
    finally:
        faulthandler.cancel_dump_traceback_later()

    found = json_of(result)
    assert sorted(result["path"] for result in found["results"]) == [
        "brain/exact.md",
        "brain/untracked.md",
    ]
    assert found["skipped"] == [
        {"path": "brain/big.md", "reason": "larger than 256 KiB"},
        {"path": "brain/latin.md", "reason": "not UTF-8"},
        {"path": "brain/link.md", "reason": "reached through a link"},
        {"path": "brain/pipe.md", "reason": "not a regular file"},
    ]
    assert result.stderr == (
        "hub search: skipped brain/big.md: larger than 256 KiB\n"
        "hub search: skipped brain/latin.md: not UTF-8\n"
        "hub search: skipped brain/link.md: reached through a link\n"
        "hub search: skipped brain/pipe.md: not a regular file\n"
    )


def test_skips_file_when_secret_rule_matches(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = knowledge_hub(
        {
            "brain/_inbox/leak.md": f"# Leak\n\nmarker {secret_token()}\n".encode(),
            "brain/a.md": MARKER,
        }
    )

    result = run_command(hub, "search", "marker")

    assert result.exit_code == 0, result.output
    assert result.stdout == "brain/a.md  doc\nNote\n# Note marker\n"
    assert result.stderr == "hub search: skipped brain/_inbox/leak.md: matches a secret rule\n"
    assert secret_token().encode() not in database_bytes()


def test_reports_secret_skip_once_when_file_unchanged(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = knowledge_hub({"brain/_inbox/leak.md": f"marker {secret_token()}\n".encode()})

    first = run_command(hub, "search", "marker")
    second = run_command(hub, "search", "marker")

    assert first.stderr == "hub search: skipped brain/_inbox/leak.md: matches a secret rule\n"
    assert second.exit_code == 0, second.output
    assert second.stderr == ""
    assert second.stdout == "no results for marker\n"


def test_warns_and_goes_on_when_repo_not_checked_out(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = knowledge_hub({"demo-api/docs/guide.md": MARKER})
    document = json.loads((hub / "hub.json").read_bytes())
    document["repos"].append(a_second_repo())
    (hub / "hub.json").write_bytes(dump_json(document))

    result = run_command(hub, "search", "marker")

    assert result.exit_code == 0, result.output
    assert result.stderr == "hub search: demo-web: not checked out; its docs are not searched\n"
    assert result.stdout == "demo-api/docs/guide.md  doc\nNote\n# Note marker\n"


def test_exits_one_when_git_missing(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner, no_git_path: Path
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER})

    result = run_command(hub, "search", "marker", env={"PATH": str(no_git_path)})

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "hub search: git is not on PATH; install git\n"


def test_exits_one_when_git_fails_on_folder(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER})
    # Without its repo, git cannot list the brain: the ceiling keeps it from looking above.
    shutil.rmtree(hub / ".git")

    result = run_command(hub, "search", "marker")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.startswith("hub search: brain: git exited with 128: ")
    assert result.stderr.count("\n") == 1


def test_escapes_path_when_name_holds_line_break(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = knowledge_hub({"brain/a\nb.md": MARKER})

    result = run_command(hub, "search", "marker")

    assert result.exit_code == 0, result.output
    assert result.stdout == '"brain/a\\nb.md"  doc\nNote\n# Note marker\n'


def synced_hub(knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner) -> Path:
    """A hub of three notes, searched once."""
    hub = knowledge_hub({"brain/a.md": MARKER, "brain/b.md": MARKER, "brain/c.md": MARKER})
    assert json_of(run_command(hub, "search", "marker", "--json"))["sync"]["indexed"] == 3
    return hub


def sync_of(run_command: CommandRunner, hub: Path, *words: str) -> Any:
    return json_of(run_command(hub, "search", *words, "--json"))


def test_reads_nothing_when_sync_finds_no_change(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = synced_hub(knowledge_hub, run_command)

    found = sync_of(run_command, hub, "marker")

    assert found["sync"] == {"listed": 3, "read": 0, "indexed": 0, "dropped": 0}
    assert len(found["results"]) == 3


def test_reads_changed_file_when_sync_sees_new_size(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = synced_hub(knowledge_hub, run_command)
    (hub / "brain" / "b.md").write_bytes(b"# Note\n\nmarker and a giraffe\n")

    found = sync_of(run_command, hub, "giraffe")

    assert found["sync"] == {"listed": 3, "read": 1, "indexed": 1, "dropped": 0}
    assert [result["path"] for result in found["results"]] == ["brain/b.md"]


def test_updates_mtime_only_when_sync_sees_touch(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = synced_hub(knowledge_hub, run_command)
    touched = hub / "brain" / "c.md"
    later = touched.stat().st_mtime_ns + 5_000_000_000
    os.utime(touched, ns=(later, later))

    after_touch = sync_of(run_command, hub, "marker")
    next_one = sync_of(run_command, hub, "marker")

    assert after_touch["sync"] == {"listed": 3, "read": 1, "indexed": 0, "dropped": 0}
    assert next_one["sync"] == {"listed": 3, "read": 0, "indexed": 0, "dropped": 0}


def test_adds_and_drops_files_when_sync_sees_them(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = synced_hub(knowledge_hub, run_command)
    (hub / "brain" / "d.md").write_bytes(b"# New\n\nmarker\n")

    added = sync_of(run_command, hub, "marker")
    (hub / "brain" / "a.md").unlink()
    dropped = sync_of(run_command, hub, "marker")

    assert added["sync"] == {"listed": 4, "read": 1, "indexed": 1, "dropped": 0}
    assert "brain/d.md" in [result["path"] for result in added["results"]]
    assert dropped["sync"] == {"listed": 3, "read": 0, "indexed": 0, "dropped": 1}
    assert [result["path"] for result in dropped["results"]] == [
        "brain/b.md",
        "brain/c.md",
        "brain/d.md",
    ]


def test_searches_named_hub_when_hub_root_set(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner, tmp_path: Path
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    found = json_of(
        run_command(elsewhere, "search", "marker", "--json", env={"AGENT_HUB_ROOT": str(hub)})
    )

    assert found["hub"] == "demo"
    assert [result["path"] for result in found["results"]] == ["brain/a.md"]


def test_exits_two_when_no_hub_root_found(run_command: CommandRunner, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    result = run_command(elsewhere, "search", "marker")

    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr == (
        f"{elsewhere}: not a hub: no hub.json in this folder"
        " (hub search runs in the hub folder or through ./hub)\n"
    )
    assert not default_database().exists()


def test_indexes_main_checkout_when_run_in_worktree(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner, tmp_path: Path
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER, "demo-api/docs/guide.md": MARKER})
    worktree = tmp_path / "hub-task"
    subprocess.run(  # noqa: S603 - absolute git, fixed arguments, a tmp_path folder
        [shutil.which("git") or "git", "worktree", "add", "-q", "-b", "task", str(worktree)],
        cwd=hub,
        check=True,
        capture_output=True,
    )
    # Only in the worktree: the main checkout is the one indexed (owner, Q-2).
    (worktree / "brain" / "only-here.md").write_bytes(MARKER)

    from_worktree = json_of(run_command(worktree, "search", "marker", "--json"))
    from_checkout = json_of(run_command(hub, "search", "marker", "--json"))

    assert [result["path"] for result in from_worktree["results"]] == [
        "brain/a.md",
        "demo-api/docs/guide.md",
    ]
    assert from_worktree["sync"] == {"listed": 2, "read": 2, "indexed": 2, "dropped": 0}
    assert from_checkout["sync"] == {"listed": 2, "read": 0, "indexed": 0, "dropped": 0}


def test_exits_one_when_hub_json_invalid(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER})
    (hub / "hub.json").write_bytes(b"{not json")

    result = run_command(hub, "search", "marker")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.startswith("hub.json: ")
    assert not default_database().exists()


def rows_of(database: Path, statement: str) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute(statement).fetchall()


@pytest.mark.parametrize("given", ["option", "variable", "default"])
def test_writes_index_to_database_when_db_option_or_variable_given(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner, tmp_path: Path, *, given: str
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER})
    database = {
        "option": tmp_path / "given" / "option.db",
        "variable": tmp_path / "given" / "variable.db",
        "default": default_database(),
    }[given]
    options = ["--db", str(database)] if given == "option" else []
    env = {"AGENT_HUB_DB": str(database)} if given == "variable" else None

    searched = run_command(hub, "search", "marker", *options, env=env)
    collected = CliRunner().invoke(
        app, ["collect", *options], input=events_to_jsonl([an_event()]), env=env
    )

    assert searched.exit_code == 0, searched.output
    assert collected.exit_code == 0, collected.output
    assert rows_of(database, "SELECT path FROM knowledge_documents") == [("brain/a.md",)]
    assert rows_of(database, "SELECT count(*) FROM events") == [(1,)]
    assert rows_of(database, "SELECT version_num FROM alembic_version") == [("0008",)]


def test_exits_one_when_database_unusable(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner, tmp_path: Path
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER})
    blocker = tmp_path / "a-file"
    blocker.write_bytes(b"not a folder\n")

    result = run_command(hub, "search", "marker", "--db", str(blocker / "index.db"))

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.startswith("hub search: cannot create the directory of the database ")
    assert result.stderr.count("\n") == 1


def test_exits_one_when_sqlite_has_no_fts5(
    knowledge_hub: KnowledgeHubFactory,
    run_command: CommandRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER})
    monkeypatch.setattr(knowledge_index, "fts5_available", lambda *_: False)

    result = run_command(hub, "search", "marker")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        "hub search: this Python's SQLite has no FTS5 module; the knowledge index needs it\n"
    )
    assert not default_database().exists()
