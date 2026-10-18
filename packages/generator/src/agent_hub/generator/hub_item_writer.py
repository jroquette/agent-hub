"""``FileSystemHubItemWriter``: the ``HubItemWriter`` port on a hub's folder (AGH-295, S4, D7).

The hub is opened once per call and every path is reached from that descriptor one folder at a
time with ``O_DIRECTORY | O_NOFOLLOW``, so a link on the way is refused (``link_in_path``) and
nothing is ever written through one or outside the unit's path. A unit's own name that is a
link is refused too. Missing folders above a unit are made (mode ``0o777`` less the umask).

A file (an agent, hook or workflow file, a hook's script) is written to ``.<name>.hub-tmp-<8
hex>`` beside it (``O_CREAT | O_EXCL | O_NOFOLLOW``, mode 0o600), given its final mode
(``0o777`` or ``0o666`` less the umask) and ``os.replace``d onto its name; on a failure the
temp file is removed.

A skill folder is swapped whole (no ``renameat2``): the version is staged at
``.<name>.hub-tmp-<8 hex>`` beside the target (the leftover shape ``tree_snapshot.TEMP_NAME``,
so ``hub doctor`` lists a crash's leftovers and the listing skips them); the target's hidden
entries, which no version records, are moved into the stage unchanged (never a name of the temp
shape; a hidden folder whole; a path the version writes wins); the target is renamed to a second
temp name, the stage renamed into place, and the old folder removed with ``rmtree(dir_fd=…)``.
Any failure before the stage is in place moves the hidden entries back, renames the old folder
back and removes the stage, so the unit is left as it was. A reader may find no folder between
the two renames. An old folder that cannot be removed afterwards stays as a leftover.

``EROFS``, ``EACCES`` and ``EPERM`` are ``ItemWriteRefusedError("hub_read_only")``, a link met
``ItemWriteRefusedError("link_in_path")``, any other failure ``HubItemWriteError``; no message
names a path.
"""

import contextlib
import errno
import os
import shutil
import stat
from collections.abc import Iterator, Sequence
from typing import Final

from agent_hub.core.errors import AgentHubError
from agent_hub.core.hub_files.tree_snapshot import is_leftover_name, temp_name
from agent_hub.core.item_versions.hub_item_writer import (
    HubItemWriteError,
    ItemWriteRefusedError,
    checked_unit_parts,
    plain_parts,
)
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.unit_content import UnitContent, UnitFile
from agent_hub.core.skills.skill_sources import DEFAULT_LIMITS

_ROOT_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY
_FOLDER_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_TEMP_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
_TEMP_MODE: Final = 0o600
_FOLDER_MODE: Final = 0o777
_READ_ONLY: Final = frozenset({errno.EROFS, errno.EACCES, errno.EPERM})
_NOT_FOLDER: Final = "the unit is not a folder"
_NOT_FILE: Final = "the unit is not a file"
_TOO_MANY: Final = "the folder holds too many names"


class _LinkMetError(Exception):
    """A component on the way is a link."""


