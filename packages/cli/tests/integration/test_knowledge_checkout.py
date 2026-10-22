"""The hub checkout as the knowledge index sees it: git's listing of each source, walked
without following a link, and each file read within its bounds (AGH-391 P-7, AM-1, AM-2)."""

import errno
import faulthandler
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.knowledge import document_rules
from agent_hub.core.knowledge.knowledge_index import Fingerprint
from agent_hub.core.knowledge.sync_knowledge import KnowledgeCheckoutError, sync_knowledge
from agent_hub.core.knowledge.sync_plan import ListedFile
from agent_hub.core.testing.knowledge_fakes import InMemoryKnowledgeIndex
from agent_hub.hub_git import knowledge_checkout
from agent_hub.hub_git.knowledge_checkout import GitKnowledgeCheckout

type KnowledgeHubFactory = Callable[..., Path]

NOTE = b"# Note\n\nmarker\n"
# Git looks for a repository no higher than these folders.
CEILING = "GIT_CEILING_DIRECTORIES"


def a_checkout(hub: Path, repos: tuple[str, ...] = ("demo-api",)) -> GitKnowledgeCheckout:
    git = shutil.which("git")
    assert git is not None, "git is needed for a synthetic checkout"
    return GitKnowledgeCheckout(hub, repos, git=os.path.abspath(git), environ=dict(os.environ))


def listed_as_found(root: Path, paths: Mapping[str, str]) -> tuple[ListedFile, ...]:
    """Each hub path, with the fingerprint ``lstat`` gives its file under ``root``."""
    found = []
    for path, on_disk in sorted(paths.items()):
        status = os.lstat(root / on_disk)
        fingerprint = Fingerprint(size=status.st_size, mtime_ns=status.st_mtime_ns)
        found.append(ListedFile(path=path, fingerprint=fingerprint))
    return tuple(found)


