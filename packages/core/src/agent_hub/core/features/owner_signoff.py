"""The owner confirms a feature's owner steps are done (playground): pure, no I/O but the ports.

A SHIP-WITH-OWNER-STEPS eval waits on steps only the owner can do. Once they are done, the owner
signs off from the app: a new eval ``brain/features/<slug>/evals/owner-signoff.md`` (a re-run is
``owner-signoff-r2``, ``-r3``...) with ``verdict: SHIP``, ``provenance: owner`` and the AC ids
that waited on owner steps as its scope. Being dated now, it is the latest eval of those ACs, so
the Evaluate step turns done (``feature_evals``' order). A sign-off is refused while any AC is
not covered by a SHIP (an agent must evaluate it first) or when no AC waits on owner steps.

The owner can also settle one eval only (``delivery``): the sign-off then covers the ACs of that
SHIP-WITH-OWNER-STEPS eval that still wait on owner steps, carries its tickets (so it is listed
with them), and the rest of the feature does not have to be covered yet. Its ``decision`` is
``done`` (verdict SHIP) or ``more_work``: the owner found more to do before the delivery ships,
which writes a NO-SHIP over those ACs, so they read as open until an agent evaluates them again.
The owner's optional ``note`` (what was done, or what is left) goes into the note's body.

The owner can also sign off named ACs (``acs``), whatever their evals say: the criteria they
checked by hand (a manual test, a look at the screen). The note then covers exactly those ACs,
with no source eval, and ``done`` makes them pass (``EvalCoverage.signed_off``).
"""

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Final, Literal, Protocol

from agent_hub.core.errors import AgentHubError
from agent_hub.core.features.feature_evals import (
    EVALS_FOLDER,
    NOTE_SUFFIX,
    EvalCoverage,
    eval_coverage,
    eval_records,
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
    by_hand: bool = False,
) -> str:
    """The eval note of the owner's sign-off (``more_work``: the owner's NO-SHIP); ``by_hand``
    when the owner named the ACs themselves rather than an eval's owner steps."""
    listed = ", ".join(acs)
    from_evals = ", ".join(sources) or "the latest eval"
    checked = f"the owner steps listed in {from_evals}"
    if by_hand:
        checked = "these acceptance criteria by hand"
    verdict = _VERDICT_OF[decision]
    ticket_line = f"tickets: [{', '.join(tickets)}]\n" if tickets else ""
    if decision == "done":
        title = f"# Owner sign-off: {slug}"
        lead = (
            f"**Verdict: SHIP.** The owner confirmed in agent-hub that {checked} "
            f"{'pass' if by_hand else 'are done'}."
        )
        footer = f"ACs signed off: {listed}."
    else:
        title = f"# Owner review: {slug}"
        lead = (
            f"**Verdict: NO-SHIP.** The owner checked {checked} in agent-hub and found more "
            "work is needed before this ships."
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


def _feature_scope(evals: tuple[EvalRecord, ...], coverage: EvalCoverage) -> _Scope:
    """The whole feature's sign-off: every AC waiting on owner steps, once all are covered."""
    if coverage.uncovered:
        raise OwnerSignOffError(
            f"{len(coverage.uncovered)} ACs are not covered by a SHIP; evaluate them first"
        )
    if not coverage.owner_steps:
        raise OwnerSignOffError("no AC waits on owner steps")
    sources = tuple(
        found.delivery
        for found in evals
        if found.verdict == "SHIP-WITH-OWNER-STEPS" and found.problem is None
    )
    return coverage.owner_steps, sources, ()


def _named_acs(record: FeatureRecordFile, acs: tuple[str, ...]) -> _Scope:
    """The owner's own sign-off: the named live ACs, in ``features.json`` order."""
    live = tuple(ac.id for ac in record.acs if not ac.withdrawn)
    unknown = [ac for ac in acs if ac not in live]
    if unknown:
        raise OwnerSignOffError(f"no AC {unknown[0][:32]} in this feature")
    wanted = set(acs)
    named = tuple(ac for ac in live if ac in wanted)
    if not named:
        raise OwnerSignOffError("name at least one AC")
    return named, (), ()


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


def _chosen_scope(
    evals: tuple[EvalRecord, ...],
    coverage: EvalCoverage,
    *,
    record: FeatureRecordFile,
    delivery: str | None,
    decision: OwnerDecision,
    acs: tuple[str, ...] | None,
) -> _Scope:
    """The sign-off's scope: the named ACs, one eval's waiting ACs, or the whole feature's."""
    if acs is not None:
        if delivery is not None:
            raise OwnerSignOffError("name either an eval or ACs, not both")
        return _named_acs(record, acs)
    if delivery is None:
        if decision != "done":
            raise OwnerSignOffError("name the eval whose owner steps need more work")
        return _feature_scope(evals, coverage)
    return _eval_scope(evals, coverage, record=record, delivery=delivery)


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
        acs: tuple[str, ...] | None = None,
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
        coverage = eval_coverage(evals, record.acs, tickets=record.tickets)
        scope, sources, tickets = _chosen_scope(
            evals, coverage, record=record, delivery=delivery, decision=decision, acs=acs
        )
        name_of_delivery = signoff_name(found.delivery for found in evals if not found.legacy)
        name = f"{name_of_delivery}{NOTE_SUFFIX}"
        at = self._clock()
        text = signoff_note(
            slug=folder.slug,
            delivery=name_of_delivery,
            acs=scope,
            sources=sources,
            at=at,
            tickets=tickets,
            decision=decision,
            note=_clean_note(note),
            by_hand=acs is not None,
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
            acs=scope,
            prs=(),
            commit=None,
            evaluated_at=at.isoformat(timespec="seconds"),
            legacy=False,
            problem=None,
            provenance="owner",
        )
