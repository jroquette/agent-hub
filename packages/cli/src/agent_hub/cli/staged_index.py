"""What git's index holds for the commit being made: the reads of ``hub doctor --staged``.

Run from the hub's ``.githooks/pre-commit``, inside the commit: git's own variables stay as the
hook got them, ``GIT_INDEX_FILE`` above all (``git commit <paths>`` builds a temporary index, and
that is what gets committed). Git runs in the hub root with no optional lock and literal
pathspecs, and nothing is read from the working tree: the staged paths come from ``git diff
--cached``, the entries from ``git ls-files --stage`` and the content from ``git cat-file
--batch``. A git that fails is an ``IndexReadError`` with its first error line.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, NamedTuple

from agent_hub.cli.child_process import run_child
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.core.doctor.staged_check import HUB_FILE, StagedIndex, staged_feature_folders
from agent_hub.core.hub_files.tree_snapshot import FileEntry, LinkEntry, TreeEntry

GIT_TIMEOUT: Final = 60
_REGULAR: Final = "100644"
_EXECUTABLE: Final = "100755"
_LINK: Final = "120000"


class IndexReadError(Exception):
    """Git could not tell what the index holds."""


class _Staged(NamedTuple):
    mode: str
    object_id: str
    path: str


def read_staged_index(root: Path, *, environ: Mapping[str, str]) -> StagedIndex:
    """The staged paths, and the index entries the staged checks read, of the hub at ``root``:
    ``hub.json``, each staged path and each file of the staged feature folders."""
    env = {**environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_LITERAL_PATHSPECS": "1"}
    names = _git(
        root, env, "diff", "--cached", "--name-only", "--no-renames", "-z", "--no-ext-diff"
    )
    staged = tuple(sorted({path for path in _split(names) if path}))
    if not staged:
        return StagedIndex(staged=(), entries={}, feature_files=())
    folders = staged_feature_folders(staged)
    # hub.json always: the staged checks read the config the commit will hold.
    listing = _git(root, env, "ls-files", "--stage", "-z", "--", HUB_FILE, *staged, *folders)
    found = [entry for entry in _entries(listing) if entry.mode in {_REGULAR, _EXECUTABLE, _LINK}]
    contents = _blobs(root, env, [entry.object_id for entry in found])
    entries: dict[str, TreeEntry] = {}
    for entry, content in zip(found, contents, strict=True):
        if entry.mode == _LINK:
            # A link is never followed; its target is the blob's text.
            target = content.decode("utf-8", errors="surrogateescape")
            entries[entry.path] = LinkEntry(target=target, outside=True)
        else:
            entries[entry.path] = FileEntry(executable=entry.mode == _EXECUTABLE, content=content)
    feature_files = tuple(sorted(path for path in entries if path.startswith(folders)))
    return StagedIndex(staged=staged, entries=entries, feature_files=feature_files)


def _entries(listing: bytes) -> list[_Staged]:
    """Each stage-0 entry of ``git ls-files --stage -z`` (an unmerged path has none)."""
    found = []
    for record in _split(listing):
        if not record:
            continue
        info, _, path = record.partition("\t")
        fields = info.split(" ")
        if len(fields) == 3 and fields[2] == "0":
            found.append(_Staged(mode=fields[0], object_id=fields[1], path=path))
    return found


def _blobs(root: Path, env: Mapping[str, str], object_ids: Sequence[str]) -> list[bytes]:
    """The content of each blob, in order, through one ``git cat-file --batch``."""
    if not object_ids:
        return []
    output = _git(root, env, "cat-file", "--batch", stdin="".join(f"{oid}\n" for oid in object_ids))
    contents = []
    at = 0
    for object_id in object_ids:
        end = output.find(b"\n", at)
        header = output[at:end].decode("ascii", errors="replace").split(" ")
        if end < 0 or len(header) != 3 or header[0] != object_id or header[1] != "blob":
            msg = f"git cat-file: unexpected answer for {object_id}"
            raise IndexReadError(msg)
        size = int(header[2])
        contents.append(output[end + 1 : end + 1 + size])
        at = end + 1 + size + 1
    return contents


def _split(output: bytes) -> list[str]:
    """NUL-separated git output as text; a name that is not UTF-8 keeps its bytes as escapes."""
    return output.decode("utf-8", errors="surrogateescape").split("\0")


def _git(root: Path, env: Mapping[str, str], *arguments: str, stdin: str | None = None) -> bytes:
    try:
        result = run_child(
            ["git", *arguments],
            cwd=root,
            env=env,
            timeout=GIT_TIMEOUT,
            stdin=None if stdin is None else stdin.encode("ascii"),
        )
    except ChildTimedOutError:
        msg = f"git {arguments[0]} timed out after {GIT_TIMEOUT} s"
        raise IndexReadError(msg) from None
    except OSError as error:
        msg = f"git could not run: {error.strerror or error}"
        raise IndexReadError(msg) from None
    if result.returncode != 0:
        lines = [line.strip() for line in result.stderr.decode(errors="replace").splitlines()]
        first = next((line for line in lines if line), f"exited {result.returncode}")
        msg = f"git {arguments[0]}: {first}"
        raise IndexReadError(msg)
    return result.stdout
