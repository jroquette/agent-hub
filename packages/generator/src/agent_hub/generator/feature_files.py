"""Read a hub's feature folders, ``brain/features/<slug>/`` (D23), for the control plane.

Bounded and never through a link: each folder on the way (``brain``, ``features``, the slug) is
opened relative to its parent with ``O_NOFOLLOW``, so a linked folder is skipped; a slug starting
with ``.`` is skipped, as a shell glob does, and at most ``MAX_FEATURE_FOLDERS`` are read, in name
order. In each folder only the record files are looked at, as regular files: ``features.json``
whole up to ``MAX_RECORD_BYTES`` (else a one-line problem), ``plan.md`` whole up to
``MAX_PLAN_BYTES`` (else ``plan_too_large``), ``spec.md`` and ``eval.md`` up to ``HEAD_BYTES``; the
other record files are only checked as regular files, never read. What the files mean is core's
(``feature_status``).

The record folders ``evals/`` and ``reviews/`` are opened the same way, relative to the slug's
folder: in each, the ``.md`` names not hidden are read in name order, at most ``MAX_EVAL_FILES``
and ``MAX_REVIEW_FILES``, as the first ``EVAL_HEAD_BYTES`` / ``REVIEW_HEAD_BYTES``. A link, a
folder or another non-regular file is listed with its problem, never read; the files left out by
the cap, and the names that are not UTF-8, are counted in ``evals_skipped`` (for ``reviews/``
they are left out uncounted).
A linked or missing record folder reads as empty: at most ``MAX_EVAL_FILES`` and
``MAX_REVIEW_FILES`` names are kept while listing (the smallest by name), the rest only counted.
The folder's own ``ux-*.md`` designs are read the same way, at most ``MAX_UX_FILES``, as their
first ``UX_HEAD_BYTES`` (``ux_skipped`` counts the rest). In ``reviews/``, the first
``MAX_ROUND_TICKETS`` ticket folders by name (not hidden, UTF-8 names, never a link) are opened
the same way, and only the names of their review rounds are kept: regular files named as the
review check names them (``<reviewer>-r<N>.json``), at most ``MAX_ROUND_NAMES`` in all, never
read. Each ticket folder opened counts ``FOLDER_COST_BYTES`` against the read budget.

One call reads at most about ``READ_BUDGET_BYTES``: a folder is read only while the bytes read so
far are under it, so the total goes over by one folder at most (11,067,394 bytes, about 10.6 MiB:
``features.json`` 1 MiB + 1, ``plan.md`` 256 KiB + 1, two 64 KiB heads, 200 eval heads of 16 KiB,
500 review heads of 8 KiB, 50 UX design heads of 4 KiB and 500 ticket folders of 4 KiB); each
folder past it is listed with ``OVER_BUDGET`` as its record problem and files unread.
``read_feature_folder`` reads the one folder a slug names, as the listing would, and nothing else.
"""

import contextlib
import heapq
import os
import stat
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Final

from agent_hub.core.features.feature_evals import (
    EVAL_HEAD_BYTES,
    EVALS_FOLDER,
    MAX_EVAL_FILES,
    NOTE_SUFFIX,
)
from agent_hub.core.features.feature_record import MAX_RECORD_BYTES
from agent_hub.core.features.feature_reviews import (
    MAX_REVIEW_FILES,
    MAX_ROUND_NAMES,
    MAX_ROUND_TICKETS,
    REVIEW_HEAD_BYTES,
    REVIEWS_FOLDER,
)
from agent_hub.core.features.feature_status import (
    EVAL,
    HEAD_BYTES,
    MAX_PLAN_BYTES,
    MAX_UX_FILES,
    PLAN,
    RECORD,
    RECORD_FILES,
    SPEC,
    UX_HEAD_BYTES,
    UX_PREFIX,
    FeatureFolder,
    RecordHead,
)
from agent_hub.core.features.review_output_checks import is_review_round
from agent_hub.generator.regular_files import read_regular

MAX_FEATURE_FOLDERS: Final = 500
READ_BUDGET_BYTES: Final = 32 * 1_048_576
OVER_BUDGET: Final = f"not read: the feature folders read are over {READ_BUDGET_BYTES} bytes"
# What opening one ticket folder of ``reviews/`` costs against the read budget: a block read.
FOLDER_COST_BYTES: Final = 4096
FEATURES_PATH: Final = ("brain", "features")
_FOLDER_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class _Meter:
    """The bytes read so far by one call."""

    def __init__(self) -> None:
        self.read = 0

    def add(self, read: bytes | str | None) -> bytes | str | None:
        if isinstance(read, bytes):
            self.read += len(read)
        return read


