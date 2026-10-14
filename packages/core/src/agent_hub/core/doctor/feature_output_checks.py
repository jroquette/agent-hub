"""``features.tracker``'s light check of a feature folder's agent outputs (AGH-139 S9, P10).

Warnings only. An ``evals/<name>.json`` needs its ``evals/<name>.md`` and a
``reviews/<ticket>/<file>.json`` its ``reviews/<ticket>.md``, each a listed regular file; an output
without one gets that warning only and is not validated. The others are validated by
``agent_outputs`` (an eval with the sibling's first ``EVAL_HEAD_BYTES`` and the folder's
``features.json`` as the record), and an invalid one gets one warning: its problem count and first
problem, and the ``hub validate-output`` command that lists them all. An output that is not a
regular file, or whose read failed, gets the rule's usual read warning.

The work is bounded. Per feature, the first ``MAX_EVAL_FILES`` eval and ``MAX_REVIEW_FILES``
review outputs by path are checked (the caps of the records they sit beside). Per run, one budget of
``MAX_VALIDATED_BYTES`` is shared by every feature in listing order: an output is validated when
the bytes it hands core fit the remaining budget (its own bytes; for an eval also the sibling's
head and the record; a file core refuses over its bound costs nothing). The outputs left out by a
cap or the budget get no finding of their own: ``OutputBudget.skipped`` counts them, and the rule
reports the count in one info finding per run (``skipped_message``); ``hub validate-output``
checks any file.
"""

import shlex
from collections.abc import Iterable, Mapping
from typing import Final, NamedTuple

from agent_hub.core.doctor.feature_plan_checks import Problem, file_content
from agent_hub.core.features import agent_outputs
from agent_hub.core.features.feature_evals import EVAL_HEAD_BYTES, MAX_EVAL_FILES
from agent_hub.core.features.feature_record import MAX_RECORD_BYTES
from agent_hub.core.features.feature_reviews import MAX_REVIEW_FILES
from agent_hub.core.features.output_models import MAX_OUTPUT_BYTES, OutputProblem
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.hub_files.tree_snapshot import FileEntry, TreeEntry

MAX_VALIDATED_BYTES: Final = 4_194_304
OUTPUT_SUFFIX: Final = ".json"
NOTE_SUFFIX: Final = ".md"
EVALS_FOLDER: Final = "evals"
REVIEWS_FOLDER: Final = "reviews"
NO_EVAL_NOTE: Final = "eval output without its record evals/<name>.md"
NO_EVAL_NOTE_FIX: Final = "write the eval record beside it, or remove the output"
NO_REVIEW_NOTE: Final = "review output without its ticket record reviews/<ticket>.md"
SKIPPED_FIX: Final = "run ./hub validate-output <kind> <path> on each"
NO_REVIEW_NOTE_FIX: Final = (
    "write reviews/<ticket>.md once the ticket's reviews pass, or remove the output"
)


class OutputBudget(NamedTuple):
    """What is left of a run's validation budget, and how many outputs went unvalidated."""

    left: int = MAX_VALIDATED_BYTES
    skipped: int = 0


class OutputCheck(NamedTuple):
    """The warnings on a folder's outputs, by output path, and the run's budget after them."""

    found: tuple[tuple[str, Problem], ...]
    budget: OutputBudget


class _Output(NamedTuple):
    """A listed output: its path, kind, file and folder names, and the record beside it."""

    path: str
    kind: agent_outputs.OutputKind
    name: str
    folder_name: str
    note: str


class _Inputs(NamedTuple):
    """What core validates an output from, and how many bytes that hands it."""

    content: bytes
    sibling_head: bytes
    cost: int


def output_problems(
    folder: str,
    *,
    outputs: Iterable[str],
    entries: Mapping[str, TreeEntry],
    listed: frozenset[str],
    record: bytes | None,
    budget: OutputBudget,
) -> OutputCheck:
    """Each warning on the outputs of ``folder`` (``brain/features/<name>/``), by output path,
    with ``budget`` (what the run's earlier folders left) spent on the outputs validated here.

    ``outputs`` are the listed ``evals/*.json`` and ``reviews/<ticket>/*.json`` of the folder,
    hidden names left out; ``record`` is the bytes of its ``features.json`` (None when unread).
    """
    found: list[tuple[str, Problem]] = []
    kept, over_cap = _capped(folder, outputs)
    left, skipped = budget.left, budget.skipped + over_cap
    for output in kept:
        inputs = _inputs(output, entries=entries, listed=listed, record=record)
        if isinstance(inputs, Problem):
            found.append((output.path, inputs))
        elif inputs is not None and inputs.cost > left:
            skipped += 1
        elif inputs is not None:
            left -= inputs.cost
            problems = _validated(output, inputs, record=record)
            if problems:
                found.append((output.path, _invalid(output, problems)))
    return OutputCheck(tuple(found), OutputBudget(left=left, skipped=skipped))


