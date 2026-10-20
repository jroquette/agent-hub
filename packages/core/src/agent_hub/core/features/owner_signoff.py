"""The owner confirms a feature's owner steps are done (playground): pure, no I/O but the ports.

A SHIP-WITH-OWNER-STEPS eval waits on steps only the owner can do. Once they are done, the owner
signs off from the app: a new eval ``brain/features/<slug>/evals/owner-signoff.md`` (a re-run is
``owner-signoff-r2``, ``-r3``...) with ``verdict: SHIP``, ``provenance: owner`` and the AC ids
that waited on owner steps as its scope. Being dated now, it is the latest eval of those ACs, so
the Acceptance step turns done (two-level-flows A3; ``feature_evals``' order). It is never a
whole-feature eval, so it never sets the header verdict. The ACs it lists are exactly those the
Acceptance step waits on (``feature_evals.owner_wait``, the rule both share). A sign-off is
refused, writing nothing (A9): when not every eval was read, when no AC waits on owner steps or
the feature lists no AC to sign off (A10), when the latest eval of a waiting AC is NO-SHIP, and
when the note would not rank newer than the acceptance eval (undated, or dated in the future).

The owner can also settle one eval only (``delivery``): the sign-off then covers the ACs of that
SHIP-WITH-OWNER-STEPS eval that still wait on owner steps, carries its tickets (so it is listed
with them), and the rest of the feature does not have to be covered yet. Its ``decision`` is
``done`` (verdict SHIP) or ``more_work``: the owner found more to do before the delivery ships,
which writes a NO-SHIP over those ACs, so they read as open until an agent evaluates them again.
The owner's optional ``note`` (what was done, or what is left) goes into the note's body. When
``delivery`` is the acceptance eval itself, its ACs and refusals are the whole-feature sign-off's
(``owner_wait``; ``more_work`` is not refused over ACs already reopened), so the app never writes
a sign-off over the acceptance eval that differs from what the Acceptance step waits on.
"""

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Final, Literal, Protocol

from agent_hub.core.errors import AgentHubError
from agent_hub.core.features.feature_evals import (
    EVALS_FOLDER,
    MAX_EVAL_FILES,
    NOTE_SUFFIX,
    EvalCoverage,
    OwnerWait,
    acceptance_eval,
    eval_coverage,
    eval_records,
    owner_wait,
    ranks_newer,
)
from agent_hub.core.features.feature_record import FeatureRecordFile, record_from_bytes
from agent_hub.core.features.feature_status import FeatureFolder
from agent_hub.core.features.feature_view import EvalRecord, Verdict
from agent_hub.core.features.scope_rules import named_scope, ticket_aliases
from agent_hub.core.readmodels.read_ports import EntityNotFoundError

SIGNOFF_DELIVERY: Final = "owner-signoff"
MAX_SIGNOFFS: Final = 99
MAX_NOTE_CHARS: Final = 2_000

type OwnerDecision = Literal["done", "more_work"]


class OwnerSignOffError(AgentHubError):
    """The feature has nothing to sign off; ``reason`` says why in one line."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ProjectHubs(Protocol):
    """Where a project's hub folder is (``HubReadModels.get_project``)."""

    def hub_path_of(self, project: str) -> str:
        """The hub folder of ``project``; ``EntityNotFoundError`` when unknown."""
        ...


class FeatureFolders(Protocol):
    """The feature folders of a hub (``HubFileReader.feature_folder``)."""

    def feature_folder(self, hub_path: str, slug: str) -> FeatureFolder | None:
        """The hub's feature folder ``slug``; None when there is no such folder."""
        ...


class EvalWriter(Protocol):
    """Writes a new eval note into a feature folder."""

    def create_eval(self, hub_path: str, *, slug: str, name: str, text: str) -> None:
        """Create ``brain/features/<slug>/evals/<name>`` with ``text``; ``FileExistsError`` when
        it exists already."""
        ...