def read_feature_folders(hub_root: Path) -> tuple[FeatureFolder, ...]:
    """Every feature folder of the hub at ``hub_root``; none when ``brain/features`` is absent.

    Folders past ``READ_BUDGET_BYTES`` are listed unread, with ``OVER_BUDGET`` as their problem.
    """
    meter = _Meter()
    with _features_folder(hub_root) as folder:
        if folder is None:
            return ()
        return tuple(
            _read_folder(folder, slug, meter)
            if meter.read < READ_BUDGET_BYTES
            else FeatureFolder(slug=slug, files=(), features_json=OVER_BUDGET)
            for slug in _slugs(folder)
        )


def read_feature_folder(hub_root: Path, slug: str) -> FeatureFolder | None:
    """The feature folder ``slug`` names, read as ``read_feature_folders`` reads it; None when
    there is no such folder (absent, hidden, a link, not a folder, or not a single name)."""
    if not slug or slug.startswith(".") or "/" in slug or "\0" in slug:
        return None
    with _features_folder(hub_root) as folder:
        if folder is None or not _is_folder(folder, slug):
            return None
        return _read_folder(folder, slug, _Meter())


@contextlib.contextmanager
def _features_folder(hub_root: Path) -> Iterator[int | None]:
    opened: list[int] = []
    try:
        parent = os.open(hub_root, os.O_RDONLY | os.O_DIRECTORY)
        opened.append(parent)
        for name in FEATURES_PATH:
            parent = os.open(name, _FOLDER_FLAGS, dir_fd=parent)
            opened.append(parent)
    except OSError:
        yield None
    else:
        yield parent
    finally:
        for descriptor in opened:
            os.close(descriptor)


def _slugs(folder: int) -> list[str]:
    slugs: list[str] = []
    for name in sorted(os.listdir(folder)):
        if len(slugs) >= MAX_FEATURE_FOLDERS:
            break
        if not name.startswith(".") and _is_folder(folder, name):
            slugs.append(name)
    return slugs


def _is_folder(parent: int, name: str) -> bool:
    try:
        return stat.S_ISDIR(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode)
    except OSError:
        return False


def _limit(name: str) -> int:
    """How much of the record file ``name`` is read: the record whole (one byte more, to see it
    too large), the heads kept, nothing of the files only checked present."""
    if name == RECORD:
        return MAX_RECORD_BYTES + 1
    if name == PLAN:
        return MAX_PLAN_BYTES + 1
    return HEAD_BYTES if name in {SPEC, EVAL} else 0


def _read_folder(parent: int, slug: str, meter: _Meter) -> FeatureFolder:
    try:
        folder = os.open(slug, _FOLDER_FLAGS, dir_fd=parent)
    except OSError:
        return FeatureFolder(slug=slug, files=())
    try:
        reads = {
            name: meter.add(read_regular(folder, name, limit=_limit(name))) for name in RECORD_FILES
        }
        evals, evals_skipped = _heads(
            folder, EVALS_FOLDER, cap=MAX_EVAL_FILES, size=EVAL_HEAD_BYTES, meter=meter
        )
        reviews, _ = _heads(
            folder, REVIEWS_FOLDER, cap=MAX_REVIEW_FILES, size=REVIEW_HEAD_BYTES, meter=meter
        )
        ux_designs, ux_skipped = _ux_heads(folder, meter)
        rounds = _round_names(folder, meter)
    finally:
        os.close(folder)
    record, plan = reads[RECORD], reads[PLAN]
    too_large = isinstance(plan, bytes) and len(plan) > MAX_PLAN_BYTES
    return FeatureFolder(
        slug=slug,
        files=tuple(name for name, read in reads.items() if isinstance(read, bytes)),
        features_json=_record(record),
        spec_head=_head(reads[SPEC]),
        eval_head=_head(reads[EVAL]),
        evals=evals,
        reviews=reviews,
        evals_skipped=evals_skipped,
        plan=plan if isinstance(plan, bytes) and not too_large else None,
        plan_too_large=too_large,
        ux_designs=ux_designs,
        ux_skipped=ux_skipped,
        review_rounds=rounds,
    )


def _heads(
    parent: int, name: str, *, cap: int, size: int, meter: _Meter
) -> tuple[tuple[RecordHead, ...], int]:
    """The heads of the record folder ``name``'s ``.md`` files, and how many were skipped."""
    try:
        folder = os.open(name, _FOLDER_FLAGS, dir_fd=parent)
    except OSError:
        return (), 0
    try:
        names, skipped = _record_names(folder, cap)
        heads = tuple(_record_head(folder, note, size=size, meter=meter) for note in names)
    except OSError:
        return (), 0
    finally:
        os.close(folder)
    return heads, skipped