class FileSystemHubItemWriter:
    """Writes units into hub folders on disk; behaves as ``HubItemWriterContract`` says."""

    def is_writable(self, hub_path: str, unit_paths: Sequence[str] = ()) -> bool:
        """Whether the hub folder and, for each path, its nearest existing folder (and the
        unit's own folder when it is one) can be written."""
        checked = [plain_parts(path) for path in unit_paths]
        if not os.access(hub_path, os.W_OK):
            return False
        try:
            with _opened_root(hub_path) as root:
                return all(_writable_along(root, parts) for parts in checked)
        except AgentHubError:
            return False

    def check_targets(self, hub_path: str, unit_paths: Sequence[str]) -> None:
        """Refuse a path one of whose existing components is a link."""
        checked = [plain_parts(path) for path in unit_paths]
        with _opened_root(hub_path) as root:
            for parts in checked:
                _check_components(root, parts)

    def write_unit(
        self, hub_path: str, unit_path: str, content: UnitContent, *, kind: UnitKind
    ) -> None:
        """Make the unit equal to ``content``: a file through a temp file, a folder swapped."""
        parts = checked_unit_parts(unit_path, kind)
        if kind is not UnitKind.SKILL and [file.path for file in content.files] != [parts[-1]]:
            msg = "a file unit holds one file named after it"
            raise ValueError(msg)
        umask = _umask()
        with _opened_root(hub_path) as root, _guarded(), _parent(root, parts) as parent:
            if kind is UnitKind.SKILL:
                _swap_folder(parent, parts[-1], content, umask=umask)
            else:
                file = content.files[0]
                _write_file(parent, parts[-1], file.content, mode=_mode(file, umask))

    def write_file(
        self, hub_path: str, path: str, content: bytes, *, executable: bool = False
    ) -> None:
        """Write the one file ``path`` through a temp file and a rename."""
        parts = plain_parts(path)
        mode = (0o777 if executable else 0o666) & ~_umask()
        with _opened_root(hub_path) as root, _guarded(), _parent(root, parts) as parent:
            _write_file(parent, parts[-1], content, mode=mode)

    def remove_unit(self, hub_path: str, unit_path: str, *, kind: UnitKind) -> None:
        """Remove the unit's file, or rename its folder aside and remove it; absent is fine."""
        parts = checked_unit_parts(unit_path, kind)
        with _opened_root(hub_path) as root, _guarded():
            try:
                parent = _descend(root, parts[:-1], create=False)
            except FileNotFoundError:
                return
            try:
                _remove(parent, parts[-1], folder=kind is UnitKind.SKILL)
            finally:
                os.close(parent)


@contextlib.contextmanager
def _opened_root(hub_path: str) -> Iterator[int]:
    """The hub folder, opened once for the call."""
    try:
        descriptor = os.open(hub_path, _ROOT_FLAGS)
    except OSError as error:
        raise _mapped(error) from None
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def _guarded() -> Iterator[None]:
    """Turn an ``OSError`` or a link met into the port's errors, naming no path."""
    try:
        yield
    except _LinkMetError:
        raise ItemWriteRefusedError("link_in_path") from None
    except OSError as error:
        raise _mapped(error) from None


def _mapped(error: OSError) -> AgentHubError:
    if error.errno in _READ_ONLY:
        return ItemWriteRefusedError("hub_read_only")
    if error.errno == errno.ELOOP:
        return ItemWriteRefusedError("link_in_path")
    return HubItemWriteError(error.strerror or "the write failed")


def _umask() -> int:
    # ``os`` has no umask getter: set it and put it back (as ``file_adapter`` does).
    umask = os.umask(0o022)
    os.umask(umask)
    return umask


def _mode(file: UnitFile, umask: int) -> int:
    return (0o777 if file.executable else 0o666) & ~umask


def _is_link(folder: int, name: str) -> bool:
    try:
        return stat.S_ISLNK(os.stat(name, dir_fd=folder, follow_symlinks=False).st_mode)
    except FileNotFoundError:
        return False


def _open_folder(name: str, parent: int) -> int:
    """``name`` under ``parent`` as a folder, never through a link (``_LinkMetError``)."""
    try:
        return os.open(name, _FOLDER_FLAGS, dir_fd=parent)
    except OSError as error:
        # A link fails with ELOOP (macOS) or ENOTDIR (Linux, with O_DIRECTORY).
        if error.errno in {errno.ELOOP, errno.ENOTDIR} and _is_link(parent, name):
            raise _LinkMetError from None
        raise


