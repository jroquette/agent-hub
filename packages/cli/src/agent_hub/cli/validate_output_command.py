"""``hub validate-output review|eval FILE``: check one agent output (AGH-139 S7, E12, E17).

A thin adapter: the generator's ``output_files`` reads the output (and, for ``eval``, the sibling
``evals/<stem>.md`` head and ``../features.json``) without following a link, then core's
``review_problems`` / ``eval_problems`` check it. Exit 0 with ``<file>: valid`` on stdout; exit 1
with one stderr line per problem, ``<file>: <json path>: <message>``, at most
``MAX_PRINTED_PROBLEMS`` of them and then ``<file>: … and <N> more problems (<T> in total)``; a
read that fails is one line ``<file>: <cause>`` (or ``<file>: <name>: <cause>`` for the sibling or
the record), exit 1, and core is not called. A usage error exits 2 before any read. It needs no
``hub.json``, makes no network call and writes nothing.
"""

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli.command_exits import fail
from agent_hub.cli.init_report import shown_path
from agent_hub.core.features.agent_outputs import eval_problems, review_problems
from agent_hub.core.features.output_models import OutputProblem
from agent_hub.generator.output_files import (
    RECORD_NAME,
    read_eval_inputs,
    read_output,
    sibling_name,
)

MAX_PRINTED_PROBLEMS: Final = 200


class OutputKind(StrEnum):
    """The two agent outputs: a reviewer's review round, the evaluator's eval."""

    REVIEW = "review"
    EVAL = "eval"


def validate_output(
    kind: Annotated[OutputKind, typer.Argument(help="The output's kind: review or eval.")],
    file: Annotated[Path, typer.Argument(help="The output's JSON file.")],
) -> None:
    """Check one agent output JSON file: every problem, one per line."""
    shown = shown_path(str(file))
    problems = _review(file, shown) if kind is OutputKind.REVIEW else _eval(file, shown)
    if problems:
        fail(*_problem_lines(shown, problems))
    typer.echo(f"{shown}: valid")


def _review(file: Path, shown: str) -> tuple[OutputProblem, ...]:
    content = read_output(file)
    if isinstance(content, str):
        fail(f"{shown}: {content}")
    folder = file.parent.resolve().name
    return review_problems(content, file_name=file.name, folder_name=folder)


def _eval(file: Path, shown: str) -> tuple[OutputProblem, ...]:
    inputs = read_eval_inputs(file)
    if isinstance(inputs.content, str):
        fail(f"{shown}: {inputs.content}")
    if isinstance(inputs.sibling_head, str):
        fail(f"{shown}: {shown_path(sibling_name(file.name) or '')}: {inputs.sibling_head}")
    if isinstance(inputs.record, str):
        fail(f"{shown}: {RECORD_NAME}: {inputs.record}")
    return eval_problems(
        inputs.content, file_name=file.name, sibling_head=inputs.sibling_head, record=inputs.record
    )


def _problem_lines(shown: str, problems: tuple[OutputProblem, ...]) -> list[str]:
    """The first ``MAX_PRINTED_PROBLEMS`` problem lines, then the summary when there are more."""
    printed = problems[:MAX_PRINTED_PROBLEMS]
    lines = [f"{shown}: {problem.path}: {problem.message}" for problem in printed]
    more = len(problems) - len(printed)
    if more:
        lines.append(f"{shown}: … and {more} more problems ({len(problems)} in total)")
    return lines