def _ux_heads(folder: int, meter: _Meter) -> tuple[tuple[RecordHead, ...], int]:
    """The heads of the slug folder's own ``ux-*.md`` designs, and how many were skipped."""
    try:
        names, skipped = _record_names(folder, MAX_UX_FILES, prefix=UX_PREFIX)
    except OSError:
        return (), 0
    heads = tuple(_record_head(folder, name, size=UX_HEAD_BYTES, meter=meter) for name in names)
    return heads, skipped


def _round_names(parent: int, meter: _Meter) -> tuple[str, ...]:
    """The review round names ``<ticket>/<reviewer>-r<N>.json`` of ``reviews/``, by ticket folder
    then name: at most ``MAX_ROUND_TICKETS`` folder names are held while listing."""
    try:
        reviews = os.open(REVIEWS_FOLDER, _FOLDER_FLAGS, dir_fd=parent)
    except OSError:
        return ()
    found: list[str] = []
    try:
        with os.scandir(reviews) as entries:
            tickets = heapq.nsmallest(MAX_ROUND_TICKETS, _ticket_folders(entries))
        for ticket in tickets:
            if len(found) >= MAX_ROUND_NAMES:
                break
            meter.read += FOLDER_COST_BYTES
            names = _rounds_of(reviews, ticket, MAX_ROUND_NAMES - len(found))
            found.extend(f"{ticket}/{name}" for name in names)
    except OSError:
        pass
    finally:
        os.close(reviews)
    return tuple(found)


def _ticket_folders(entries: Iterable[os.DirEntry[str]]) -> Iterator[str]:
    """The folders of ``entries`` (never through a link) whose names are UTF-8 and not hidden."""
    for entry in entries:
        if entry.name.startswith(".") or not _is_utf8(entry.name):
            continue
        if entry.is_dir(follow_symlinks=False):
            yield entry.name


def _rounds_of(reviews: int, ticket: str, cap: int) -> list[str]:
    """The first ``cap`` names of the review rounds in ``reviews/<ticket>``, regular files only."""
    try:
        folder = os.open(ticket, _FOLDER_FLAGS, dir_fd=reviews)
    except OSError:
        return []
    try:
        with os.scandir(folder) as entries:
            return heapq.nsmallest(
                cap,
                (
                    entry.name
                    for entry in entries
                    if is_review_round(entry.name) and entry.is_file(follow_symlinks=False)
                ),
            )
    finally:
        os.close(folder)


def _is_utf8(name: str) -> bool:
    try:
        name.encode()
    except UnicodeEncodeError:
        return False
    return True


def _record_names(folder: int, cap: int, *, prefix: str = "") -> tuple[list[str], int]:
    """The first ``cap`` ``.md`` names of ``folder`` not hidden (and starting with ``prefix``),
    sorted, and how many others were left out (over the cap, or not UTF-8). At most ``cap``
    names are held while listing."""
    left_out = [0]
    with os.scandir(folder) as found:
        kept = heapq.nsmallest(cap, _notes(found, left_out, prefix))
    listed = left_out[0]
    return kept, listed - len(kept)


def _notes(entries: Iterable[os.DirEntry[str]], counted: list[int], prefix: str) -> Iterator[str]:
    """The UTF-8 ``.md`` names not hidden of ``entries`` that start with ``prefix``;
    ``counted[0]`` counts every such name, UTF-8 or not."""
    for entry in entries:
        note = entry.name
        if note.startswith(".") or not note.startswith(prefix) or not note.endswith(NOTE_SUFFIX):
            continue
        counted[0] += 1
        try:
            note.encode()
        except UnicodeEncodeError:
            continue
        yield note


def _record_head(folder: int, name: str, *, size: int, meter: _Meter) -> RecordHead:
    read = meter.add(read_regular(folder, name, limit=size))
    if isinstance(read, bytes):
        return RecordHead(name=name, head=read, problem=None)
    return RecordHead(name=name, head=None, problem=read or "could not be read")


def _record(read: bytes | str | None) -> bytes | str | None:
    if isinstance(read, bytes) and len(read) > MAX_RECORD_BYTES:
        return f"larger than {MAX_RECORD_BYTES} bytes"
    return read


def _head(read: bytes | str | None) -> bytes | None:
    return read[:HEAD_BYTES] if isinstance(read, bytes) else None
