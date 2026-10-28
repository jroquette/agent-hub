"""The cross-checks of a review output (AGH-139 S4, S5, E11): pure, on the parsed document.

Each check runs only when the fields it reads pass their model's own rule (S2), so a shape
problem never hides it and a malformed field never makes it raise. Order (P7): the file name,
``reviewer``, ``round``, ``ticket``, ``verdict``, then repeated finding ids.

A round sits in its ticket's folder, ``reviews/<ticket>/``, or, for a ticket that owns several
repos, in one repo's folder under it, ``reviews/<ticket>/<repo>/`` (AGH-589): the folder then names
the repo, which must be one of the ticket's repos when ``features.json`` is given.
"""

from collections.abc import Iterator, Mapping
from typing import Final, NamedTuple

from agent_hub.core.features.output_models import OutputProblem, ReviewFinding, ReviewOutput
from agent_hub.core.features.output_shape import echo, field_adapter, output_path, well_formed
from agent_hub.core.features.scope_rules import RERUN_PATTERN
from agent_hub.core.hub_config.problems import ROOT_PATH

_JSON_SUFFIX: Final = ".json"
_FILE_FORM: Final = (
    "spec-r<N>.json, quality-r<N>.json, ux-r<N>.json or overengineering-r<N>.json"
    " (N from 1 to 9999, no leading zero)"
)
_REVIEWER: Final = field_adapter(ReviewOutput, "reviewer")
_ROUND: Final = field_adapter(ReviewOutput, "round")
_TICKET: Final = field_adapter(ReviewOutput, "ticket")
_VERDICT: Final = field_adapter(ReviewOutput, "verdict")
_SEVERITY: Final = field_adapter(ReviewFinding, "severity")
_FINDING_ID: Final = field_adapter(ReviewFinding, "id")


class _FileName(NamedTuple):
    """What a review file's name says: ``<reviewer>-r<round>.json``."""

    reviewer: str
    round: int


def review_cross_problems(
    document: dict[str, object],
    *,
    file_name: str,
    folder_name: str,
    parent_name: str | None = None,
    owned: Mapping[str, tuple[str, ...]] | str | None = None,
) -> Iterator[OutputProblem]:
    """Every cross-check problem of a review saved as ``<folder_name>/<file_name>``, in order.

    A file name not of the form ``<reviewer>-r<N>.json`` is one problem at the root, and the
    ``reviewer`` and ``round`` checks, which need it, are skipped (E11). ``parent_name`` is the
    folder above ``folder_name``: when it, not ``folder_name``, is the ticket, ``folder_name`` is
    a repo of the ticket's, checked against ``owned`` (each ticket's key and id, upper case, to
    its repos), or ``owned`` is why ``features.json`` could not be read; None checks no repo.
    """
    named = _named(file_name)
    if named is None:
        yield OutputProblem(ROOT_PATH, f"the file name {echo(file_name)} is not {_FILE_FORM}")
    else:
        yield from _name_problems(document, named)
    yield from _ticket_problems(document, folder_name, parent_name=parent_name, owned=owned)
    yield from _verdict_problems(document)
    yield from _id_problems(document)


def is_review_round(file_name: str) -> bool:
    """Whether ``file_name`` is a review round's, ``<reviewer>-r<N>.json``: the rule a review is
    checked by, so the feature folder reader lists the rounds by the same one (AGH-326)."""
    return _named(file_name) is not None


def _named(file_name: str) -> _FileName | None:
    stem = file_name.removesuffix(_JSON_SUFFIX)
    found = RERUN_PATTERN.search(stem)
    # ``$`` also matches before a final line break, so the match must end the stem itself.
    if stem == file_name or found is None or found.end() != len(stem):
        return None
    reviewer = stem[: found.start()]
    if not well_formed(_REVIEWER, reviewer):
        return None
    return _FileName(reviewer, int(found.group(1)))


def _name_problems(document: dict[str, object], named: _FileName) -> Iterator[OutputProblem]:
    reviewer = document.get("reviewer")
    if well_formed(_REVIEWER, reviewer) and reviewer != named.reviewer:
        message = f"the reviewer is {reviewer} but the file name says {named.reviewer}"
        yield OutputProblem("reviewer", message)
    found_round = document.get("round")
    if well_formed(_ROUND, found_round) and found_round != named.round:
        message = f"the round is {found_round} but the file name says {named.round}"
        yield OutputProblem("round", message)


def _ticket_problems(
    document: dict[str, object],
    folder_name: str,
    *,
    parent_name: str | None,
    owned: Mapping[str, tuple[str, ...]] | str | None,
) -> Iterator[OutputProblem]:
    ticket = document.get("ticket")
    if not isinstance(ticket, str) or not well_formed(_TICKET, ticket):
        return
    if _same(ticket, folder_name):
        return
    if parent_name is None or not _same(ticket, parent_name):
        message = f"the ticket is {echo(ticket)} but the folder is {echo(folder_name)}"
        yield OutputProblem("ticket", message)
    elif isinstance(owned, str):
        yield OutputProblem(ROOT_PATH, owned)
    elif owned is not None and folder_name not in (repos := owned.get(ticket.upper(), ())):
        listed = ", ".join(repos) or "none planned"
        message = f"the folder {echo(folder_name)} is not a repo of {echo(ticket)} ({listed})"
        yield OutputProblem("ticket", message)


def _same(ticket: str, folder_name: str) -> bool:
    # ``str.upper`` maps some non-ASCII letters to ASCII (ſ to S, ı to I): compare ASCII only.
    return folder_name.isascii() and ticket.upper() == folder_name.upper()


def _verdict_problems(document: dict[str, object]) -> Iterator[OutputProblem]:
    """D4: ``FAIL`` iff a finding is blocking; needs a valid verdict and every severity valid."""
    verdict = document.get("verdict")
    severities = _severities(document.get("findings"))
    if severities is None or not well_formed(_VERDICT, verdict):
        return
    blocking = next(
        (index for index, severity in enumerate(severities) if severity == "blocking"), None
    )
    if verdict == "FAIL" and blocking is None:
        yield OutputProblem("verdict", "the verdict is FAIL but no finding is blocking")
    elif verdict == "PASS" and blocking is not None:
        finding = output_path(("findings", blocking))
        yield OutputProblem("verdict", f"the verdict is PASS but {finding} is blocking")


def _severities(findings: object) -> list[object] | None:
    """Each finding's severity; None unless ``findings`` is a list whose severities are valid."""
    if not isinstance(findings, list):
        return None
    severities = [
        finding.get("severity") if isinstance(finding, dict) else None for finding in findings
    ]
    if all(well_formed(_SEVERITY, severity) for severity in severities):
        return severities
    return None


def _id_problems(document: dict[str, object]) -> Iterator[OutputProblem]:
    """A problem at each finding whose valid ``id`` an earlier finding already has."""
    findings = document.get("findings")
    first: dict[str, int] = {}
    for index, finding in enumerate(findings if isinstance(findings, list) else ()):
        found = finding.get("id") if isinstance(finding, dict) else None
        if not isinstance(found, str) or not well_formed(_FINDING_ID, found):
            continue
        if found in first:
            earlier = output_path(("findings", first[found], "id"))
            message = f"the id {echo(found)} repeats {earlier}"
            yield OutputProblem(output_path(("findings", index, "id")), message)
        else:
            first[found] = index
