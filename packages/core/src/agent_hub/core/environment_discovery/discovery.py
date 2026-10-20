"""A discovery as stored, as the API shows it, and the body that starts one (ADR 0043).

``hub web`` starts a read-only Claude session that reads the picked repos and ends its reply
with a JSON proposal. ``DiscoveryRecord`` is what is kept per discovery (one file under
``<hub>/.agent-runs/env-discoveries/``, ``DiscoveryRecords``); ``EnvironmentDiscovery`` is what
the routes answer: the record, the session's state and, once Claude finished, the proposal the
server checked, each item's ``status`` computed against the effective config of now. Nothing is
written to ``hub.json`` here: the person applies the rows they pick through the batch edit.
"""

from datetime import datetime
from typing import Annotated, Final, Literal, Protocol

from pydantic import Field, StringConstraints

from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.readmodels.view_types import ApiTimestamp, ViewModel

DISCOVERY_ID_PATTERN: Final = r"^[0-9a-f]{12}$"
MAX_PICKED: Final = 50
MAX_NAME_CHARS: Final = 200

type Preset = Literal["local", "staging", "production", "mine", "other"]
type ProposedAccess = Literal["read", "ask", "write"]
type ItemStatus = Literal["new", "differs", "declared"]
type DiscoveryState = Literal["running", "finished", "failed", "stopped"]

PickedName = Annotated[str, StringConstraints(min_length=1, max_length=MAX_NAME_CHARS)]
DiscoveryId = Annotated[str, StringConstraints(pattern=DISCOVERY_ID_PATTERN)]


class Evidence(ViewModel):
    """Where Claude saw something: a file relative to the workspace, inside a picked repo."""

    path: str
    line: int | None = None


class ProposedEnvironment(ViewModel):
    """An environment Claude found. ``access`` and ``production`` come from ``preset``, never
    from Claude alone; ``yours`` describes the declared one when ``status`` is ``differs``."""

    name: str
    preset: Preset
    access: ProposedAccess
    production: bool
    description: str | None = None
    aws_profile: str | None = None
    env_file: str | None = None
    evidence: tuple[Evidence, ...] = ()
    status: ItemStatus
    yours: str | None


class ProposedAddress(ViewModel):
    """A service's address in one environment: a URL or a resource name."""

    environment: str
    address: str
    note: str | None = None
    evidence: tuple[Evidence, ...] = ()
    status: ItemStatus
    yours: str | None


class ProposedService(ViewModel):
    """A service of a picked repo; ``declared`` when it and every address are declared already,
    ``differs`` when it is declared but an address is new or different."""

    repo: str
    name: str
    kind: str | None = None
    description: str | None = None
    evidence: tuple[Evidence, ...] = ()
    status: ItemStatus
    addresses: tuple[ProposedAddress, ...] = ()


class MissingService(ViewModel):
    """A service Claude saw a sign of but could not place: no address it could read."""

    repo: str
    name: str
    kind: str | None = None
    why: str
    evidence: tuple[Evidence, ...] = ()


class NotRead(ViewModel):
    """A file Claude could not read, and why."""

    path: str
    reason: str


class Dropped(ViewModel):
    """An item, or one field of it, the server refused while checking the proposal."""

    what: str
    reason: str


class DiscoveryProposal(ViewModel):
    """What Claude proposed, as the server checked it."""

    environments: tuple[ProposedEnvironment, ...] = ()
    services: tuple[ProposedService, ...] = ()
    missing: tuple[MissingService, ...] = ()
    not_read: tuple[NotRead, ...] = ()
    dropped: tuple[Dropped, ...] = ()


class DiscoveryRecord(ViewModel):
    """One discovery as stored: what was asked and the session that answers it."""

    id: DiscoveryId
    project: str
    agent_session_id: str
    repos: tuple[str, ...]
    environments: tuple[str, ...]
    suggest_environments: bool
    created_at: ApiTimestamp
    discarded: bool = False


class EnvironmentDiscovery(ViewModel):
    """``/projects/{project}/environment-discoveries``: a discovery, where its session is, and
    its checked proposal once there is one; ``problem`` says in plain words why it failed."""

    id: str
    project: str
    agent_session_id: str
    repos: tuple[str, ...]
    environments: tuple[str, ...]
    suggest_environments: bool
    created_at: ApiTimestamp
    state: DiscoveryState
    problem: str | None = None
    proposal: DiscoveryProposal | None = None


class StartEnvironmentDiscovery(ViewModel):
    """``POST /projects/{project}/environment-discoveries``: the repos to read (``hub.json``
    repo folders), the declared environments to look for, and whether Claude may suggest
    environments not declared yet."""

    repos: tuple[PickedName, ...] = Field(min_length=1, max_length=MAX_PICKED)
    environments: tuple[PickedName, ...] = Field(default=(), max_length=MAX_PICKED)
    suggest_environments: bool = False


class DiscoveryNotFoundError(EntityNotFoundError):
    """No discovery with this id in the project (or it was discarded): 404."""

    def __init__(self, discovery_id: str) -> None:
        super().__init__(entity="discovery", entity_id=discovery_id)


class DiscoveryRecords(Protocol):
    """Where a hub's discoveries are kept (one file each); synchronous, called off the loop."""

    def create(self, hub_path: str, record: DiscoveryRecord) -> None:
        """Store a new discovery; ``FileExistsError`` when its id is taken."""
        ...

    def list(self, hub_path: str) -> tuple[DiscoveryRecord, ...]:
        """Every discovery that reads, in no order; unreadable files are skipped."""
        ...

    def get(self, hub_path: str, discovery_id: str) -> DiscoveryRecord | None:
        """One discovery, or None."""
        ...

    def replace(self, hub_path: str, record: DiscoveryRecord) -> None:
        """Write a discovery over its stored self."""
        ...


def created_order(record: DiscoveryRecord) -> datetime:
    """The sort key that lists the newest first (with ``reverse``)."""
    return record.created_at
