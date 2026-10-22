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
the same way and read only until their first review round: a regular file named as the review
check names one (``<reviewer>-r<N>.json``), never read; ``MAX_ROUND_ENTRIES`` entries at most in
all. ``review_round_tickets`` names the folders holding one; only ``read_feature_folder`` (one
feature, as the tickets view reads it) looks for them, so the listing leaves it empty.
``change-requests/`` is read as ``evals/`` is, at most ``MAX_CHANGE_REQUEST_FILES`` heads of
``CHANGE_REQUEST_HEAD_BYTES`` (requests and their decisions; ``change_requests_skipped`` counts the
rest), by the listing too: the golden path's Plan signal and ``waiting_on_owner`` need them.
Only ``read_feature_folder(..., tickets=True)`` (the tickets route) opens ``tickets/``: its first
folders by name (not hidden, UTF-8 names, never a link), at most ``MAX_TICKET_FOLDERS`` and no
more than a full ``preflight.json`` (``MAX_PREFLIGHT_BYTES`` + 1) each can add before the call
reaches ``READ_BUDGET_BYTES``; ``ticket_folders_skipped`` counts the rest. In each,
``preflight.json`` is read whole up to ``MAX_PREFLIGHT_BYTES`` (else a one-line problem), and
``brief.md`` and ``plan.md`` are only checked as regular files.

One listing reads at most about ``READ_BUDGET_BYTES``: a folder is read only while the bytes read
so far are under it, so the total goes over by one folder at most (15,572,994 bytes, about
14.9 MiB: ``features.json`` 1 MiB + 1, ``plan.md`` 256 KiB + 1, two 64 KiB heads, 200 eval heads
of 16 KiB, 500 review heads of 8 KiB, 50 UX design heads of 4 KiB and 400 change request heads of
16 KiB); each folder past it is listed with ``OVER_BUDGET`` as its record problem and files
unread. ``read_feature_folder`` reads the one folder a slug names, as the listing would (at most
those 15,572,994 bytes), plus which of its ``reviews/`` ticket folders hold a review round; with
``tickets`` the call stays within ``READ_BUDGET_BYTES`` (32 MiB) in all, which leaves room for at
least 274 full ``preflight.json`` in the worst case.
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
    MAX_ROUND_ENTRIES,
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
from agent_hub.core.features.ticket_records import (
    CHANGE_REQUEST_HEAD_BYTES,
    CHANGE_REQUESTS_FOLDER,
    MAX_CHANGE_REQUEST_FILES,
    MAX_PREFLIGHT_BYTES,
    MAX_TICKET_FOLDERS,
    PREFLIGHT_FILE,
    TICKET_BRIEF,
    TICKET_PLAN,
    TICKETS_FOLDER,
    TicketFiles,
)
from agent_hub.core.regular_files import read_regular

MAX_FEATURE_FOLDERS: Final = 500
READ_BUDGET_BYTES: Final = 32 * 1_048_576
OVER_BUDGET: Final = f"not read: the feature folders read are over {READ_BUDGET_BYTES} bytes"
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


def read_feature_folder(
    hub_root: Path, slug: str, *, tickets: bool = False
) -> FeatureFolder | None:
    """The feature folder ``slug`` names, read as ``read_feature_folders`` reads it, with its
    ``tickets/`` records when ``tickets`` (the tickets route); None when there is no such folder
    (absent, hidden, a link, not a folder, or not a single name)."""
    if not slug or slug.startswith(".") or "/" in slug or "\0" in slug:
        return None
    with _features_folder(hub_root) as folder:
        if folder is None or not _is_folder(folder, slug):
            return None
        return _read_folder(folder, slug, _Meter(), one=True, tickets=tickets)


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