def skipped_message(count: int) -> str:
    """The run's info line on the outputs no cap or budget let it validate."""
    noun = "output" if count == 1 else "outputs"
    return f"{count} agent {noun} not validated (over the doctor's budget)"


def _capped(folder: str, outputs: Iterable[str]) -> tuple[list[_Output], int]:
    """The first eval outputs, then the first review outputs, each kind in path order, and how
    many outputs the caps left out."""
    parsed = [output for path in sorted(outputs) if (output := _output(folder, path)) is not None]
    evals = [output for output in parsed if output.kind == "eval"]
    reviews = [output for output in parsed if output.kind == "review"]
    kept = [*evals[:MAX_EVAL_FILES], *reviews[:MAX_REVIEW_FILES]]
    return kept, len(parsed) - len(kept)


def _output(folder: str, path: str) -> _Output | None:
    parts = path.removeprefix(folder).split("/")
    name = parts[-1]
    stem = name.removesuffix(OUTPUT_SUFFIX)
    if len(parts) == 2 and parts[0] == EVALS_FOLDER:
        note = f"{folder}{EVALS_FOLDER}/{stem}{NOTE_SUFFIX}"
        return _Output(path, "eval", name, EVALS_FOLDER, note)
    if len(parts) == 3 and parts[0] == REVIEWS_FOLDER:
        note = f"{folder}{REVIEWS_FOLDER}/{parts[1]}{NOTE_SUFFIX}"
        return _Output(path, "review", name, parts[1], note)
    return None


def _inputs(
    output: _Output,
    *,
    entries: Mapping[str, TreeEntry],
    listed: frozenset[str],
    record: bytes | None,
) -> _Inputs | Problem | None:
    """What to validate the output from; the warning instead; None when its note was not read."""
    note = entries.get(output.note) if output.note in listed else None
    if not isinstance(note, FileEntry):
        if output.kind == "eval":
            return Problem(NO_EVAL_NOTE, NO_EVAL_NOTE_FIX, warning=True)
        return Problem(NO_REVIEW_NOTE, NO_REVIEW_NOTE_FIX, warning=True)
    content = file_content(entries.get(output.path))
    if isinstance(content, Problem):
        return content._replace(warning=True)
    if output.kind == "review":
        return _Inputs(content, b"", _parsed(content, MAX_OUTPUT_BYTES))
    if note.content is None:
        # The note's own check already reports its failed read.
        return None
    head = note.content[:EVAL_HEAD_BYTES]
    cost = _parsed(content, MAX_OUTPUT_BYTES) + len(head) + _parsed(record, MAX_RECORD_BYTES)
    return _Inputs(content, head, cost)


def _parsed(content: bytes | None, bound: int) -> int:
    """The bytes core parses of ``content``: none when absent or refused over ``bound``."""
    return len(content) if content is not None and len(content) <= bound else 0


def _validated(
    output: _Output, inputs: _Inputs, *, record: bytes | None
) -> tuple[OutputProblem, ...]:
    if output.kind == "review":
        return agent_outputs.review_problems(
            inputs.content, file_name=output.name, folder_name=output.folder_name
        )
    return agent_outputs.eval_problems(
        inputs.content, file_name=output.name, sibling_head=inputs.sibling_head, record=record
    )


def _invalid(output: _Output, problems: tuple[OutputProblem, ...]) -> Problem:
    """One warning: the count and the first problem (already escaped by core), and the command."""
    first = problems[0]
    noun = "problem" if len(problems) == 1 else "problems"
    message = (
        f"invalid {output.kind} output: {len(problems)} {noun}, first: {first.path}: "
        f"{first.message}"
    )
    fix = f"run ./hub validate-output {output.kind} {shlex.quote(one_line(output.path))}"
    return Problem(message, fix, warning=True)