def signoff_name(existing: Iterable[str]) -> str:
    """The first free ``owner-signoff[-rN]`` delivery among the ``existing`` eval deliveries."""
    taken = set(existing)
    for run in range(1, MAX_SIGNOFFS + 1):
        name = SIGNOFF_DELIVERY if run == 1 else f"{SIGNOFF_DELIVERY}-r{run}"
        if name not in taken:
            return name
    raise OwnerSignOffError(f"more than {MAX_SIGNOFFS} owner sign-offs on this feature")


def signoff_note(
    *,
    slug: str,
    delivery: str,
    acs: tuple[str, ...],
    sources: tuple[str, ...],
    at: datetime,
    tickets: tuple[str, ...] = (),
    decision: OwnerDecision = "done",
    note: str | None = None,
) -> str:
    """The eval note of the owner's sign-off (``more_work``: the owner's NO-SHIP)."""
    listed = ", ".join(acs)
    from_evals = ", ".join(sources) or "the latest eval"
    verdict = _VERDICT_OF[decision]
    ticket_line = f"tickets: [{', '.join(tickets)}]\n" if tickets else ""
    if decision == "done":
        title = f"# Owner sign-off: {slug}"
        lead = (
            "**Verdict: SHIP.** The owner confirmed in agent-hub that the owner steps listed in "
            f"{from_evals} are done."
        )
        footer = f"ACs signed off: {listed}."
    else:
        title = f"# Owner review: {slug}"
        lead = (
            "**Verdict: NO-SHIP.** The owner checked the owner steps listed in "
            f"{from_evals} in agent-hub and found more work is needed before this ships."
        )
        footer = f"ACs reopened: {listed}."
    body = f"\n\n## Owner's note\n\n{note}\n" if note else ""
    return (
        "---\n"
        "type: eval\n"
        f"feature: {slug}\n"
        f"delivery: {delivery}\n"
        f"verdict: {verdict}\n"
        f"{ticket_line}"
        f"acs: [{listed}]\n"
        f"evaluated_at: {at.isoformat(timespec='seconds')}\n"
        "provenance: owner\n"
        "---\n\n"
        f"{title}\n\n"
        f"{lead}\n\n"
        f"{footer}\n"
        f"{body}"
    )


_VERDICT_OF: Final[dict[str, Verdict]] = {"done": "SHIP", "more_work": "NO-SHIP"}


def _clean_note(note: str | None) -> str | None:
    """The owner's note without trailing spaces, cut to ``MAX_NOTE_CHARS``; None when empty."""
    if note is None:
        return None
    text = "\n".join(line.rstrip() for line in note.strip()[:MAX_NOTE_CHARS].splitlines())
    return text.strip() or None


type _Scope = tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]


def _eval_scope(
    evals: tuple[EvalRecord, ...],
    coverage: EvalCoverage,
    *,
    record: FeatureRecordFile,
    delivery: str,
) -> _Scope:
    """One eval's sign-off: the ACs it names that still wait on owner steps, with its tickets."""
    source = next((found for found in evals if found.delivery == delivery), None)
    if source is None:
        raise OwnerSignOffError(f"no eval {delivery[:64]} in this feature")
    if source.verdict != "SHIP-WITH-OWNER-STEPS" or source.problem is not None:
        raise OwnerSignOffError(f"{source.delivery} is not a SHIP-WITH-OWNER-STEPS eval")
    named = named_scope(
        acs=source.acs,
        tickets=source.tickets,
        live=tuple(ac for ac in record.acs if not ac.withdrawn),
        aliases=ticket_aliases(record.tickets),
    )
    acs = tuple(ac for ac in coverage.owner_steps if ac in (named or ()))
    if not acs:
        raise OwnerSignOffError(f"no AC of {source.delivery} waits on owner steps")
    return acs, (source.delivery,), source.tickets


