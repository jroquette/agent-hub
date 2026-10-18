"""The owner confirms a feature's owner steps are done (playground): pure, no I/O but the ports.

A SHIP-WITH-OWNER-STEPS eval waits on steps only the owner can do. Once they are done, the owner
signs off from the app: a new eval ``brain/features/<slug>/evals/owner-signoff.md`` (a re-run is
``owner-signoff-r2``, ``-r3``...) with ``verdict: SHIP``, ``provenance: owner`` and the AC ids
that waited on owner steps as its scope. Being dated now, it is the latest eval of those ACs, so
the Evaluate step turns done (``feature_evals``' order). A sign-off is refused while any AC is
not covered by a SHIP (an agent must evaluate it first) or when no AC waits on owner steps.
"""

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Final, Protocol

from agent_hub.core.errors import AgentHubError
from agent_hub.core.features.feature_evals import (
    EVALS_FOLDER,
    NOTE_SUFFIX,
    eval_coverage,
    eval_records,
)
from agent_hub.core.features.feature_record import FeatureRecordFile, record_from_bytes
from agent_hub.core.features.feature_status import FeatureFolder
from agent_hub.core.features.feature_view import EvalRecord
from agent_hub.core.readmodels.read_ports import EntityNotFoundError

SIGNOFF_DELIVERY: Final = "owner-signoff"
MAX_SIGNOFFS: Final = 99


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
    *, slug: str, delivery: str, acs: tuple[str, ...], sources: tuple[str, ...], at: datetime
) -> str:
    """The eval note of the owner's sign-off."""
    listed = ", ".join(acs)
    from_evals = ", ".join(sources) or "the latest eval"
    return (
        "---\n"
        "type: eval\n"
        f"feature: {slug}\n"
        f"delivery: {delivery}\n"
        "verdict: SHIP\n"
        f"acs: [{listed}]\n"
        f"evaluated_at: {at.isoformat(timespec='seconds')}\n"
        "provenance: owner\n"
        "---\n\n"
        f"# Owner sign-off: {slug}\n\n"
        "**Verdict: SHIP.** The owner confirmed in agent-hub that the owner steps listed in "
        f"{from_evals} are done.\n\n"
        f"ACs signed off: {listed}.\n"
    )


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

    def __call__(self, project: str, slug: str) -> EvalRecord:
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
        delivery = signoff_name(found.delivery for found in evals if not found.legacy)
        name = f"{delivery}{NOTE_SUFFIX}"
        at = self._clock()
        text = signoff_note(
            slug=folder.slug, delivery=delivery, acs=coverage.owner_steps, sources=sources, at=at
        )
        try:
            self._writer.create_eval(hub_path, slug=folder.slug, name=name, text=text)
        except FileExistsError:
            raise OwnerSignOffError("a sign-off was just written; reload the feature") from None
        return EvalRecord(
            delivery=delivery,
            path=f"features/{folder.slug}/{EVALS_FOLDER}/{name}",
            verdict="SHIP",
            tickets=(),
            acs=coverage.owner_steps,
            prs=(),
            commit=None,
            evaluated_at=at.isoformat(timespec="seconds"),
            legacy=False,
            problem=None,
        )