def test_lists_markdown_under_sources_when_git_lists_them(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    hub = knowledge_hub(
        {
            ".gitignore": b"brain/ignored.md\n",
            "notes.md": NOTE,
            "brain/decisions/0001-choice.md": NOTE,
            "brain/auto/workspace/mine.md": NOTE,
            "brain/AUTO/upper.md": NOTE,
            "brain/playbooks/steps.txt": NOTE,
            "demo-api/notes.md": NOTE,
            "demo-api/docs/guide.md": NOTE,
            "demo-api/docs/adr/0001-store.md": NOTE,
        }
    )
    (hub / "brain" / "_inbox").mkdir()
    (hub / "brain" / "_inbox" / "fresh.md").write_bytes(NOTE)
    (hub / "brain" / "ignored.md").write_bytes(NOTE)

    listed = a_checkout(hub).listed()

    assert listed == listed_as_found(
        tmp_path,
        {
            "brain/_inbox/fresh.md": "hub/brain/_inbox/fresh.md",
            "brain/decisions/0001-choice.md": "hub/brain/decisions/0001-choice.md",
            "demo-api/docs/adr/0001-store.md": "demo-api/docs/adr/0001-store.md",
            "demo-api/docs/guide.md": "demo-api/docs/guide.md",
        },
    )


def test_raises_checkout_error_when_git_fails_on_folder(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    hub = knowledge_hub({"brain/note.md": NOTE}, repos=())
    # Beside the hub, a folder that is no repo of its own. Above it stands a repo git would take
    # for the folder's but for the ceiling the checkout sets (the caller's own is left out).
    (tmp_path / "demo-api" / "docs").mkdir(parents=True)
    (tmp_path / "demo-api" / "docs" / "guide.md").write_bytes(NOTE)
    git = shutil.which("git")
    assert git is not None
    environ = {name: value for name, value in os.environ.items() if name != CEILING}
    subprocess.run(  # noqa: S603 - absolute git, fixed arguments, a tmp_path folder
        [git, "init", "-q", str(tmp_path)], env=environ, check=True, capture_output=True
    )
    checkout = GitKnowledgeCheckout(hub, ("demo-api",), git=git, environ=environ)

    with pytest.raises(KnowledgeCheckoutError, match=r"^demo-api/docs: git exited with 128"):
        checkout.listed()


def test_stops_when_listing_over_file_cap(
    knowledge_hub: KnowledgeHubFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = knowledge_hub(
        {
            "brain/one.md": NOTE,
            "brain/two.md": NOTE,
            "demo-api/docs/three.md": NOTE,
            "demo-api/docs/four.md": NOTE,
        }
    )
    monkeypatch.setattr(document_rules, "MAX_LISTED_FILES", 3)
    index = InMemoryKnowledgeIndex()
    line = "4 Markdown files under the hub's sources, more than 3; nothing was indexed"

    with pytest.raises(KnowledgeCheckoutError) as listing:
        a_checkout(hub).listed()
    with pytest.raises(KnowledgeCheckoutError) as raised:
        sync_knowledge(index, a_checkout(hub), "demo")

    assert str(listing.value) == line
    assert str(raised.value) == line
    assert index.stored("demo").files == {}


def test_lists_nothing_from_repo_when_not_checked_out(knowledge_hub: KnowledgeHubFactory) -> None:
    hub = knowledge_hub({"brain/note.md": NOTE}, repos=())
    checkout = a_checkout(hub, repos=("demo-api",))

    assert [file.path for file in checkout.listed()] == ["brain/note.md"]
    assert checkout.not_checked_out() == ("demo-api",)


def test_raises_checkout_error_when_listing_longer_than_limit(
    knowledge_hub: KnowledgeHubFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = knowledge_hub({"brain/one.md": NOTE, "brain/two.md": NOTE})
    monkeypatch.setattr(document_rules, "MAX_LISTING_BYTES", 16)

    with pytest.raises(KnowledgeCheckoutError, match=re.escape("brain: git listed more than 16")):
        a_checkout(hub).listed()


def lstat_fingerprint(path: Path | bytes) -> Fingerprint:
    status = os.lstat(path)
    return Fingerprint(size=status.st_size, mtime_ns=status.st_mtime_ns)


def test_reports_link_and_fifo_when_listed(
    knowledge_hub: KnowledgeHubFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    large = b"x" * (document_rules.MAX_DOCUMENT_BYTES + 1)
    hub = knowledge_hub(
        {
            "brain/real.md": NOTE,
            "brain/pipe.md": NOTE,
            "brain/large.md": large,
            "brain/folder/inner.md": NOTE,
            "brain/elsewhere/inner.md": NOTE,
        }
    )
    brain = hub / "brain"
    (brain / "link.md").symlink_to("real.md")
    shutil.rmtree(brain / "folder")
    (brain / "folder").symlink_to("elsewhere")
    (brain / "pipe.md").unlink()
    os.mkfifo(brain / "pipe.md")
    checkout = a_checkout(hub)
    reads: list[str] = []

    def recorded(folder: int, name: str, *, limit: int) -> bytes:
        reads.append(name)
        return b""

    monkeypatch.setattr(knowledge_checkout, "read_regular", recorded)

    listed = {file.path: file for file in checkout.listed()}

    assert listed["brain/link.md"] == ListedFile(
        path="brain/link.md",
        fingerprint=lstat_fingerprint(brain / "link.md"),
        skip_reason=document_rules.THROUGH_LINK,
    )
    assert listed["brain/folder/inner.md"] == ListedFile(
        path="brain/folder/inner.md", skip_reason=document_rules.THROUGH_LINK
    )
    assert listed["brain/pipe.md"] == ListedFile(
        path="brain/pipe.md",
        fingerprint=lstat_fingerprint(brain / "pipe.md"),
        skip_reason=document_rules.NOT_REGULAR,
    )
    assert listed["brain/large.md"] == ListedFile(
        path="brain/large.md",
        fingerprint=Fingerprint(size=len(large), mtime_ns=os.lstat(brain / "large.md").st_mtime_ns),
        skip_reason=document_rules.TOO_LARGE,
    )
    assert listed["brain/real.md"].skip_reason is None
    assert listed["brain/elsewhere/inner.md"].skip_reason is None
    assert reads == []


def test_reads_without_blocking_when_file_is_fifo(knowledge_hub: KnowledgeHubFactory) -> None:
    hub = knowledge_hub({"brain/pipe.md": NOTE, "brain/real.md": NOTE})
    (hub / "brain" / "pipe.md").unlink()
    os.mkfifo(hub / "brain" / "pipe.md")
    checkout = a_checkout(hub)

    faulthandler.dump_traceback_later(5, exit=True)
    try:
        answer = checkout.read("brain/pipe.md")
    finally:
        faulthandler.cancel_dump_traceback_later()

    assert answer == document_rules.NOT_REGULAR
    assert checkout.read("brain/real.md") == NOTE


def test_reads_nothing_through_link_when_folder_replaced(
    knowledge_hub: KnowledgeHubFactory,
) -> None:
    hub = knowledge_hub({"brain/folder/inner.md": NOTE, "brain/elsewhere/inner.md": NOTE})
    shutil.rmtree(hub / "brain" / "folder")
    (hub / "brain" / "folder").symlink_to("elsewhere")
    checkout = a_checkout(hub)

    assert checkout.read("brain/folder/inner.md") == document_rules.THROUGH_LINK
    assert checkout.read("brain/../brain/elsewhere/inner.md") is None
    assert checkout.read("brain/gone.md") is None
    assert checkout.read("demo-api/docs/gone.md") is None


def test_reads_repo_docs_when_listed(knowledge_hub: KnowledgeHubFactory) -> None:
    hub = knowledge_hub({"demo-api/docs/adr/0001-store.md": NOTE})

    assert a_checkout(hub).read("demo-api/docs/adr/0001-store.md") == NOTE


def test_reads_at_most_one_byte_over_limit_when_file_grew(
    knowledge_hub: KnowledgeHubFactory,
) -> None:
    hub = knowledge_hub({"brain/grown.md": NOTE})
    checkout = a_checkout(hub)
    (hub / "brain" / "grown.md").write_bytes(b"y" * (document_rules.MAX_DOCUMENT_BYTES + 10))

    answer = checkout.read("brain/grown.md")

    assert answer == b"y" * (document_rules.MAX_DOCUMENT_BYTES + 1)


def test_skips_name_when_not_utf8(knowledge_hub: KnowledgeHubFactory) -> None:
    hub = knowledge_hub({"brain/fine.md": NOTE})
    bad = os.fsencode(hub / "brain") + b"/bad\xff.md"
    with open(bad, "wb") as file:
        file.write(NOTE)

    listed = {file.path: file for file in a_checkout(hub).listed()}

    assert listed["brain/bad\\xff.md"] == ListedFile(
        path="brain/bad\\xff.md",
        fingerprint=lstat_fingerprint(bad),
        skip_reason=document_rules.NOT_UTF8,
    )
    assert listed["brain/fine.md"].skip_reason is None


def test_reports_unreadable_when_open_fails(
    knowledge_hub: KnowledgeHubFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = knowledge_hub({"brain/decisions/0001-choice.md": NOTE, "brain/note.md": NOTE})
    checkout = a_checkout(hub)
    real_open = os.open

    def open_failing_on_decisions(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if os.fsencode(path) == b"decisions" and flags & os.O_DIRECTORY:
            raise OSError(errno.EMFILE, os.strerror(errno.EMFILE))
        return real_open(path, flags, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(os, "open", open_failing_on_decisions)
        listed = {file.path: file for file in checkout.listed()}
        read_through_failing_folder = checkout.read("brain/decisions/0001-choice.md")

    assert listed["brain/decisions/0001-choice.md"] == ListedFile(
        path="brain/decisions/0001-choice.md", skip_reason=document_rules.UNREADABLE
    )
    assert listed["brain/note.md"].skip_reason is None
    assert read_through_failing_folder == document_rules.UNREADABLE

    def refused(folder: int, name: str, *, limit: int) -> bytes:
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES))

    monkeypatch.setattr(knowledge_checkout, "read_regular", refused)
    assert checkout.read("brain/note.md") == document_rules.UNREADABLE

    def vanished(folder: int, name: str, *, limit: int) -> bytes:
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT))

    monkeypatch.setattr(knowledge_checkout, "read_regular", vanished)
    assert checkout.read("brain/note.md") is None


def test_reports_unreadable_when_read_fails_inside_reader(
    knowledge_hub: KnowledgeHubFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = knowledge_hub({"brain/note.md": NOTE})
    checkout = a_checkout(hub)
    # The shared reader turns an I/O error into its message: still a read that failed.
    monkeypatch.setattr(
        knowledge_checkout, "read_regular", lambda folder, name, *, limit: "Input/output error"
    )

    assert checkout.read("brain/note.md") == document_rules.UNREADABLE


def test_names_last_stderr_line_when_git_fails(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    hub = knowledge_hub({"brain/note.md": NOTE}, repos=())
    failing = tmp_path / "failing-git"
    failing.write_text(
        "#!/bin/sh\nprintf 'first line\\n\\nlast\\t%s\\n\\n' \"$(printf 'y%.0s' $(seq 300))\" >&2\n"
        "exit 3\n",
        encoding="utf-8",
    )
    failing.chmod(0o755)
    checkout = GitKnowledgeCheckout(hub, (), git=str(failing), environ=dict(os.environ))

    with pytest.raises(KnowledgeCheckoutError) as raised:
        checkout.listed()

    # The last line, cut to 200 characters, then escaped: the tab shows as ``\t``.
    assert str(raised.value) == "brain: git exited with 3: last\\t" + "y" * 195


def test_keeps_utf8_name_when_undecodable_name_shows_same(
    knowledge_hub: KnowledgeHubFactory,
) -> None:
    hub = knowledge_hub({"brain/fine.md": NOTE})
    brain = os.fsencode(hub / "brain")
    literal = brain + b"/same\\xff.md"
    with open(literal, "wb") as file:
        file.write(b"# Literal\n")
    with open(brain + b"/same\xff.md", "wb") as file:
        file.write(NOTE)

    listed = [file for file in a_checkout(hub).listed() if file.path.startswith("brain/same")]

    assert listed == [ListedFile(path="brain/same\\xff.md", fingerprint=lstat_fingerprint(literal))]


def test_keeps_tracked_utf8_name_when_untracked_undecodable_name_listed_first(
    knowledge_hub: KnowledgeHubFactory,
) -> None:
    # git prints untracked names before tracked ones: the undecodable name comes first here.
    hub = knowledge_hub({"brain/fine.md": NOTE, "brain/same\\xff.md": b"# Literal\n"})
    brain = os.fsencode(hub / "brain")
    with open(brain + b"/same\xff.md", "wb") as file:
        file.write(NOTE)

    listed = [file for file in a_checkout(hub).listed() if file.path.startswith("brain/same")]

    literal = brain + b"/same\\xff.md"
    assert listed == [ListedFile(path="brain/same\\xff.md", fingerprint=lstat_fingerprint(literal))]


def test_counts_files_as_gone_when_file_replaced_folder(
    knowledge_hub: KnowledgeHubFactory,
) -> None:
    hub = knowledge_hub({"brain/folder/inner.md": NOTE, "brain/note.md": NOTE})
    shutil.rmtree(hub / "brain" / "folder")
    (hub / "brain" / "folder").write_bytes(NOTE)
    checkout = a_checkout(hub)

    assert [file.path for file in checkout.listed()] == ["brain/note.md"]
    assert checkout.read("brain/folder/inner.md") is None


def test_raises_checkout_error_when_source_folder_cannot_open(
    knowledge_hub: KnowledgeHubFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = knowledge_hub({"brain/note.md": NOTE}, repos=())
    checkout = a_checkout(hub, repos=())
    real_open = os.open

    def open_failing_on_hub(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if os.fsdecode(path) == str(hub) and flags & os.O_DIRECTORY:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_failing_on_hub)

    with pytest.raises(KnowledgeCheckoutError) as raised:
        checkout.listed()

    assert str(raised.value) == f"brain: the folder cannot be opened: {os.strerror(errno.EACCES)}"
