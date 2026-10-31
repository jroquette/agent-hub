"""``hub doctor --fix`` for ``brain.leak``: every leak fixed at once, on the brain side.

A leak is a brain line that a repo file also holds. The repo text is the published one (a doc
that grew out of a note, a plan quoted in an ADR), so the fix rewrites the brain note
and never touches a repo: each leaked brain line, and each run of them (blank lines between two
leaked lines belong to the run), becomes one pointer line ``[in ../<dir>/<path>:<first>-<last>]``
with the run's indent, so the note keeps what the repo does not hold (the leaked text is in the
repo). A note that is mostly a promoted draft becomes a stub pointing at its repo file instead,
and that stub keeps only the frontmatter: what else the note held is then only in git, if the
note was committed. Every brain file is rewritten, not only the first one that holds a line, so
one run leaves no ``brain.leak`` finding behind.

The brain and repo lines are read exactly as the rule reads them (``brain_leak_rule``): same
trimming, same minimum length, frontmatter, fences and table rows skipped on the brain side. A
file's line endings and its final newline are kept. Pure: it returns the new texts; the caller
writes them.

An ADR draft (``brain_leak_rule.is_adr_draft``) is judged only by the repo files outside
``docs/adr/``, as the rule judges it: a draft line that only ``docs/adr/`` holds is kept, unless
half or more of the draft was copied elsewhere and the whole draft becomes a stub.
"""

from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Final

from agent_hub.core.doctor.brain_leak_rule import (
    ADR_FOLDER,
    BRAIN_FOLDER,
    DEFAULT_MIN_LINE_LENGTH,
    frontmatter_end,
    is_adr_draft,
    prose_lines,
)
from agent_hub.core.doctor.config_lint import text_lines
from agent_hub.core.doctor.snapshot import DoctorSnapshot, text_of

POINTER: Final = "[in {path}:{lines}]"
# The share of a note's countable lines found in the repo from which it is a promoted draft.
DRAFT_SHARE: Final = 0.5
STUB: Final = (
    "# {name}\n"
    "\n"
    "Promoted to `{path}`, which holds the final text.\n"
    "This draft was cut by `hub doctor --fix` (brain.leak);\n"
    "its earlier wording is in this file's git history.\n"
)


@dataclass(frozen=True, kw_only=True, slots=True)
class BrainEdit:
    """One brain note rewritten: its hub path, its new text and how many lines left it.

    ``promoted_to`` is the repo file a promoted draft now points at (the note became a stub),
    ``None`` when only its leaked lines became pointers.
    """

    path: str
    text: str
    replaced: int
    promoted_to: str | None = None


# A trimmed repo line → the first repo file (shown from the hub) and line that holds it.
type RepoLines = dict[str, tuple[str, int]]


def brain_leak_edits(snapshot: DoctorSnapshot) -> tuple[BrainEdit, ...]:
    """The brain notes to rewrite so that no ``brain.leak`` finding is left, in listing order."""
    settings = snapshot.hub_config.doctor.rules.brain_leak
    min_length = (None if settings is None else settings.min_line_length) or (
        DEFAULT_MIN_LINE_LENGTH
    )
    every, outside_adr = _repo_lines(snapshot, min_length=min_length)
    if not every:
        return ()
    edits = []
    for path in snapshot.hub.listed:
        if not path.startswith(BRAIN_FOLDER):
            continue
        text = text_of(snapshot.hub.entries.get(path))
        if text is None:
            continue
        repo = outside_adr if is_adr_draft(path) else every
        edit = _rewrite(path, text, repo=repo, min_length=min_length)
        if edit is not None:
            edits.append(edit)
    return tuple(edits)


def _repo_lines(snapshot: DoctorSnapshot, *, min_length: int) -> tuple[RepoLines, RepoLines]:
    """Every repo line, and separately the lines of the repo files outside ``docs/adr/``."""
    every: RepoLines = {}
    outside_adr: RepoLines = {}
    for checkout in snapshot.repos:
        files = checkout.files
        if files is None or files.problem is not None:
            continue
        for path in files.listed:
            text = text_of(files.entries.get(path))
            if text is None:
                continue
            in_adr = path.startswith(ADR_FOLDER)
            for number, line in enumerate(text_lines(text), start=1):
                trimmed = line.strip()
                if len(trimmed) >= min_length:
                    found = (f"../{checkout.dir}/{path}", number)
                    every.setdefault(trimmed, found)
                    if not in_adr:
                        outside_adr.setdefault(trimmed, found)
    return every, outside_adr


def _rewrite(path: str, text: str, *, repo: RepoLines, min_length: int) -> BrainEdit | None:
    lines = text_lines(text)
    leaked: dict[int, tuple[str, int]] = {}
    countable = 0
    for number, line in prose_lines(lines):
        trimmed = line.strip()
        if len(trimmed) >= min_length:
            countable += 1
            if trimmed in repo:
                leaked[number] = repo[trimmed]
    if not leaked:
        return None
    target = _promoted_to(list(leaked.values()), countable=countable)
    if target is not None:
        return BrainEdit(
            path=path, text=_stub(path, lines, target), replaced=len(leaked), promoted_to=target
        )
    raw = text.removesuffix("\n").split("\n")
    out: list[str] = []
    number = 1
    for start, end in _runs(sorted(leaked), lines=lines):
        out.extend(raw[number - 1 : start - 1])
        out.append(
            _pointer(raw[start - 1], [leaked[n] for n in range(start, end + 1) if n in leaked])
        )
        number = end + 1
    out.extend(raw[number - 1 :])
    new = "\n".join(out) + ("\n" if text.endswith("\n") else "")
    return BrainEdit(path=path, text=new, replaced=len(leaked))


def _promoted_to(found: Sequence[tuple[str, int]], *, countable: int) -> str | None:
    """The repo file a note is a promoted draft of, or None when it only quotes a few lines."""
    if len(found) < countable * DRAFT_SHARE:
        return None
    counts = Counter(path for path, _ in found)
    path, count = counts.most_common(1)[0]
    return path if count * 2 >= len(found) else None


def _stub(path: str, lines: tuple[str, ...], target: str) -> str:
    end = frontmatter_end(lines)
    head = "".join(f"{line}\n" for line in lines[:end])
    name = path.rsplit("/", 1)[-1].removesuffix(".md")
    return head + ("\n" if head else "") + STUB.format(name=name, path=target)


def _runs(numbers: Sequence[int], *, lines: Sequence[str]) -> Iterator[tuple[int, int]]:
    """The first and last line of each run of leaked lines; only blank lines may sit between."""
    start = end = numbers[0]
    for number in numbers[1:]:
        if all(not lines[between - 1].strip() for between in range(end + 1, number)):
            end = number
            continue
        yield start, end
        start = end = number
    yield start, end


def _pointer(first: str, found: Sequence[tuple[str, int]]) -> str:
    """One line in place of a run: the first line's indent and ending, the repo lines it holds."""
    indent = first[: len(first) - len(first.lstrip())]
    ending = "\r" if first.endswith("\r") else ""
    shown, line = found[0]
    numbers = [number for path, number in found if path == shown]
    low, high = min(numbers, default=line), max(numbers, default=line)
    span = str(low) if low == high else f"{low}-{high}"
    return f"{indent}{POINTER.format(path=shown, lines=span)}{ending}"