class SignOffOwnerSteps:
    """``(project, slug)`` → the new eval record of the owner's sign-off."""

    def __init__(
        self,
        hubs: ProjectHubs,
        folders: FeatureFolders,
        writer: EvalWriter,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._hubs = hubs
        self._folders = folders
        self._writer = writer
        self._clock = clock

    def __call__(
        self,
        project: str,
        slug: str,
        *,
        delivery: str | None = None,
        decision: OwnerDecision = "done",
        note: str | None = None,
    ) -> EvalRecord:
        missing = EntityNotFoundError(entity="feature", entity_id=f"{project}/{slug}")
        try:
            hub_path = self._hubs.hub_path_of(project)
        except EntityNotFoundError:
            raise missing from None
        folder = self._folders.feature_folder(hub_path, slug)
        if folder is None:
            raise missing
        raw = folder.features_json
        record = record_from_bytes(raw) if isinstance(raw, bytes) else None
        if not isinstance(record, FeatureRecordFile):
            raise OwnerSignOffError("features.json is missing or invalid")
        evals = eval_records(folder.evals, folder.eval_head, slug=folder.slug)
        name_of_delivery = signoff_name(found.delivery for found in evals if not found.legacy)
        name = f"{name_of_delivery}{NOTE_SUFFIX}"
        at = self._clock().replace(microsecond=0)
        accepted = acceptance_eval(evals)
        if delivery is None and decision != "done":
            raise OwnerSignOffError("name the eval whose owner steps need more work")
        on_acceptance = (
            accepted is not None
            and accepted.delivery == delivery
            and accepted.verdict == "SHIP-WITH-OWNER-STEPS"
        )
        if delivery is None or on_acceptance:
            waiting = _owner_wait(folder, record, evals, refuse_reopened=decision == "done")
            if not ranks_newer(waiting.acceptance, delivery=name_of_delivery, at=at):
                raise OwnerSignOffError(
                    f"a sign-off would not be newer than {waiting.acceptance.delivery}: "
                    "it has no evaluated_at, or one at or after now"
                )
            scope: _Scope = waiting.acs, (waiting.acceptance.delivery,), ()
        else:
            coverage = eval_coverage(evals, record.acs, tickets=record.tickets)
            scope = _eval_scope(evals, coverage, record=record, delivery=delivery)
        acs, sources, tickets = scope
        text = signoff_note(
            slug=folder.slug,
            delivery=name_of_delivery,
            acs=acs,
            sources=sources,
            at=at,
            tickets=tickets,
            decision=decision,
            note=_clean_note(note),
        )
        try:
            self._writer.create_eval(hub_path, slug=folder.slug, name=name, text=text)
        except FileExistsError:
            raise OwnerSignOffError("a sign-off was just written; reload the feature") from None
        return EvalRecord(
            delivery=name_of_delivery,
            path=f"features/{folder.slug}/{EVALS_FOLDER}/{name}",
            verdict=_VERDICT_OF[decision],
            tickets=tickets,
            acs=acs,
            prs=(),
            commit=None,
            evaluated_at=at.isoformat(timespec="seconds"),
            legacy=False,
            problem=None,
            provenance="owner",
        )


def _owner_wait(
    folder: FeatureFolder,
    record: FeatureRecordFile,
    evals: tuple[EvalRecord, ...],
    *,
    refuse_reopened: bool,
) -> OwnerWait:
    """What ``folder``'s whole-feature sign-off covers (``owner_wait``, the rule the Acceptance
    step shares); ``OwnerSignOffError`` when it has nothing it can sign off (A9, A10)."""
    if folder.evals_skipped:
        raise OwnerSignOffError(f"more than {MAX_EVAL_FILES} evals; not all were read")
    waiting = owner_wait(evals, record.acs, tickets=record.tickets)
    if waiting is None:
        raise OwnerSignOffError("no AC waits on owner steps")
    if not waiting.acs:
        raise OwnerSignOffError("features.json lists no AC to sign off")
    if refuse_reopened and waiting.reopened:
        reopened = ", ".join(waiting.reopened)
        raise OwnerSignOffError(
            f"the latest eval of {reopened} is NO-SHIP; fix or re-evaluate them first"
        )
    return waiting