def _read_folder(
    parent: int, slug: str, meter: _Meter, *, one: bool = False, tickets: bool = False
) -> FeatureFolder:
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
        requests, requests_skipped = _heads(
            folder,
            CHANGE_REQUESTS_FOLDER,
            cap=MAX_CHANGE_REQUEST_FILES,
            size=CHANGE_REQUEST_HEAD_BYTES,
            meter=meter,
        )
        rounds = _round_tickets(folder) if one else ()
        ticket_folders, tickets_skipped = _tickets(folder, meter) if tickets else ((), 0)
    finally:
        os.close(folder)
    record, plan = reads[RECORD], reads[PLAN]
    too_large = isinstance(plan, bytes) and len(plan) > MAX_PLAN_BYTES
    return FeatureFolder(
        slug=slug,
        files=tuple(name for name, read in reads.items() if isinstance(read, bytes)),
        features_json=_capped(record, MAX_RECORD_BYTES),
        spec_head=_head(reads[SPEC]),
        eval_head=_head(reads[EVAL]),
        evals=evals,
        reviews=reviews,
        evals_skipped=evals_skipped,
        plan=plan if isinstance(plan, bytes) and not too_large else None,
        plan_too_large=too_large,
        ux_designs=ux_designs,
        ux_skipped=ux_skipped,
        review_round_tickets=rounds,
        ticket_folders=ticket_folders,
        ticket_folders_skipped=tickets_skipped,
        change_requests=requests,
        change_requests_skipped=requests_skipped,
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


def _tickets(parent: int, meter: _Meter) -> tuple[tuple[TicketFiles, ...], int]:
    """The records of ``tickets/``'s first folders by name, and how many others were left out: at
    most ``MAX_TICKET_FOLDERS``, and no more than a full ``preflight.json`` each can add while the
    call stays within ``READ_BUDGET_BYTES``."""
    try:
        tickets = os.open(TICKETS_FOLDER, _FOLDER_FLAGS, dir_fd=parent)
    except OSError:
        return (), 0
    listed = [0]
    room = max((READ_BUDGET_BYTES - meter.read) // (MAX_PREFLIGHT_BYTES + 1), 0)
    try:
        with os.scandir(tickets) as entries:
            found = _counted(_ticket_folders(entries), listed)
            names = heapq.nsmallest(min(MAX_TICKET_FOLDERS, room), found)
            for _ in found:  # nsmallest(0, …) reads nothing: count the folders left out too
                pass
        return tuple(_ticket_files(tickets, name, meter) for name in names), listed[0] - len(names)
    except OSError:
        return (), 0
    finally:
        os.close(tickets)


def _counted(names: Iterable[str], counted: list[int]) -> Iterator[str]:
    for name in names:
        counted[0] += 1
        yield name


def _ticket_files(tickets: int, name: str, meter: _Meter) -> TicketFiles:
    try:
        folder = os.open(name, _FOLDER_FLAGS, dir_fd=tickets)
    except OSError:
        return TicketFiles(name=name)
    try:
        preflight = read_regular(folder, PREFLIGHT_FILE, limit=MAX_PREFLIGHT_BYTES + 1)
        return TicketFiles(
            name=name,
            brief=isinstance(read_regular(folder, TICKET_BRIEF, limit=0), bytes),
            plan=isinstance(read_regular(folder, TICKET_PLAN, limit=0), bytes),
            preflight=_capped(meter.add(preflight), MAX_PREFLIGHT_BYTES),
        )
    finally:
        os.close(folder)


def _round_tickets(parent: int) -> tuple[str, ...]:
    """The ticket folders of ``reviews/`` holding a review round, sorted: of the first
    ``MAX_ROUND_TICKETS`` by name, each read until its first round, ``MAX_ROUND_ENTRIES`` entries
    in all."""
    try:
        reviews = os.open(REVIEWS_FOLDER, _FOLDER_FLAGS, dir_fd=parent)
    except OSError:
        return ()
    found: list[str] = []
    left = [MAX_ROUND_ENTRIES]
    try:
        with os.scandir(reviews) as entries:
            tickets = heapq.nsmallest(MAX_ROUND_TICKETS, _ticket_folders(entries))
        for ticket in tickets:
            if left[0] <= 0:
                break
            if _has_round(reviews, ticket, left):
                found.append(ticket)
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


def _has_round(reviews: int, ticket: str, left: list[int]) -> bool:
    """Whether ``reviews/<ticket>`` holds a regular file named as a review round; each entry read
    takes one from ``left[0]``, and reading stops when it is spent."""
    try:
        folder = os.open(ticket, _FOLDER_FLAGS, dir_fd=reviews)
    except OSError:
        return False
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                left[0] -= 1
                if is_review_round(entry.name) and entry.is_file(follow_symlinks=False):
                    return True
                if left[0] <= 0:
                    return False
    finally:
        os.close(folder)
    return False


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
        if _is_utf8(note):
            yield note


def _record_head(folder: int, name: str, *, size: int, meter: _Meter) -> RecordHead:
    read = meter.add(read_regular(folder, name, limit=size))
    if isinstance(read, bytes):
        return RecordHead(name=name, head=read, problem=None)
    return RecordHead(name=name, head=None, problem=read or "could not be read")


def _capped(read: bytes | str | None, limit: int) -> bytes | str | None:
    if isinstance(read, bytes) and len(read) > limit:
        return f"larger than {limit} bytes"
    return read


def _head(read: bytes | str | None) -> bytes | None:
    return read[:HEAD_BYTES] if isinstance(read, bytes) else None