def _descend(base: int, segments: Sequence[str], *, create: bool) -> int:
    """A new descriptor of the folder ``segments`` below ``base``, each opened without
    following a link and, with ``create``, made when missing."""
    descriptor = os.dup(base)
    try:
        for segment in segments:
            try:
                child = _open_folder(segment, descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                with contextlib.suppress(FileExistsError):
                    os.mkdir(segment, _FOLDER_MODE, dir_fd=descriptor)
                child = _open_folder(segment, descriptor)
            os.close(descriptor)
            descriptor = child
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


@contextlib.contextmanager
def _folder(base: int, segments: Sequence[str], *, create: bool) -> Iterator[int]:
    """``_descend`` as a context: the descriptor is closed on leaving."""
    descriptor = _descend(base, segments, create=create)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def _parent(root: int, parts: Sequence[str]) -> contextlib.AbstractContextManager[int]:
    """The folder above the last of ``parts``, made when missing."""
    return _folder(root, parts[:-1], create=True)


def _check_components(root: int, parts: Sequence[str]) -> None:
    descriptor = os.dup(root)
    try:
        for segment in parts:
            try:
                status = os.stat(segment, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                return
            except OSError as error:
                raise _mapped(error) from None
            if stat.S_ISLNK(status.st_mode):
                raise ItemWriteRefusedError("link_in_path")
            if not stat.S_ISDIR(status.st_mode):
                return
            try:
                child = _open_folder(segment, descriptor)
            except _LinkMetError:
                raise ItemWriteRefusedError("link_in_path") from None
            except OSError as error:
                raise _mapped(error) from None
            os.close(descriptor)
            descriptor = child
    finally:
        os.close(descriptor)


def _writable_along(root: int, parts: Sequence[str]) -> bool:
    """Whether the deepest existing folder on the way to ``parts``' last name can be written,
    and, when that name is a folder, the folder too; the walk stops at a link
    (``check_targets`` refuses it) or at a name that is no folder."""
    held = [os.dup(root)]
    try:
        for segment in parts:
            try:
                held.append(_open_folder(segment, held[-1]))
            except _LinkMetError, OSError:
                break
        checked = held[-2:] if len(held) == len(parts) + 1 else held[-1:]
        return all(os.access(".", os.W_OK, dir_fd=descriptor) for descriptor in checked)
    finally:
        for descriptor in held:
            os.close(descriptor)


def _token() -> str:
    return os.urandom(4).hex()


def _write_file(folder: int, name: str, content: bytes, *, mode: int) -> None:
    if _is_link(folder, name):
        raise _LinkMetError
    temp = temp_name(name, _token())
    created = False
    try:
        descriptor = os.open(temp, _TEMP_FLAGS, _TEMP_MODE, dir_fd=folder)
        created = True
        with open(descriptor, "wb") as file:
            file.write(content)
            os.fchmod(file.fileno(), mode)
        os.replace(temp, name, src_dir_fd=folder, dst_dir_fd=folder)
    except BaseException:
        if created:
            with contextlib.suppress(OSError):
                os.unlink(temp, dir_fd=folder)
        raise


def _new_file(folder: int, name: str, content: bytes, *, mode: int) -> None:
    """A new file in a folder only this write sees (the stage): no temp file needed."""
    descriptor = os.open(name, _TEMP_FLAGS, _TEMP_MODE, dir_fd=folder)
    with open(descriptor, "wb") as file:
        file.write(content)
        os.fchmod(file.fileno(), mode)


def _swap_folder(parent: int, name: str, content: UnitContent, *, umask: int) -> None:
    exists = _folder_exists(parent, name)
    stage = temp_name(name, _token())
    old = temp_name(name, _token())
    os.mkdir(stage, _FOLDER_MODE, dir_fd=parent)
    moved: list[str] = []
    renamed = False
    try:
        with _folder(parent, [stage], create=False) as staged:
            for file in content.files:
                *folders, file_name = file.path.split("/")
                with _folder(staged, folders, create=True) as target:
                    _new_file(target, file_name, file.content, mode=_mode(file, umask))
            if exists:
                with _folder(parent, [name], create=False) as current:
                    _carry_hidden(current, staged, moved)
        if exists:
            os.rename(name, old, src_dir_fd=parent, dst_dir_fd=parent)
            renamed = True
        os.rename(stage, name, src_dir_fd=parent, dst_dir_fd=parent)
    except BaseException as error:
        _roll_back(
            parent, name, stage=stage, old=old if renamed else None, moved=moved, error=error
        )
        raise
    if exists:
        # The new folder is in place; an old one that cannot be removed stays as a leftover.
        with contextlib.suppress(OSError):
            shutil.rmtree(old, dir_fd=parent)


def _folder_exists(parent: int, name: str) -> bool:
    try:
        status = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(status.st_mode):
        raise _LinkMetError
    if not stat.S_ISDIR(status.st_mode):
        raise HubItemWriteError(_NOT_FOLDER)
    return True


def _hidden_entries(current: int) -> list[str]:
    """The hidden entries below the folder ``current`` (a hidden folder whole), never one of
    the temp shape, found through its plain folders without following a link, parents first."""
    found: list[str] = []
    budget = [DEFAULT_LIMITS.names_examined]

    def walk(folder: int, above: str) -> None:
        for entry_name in sorted(os.listdir(folder)):
            budget[0] -= 1
            if budget[0] < 0:
                raise HubItemWriteError(_TOO_MANY)
            if entry_name.startswith("."):
                if not is_leftover_name(entry_name):
                    found.append(f"{above}{entry_name}")
                continue
            status = os.stat(entry_name, dir_fd=folder, follow_symlinks=False)
            if stat.S_ISDIR(status.st_mode):
                child = _open_folder(entry_name, folder)
                try:
                    walk(child, f"{above}{entry_name}/")
                finally:
                    os.close(child)

    walk(current, "")
    return found


def _carry_hidden(current: int, staged: int, moved: list[str]) -> None:
    """Move each hidden entry of ``current`` to the same path in ``staged``, unless the version
    writes that path; each one moved is added to ``moved`` (for a roll back)."""
    for path in _hidden_entries(current):
        *folders, entry_name = path.split("/")
        with (
            _folder(current, folders, create=False) as source,
            _folder(staged, folders, create=True) as target,
        ):
            try:
                os.stat(entry_name, dir_fd=target, follow_symlinks=False)
            except FileNotFoundError:
                os.rename(entry_name, entry_name, src_dir_fd=source, dst_dir_fd=target)
                moved.append(path)


def _roll_back(
    parent: int,
    name: str,
    *,
    stage: str,
    old: str | None,
    moved: list[str],
    error: BaseException,
) -> None:
    """Put the old folder back under ``name`` with its hidden entries, and remove the stage;
    a step that fails is a note on ``error`` (naming no path), never masking it."""
    try:
        if old is not None:
            os.rename(old, name, src_dir_fd=parent, dst_dir_fd=parent)
        for path in reversed(moved):
            *folders, entry_name = path.split("/")
            with (
                _folder(parent, [stage, *folders], create=False) as source,
                _folder(parent, [name, *folders], create=False) as target,
            ):
                os.rename(entry_name, entry_name, src_dir_fd=source, dst_dir_fd=target)
    except (OSError, _LinkMetError) as failed:
        error.add_note(f"the old folder was not fully put back: {type(failed).__name__}")
        return
    try:
        shutil.rmtree(stage, dir_fd=parent)
    except OSError as failed:
        error.add_note(f"the stage was not removed: {type(failed).__name__}")


def _remove(parent: int, name: str, *, folder: bool) -> None:
    try:
        status = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(status.st_mode):
        raise _LinkMetError
    if not folder:
        if not stat.S_ISREG(status.st_mode):
            raise HubItemWriteError(_NOT_FILE)
        os.unlink(name, dir_fd=parent)
        return
    if not stat.S_ISDIR(status.st_mode):
        raise HubItemWriteError(_NOT_FOLDER)
    # Renamed aside first, so a removal that fails midway leaves no half folder at the name.
    aside = temp_name(name, _token())
    os.rename(name, aside, src_dir_fd=parent, dst_dir_fd=parent)
    with contextlib.suppress(OSError):
        shutil.rmtree(aside, dir_fd=parent)
