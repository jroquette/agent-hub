"""The ports the routes depend on, and the FastAPI dependencies that hand them over.

``create_app`` keeps an ``ApiPorts`` on ``app.state``; the composition (``build_app``) fills it
with the real adapters, tests with fakes. A route whose port is not wired answers the 501 of
the contract, so a partly wired build still serves every path of the document.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel, ValidationError

from agent_hub.api.ac_check import AcCheckRunner
from agent_hub.api.change_feed import ChangeFeed
from agent_hub.api.feature_names import FeatureNames
from agent_hub.api.linear_connection import LinearConnection
from agent_hub.api.rfc9457 import InvalidParameterError, NotImplementedInBuildError
from agent_hub.api.scenario_catalog import ScenarioCatalog, ScenarioCommands
from agent_hub.api.scenario_investigation import ScenarioInvestigations
from agent_hub.api.settings import ApiSettings
from agent_hub.core.agent_sessions.cloud import CloudSessionCommands
from agent_hub.core.agent_sessions.control import AgentSessionCommands
from agent_hub.core.agent_sessions.links import AgentSessionLinkLookup
from agent_hub.core.brain.brain_path import DEFAULT_ACCEPT_FOLDER
from agent_hub.core.environment_discovery.environment_discoveries import EnvironmentDiscoveries
from agent_hub.core.events.event_reader import EventReader
from agent_hub.core.features.change_request_decision import DecideChangeRequest
from agent_hub.core.features.owner_signoff import SignOffOwnerSteps
from agent_hub.core.ingestion.ingest_hook import IngestHook
from agent_hub.core.ingestion.ingestion_status import IngestionCounters
from agent_hub.core.item_versions.item_version_ports import ItemVersionReads, ItemVersionWrites
from agent_hub.core.knowledge.knowledge_reads import KnowledgeReads
from agent_hub.core.learnings.learning import Learning, LearningDetail
from agent_hub.core.learnings.learning_ports import LearningDecisions, LearningReads
from agent_hub.core.readmodels.filters import LearningFilter
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.read_ports import EventReadModels, HubReadModels
from agent_hub.core.workflows.gate_decisions import DecideWorkflowGate, WorkflowGates
from agent_hub.core.workflows.launch import ControlWorkflowRun, StartWorkflowRun
from agent_hub.core.workflows.workflow_reads import WorkflowReads


@dataclass(frozen=True)
class ApiPorts:
    """What the routes read and write through; None is a port this build does not wire."""

    event_read_models: EventReadModels | None = None
    hub_read_models: HubReadModels | None = None
    ingest_hook: IngestHook | None = None
    event_reader: EventReader | None = None
    change_feed: ChangeFeed | None = None
    counters: IngestionCounters | None = None
    learning_reads: LearningReads | None = None
    learning_decisions: LearningDecisions | None = None
    agent_sessions: AgentSessionCommands | None = None
    cloud_sessions: CloudSessionCommands | None = None
    agent_session_links: AgentSessionLinkLookup | None = None
    workflow_reads: WorkflowReads | None = None
    run_starts: StartWorkflowRun | None = None
    run_control: ControlWorkflowRun | None = None
    workflow_gates: WorkflowGates | None = None
    gate_decisions: DecideWorkflowGate | None = None
    item_version_reads: ItemVersionReads | None = None
    item_version_writes: ItemVersionWrites | None = None
    linear: LinearConnection | None = None
    owner_signoff: SignOffOwnerSteps | None = None
    change_request_decisions: DecideChangeRequest | None = None
    feature_names: FeatureNames | None = None
    ac_checks: AcCheckRunner | None = None
    environment_discoveries: EnvironmentDiscoveries | None = None
    scenario_investigations: ScenarioInvestigations | None = None
    knowledge_reads: KnowledgeReads | None = None
    scenario_reads: ScenarioCatalog | None = None
    scenario_commands: ScenarioCommands | None = None


def _ports(request: Request) -> ApiPorts:
    ports: ApiPorts = request.app.state.ports
    return ports


def _unwired(request: Request) -> NotImplementedInBuildError:
    route = request.scope.get("route")
    return NotImplementedInBuildError(getattr(route, "name", request.url.path))


def event_read_models(request: Request) -> EventReadModels:
    """The event read models, or 501 when not wired."""
    port = _ports(request).event_read_models
    if port is None:
        raise _unwired(request)
    return port


def hub_read_models(request: Request) -> HubReadModels:
    """The hub read models, or 501 when not wired."""
    port = _ports(request).hub_read_models
    if port is None:
        raise _unwired(request)
    return port


def knowledge_reads(request: Request) -> KnowledgeReads:
    """The knowledge search and backlinks reads, or 501 when not wired."""
    port = _ports(request).knowledge_reads
    if port is None:
        raise _unwired(request)
    return port


def owner_signoff(request: Request) -> SignOffOwnerSteps:
    """The owner's sign-off of a feature's owner steps, or 501 when not wired."""
    port = _ports(request).owner_signoff
    if port is None:
        raise _unwired(request)
    return port


def change_request_decisions(request: Request) -> DecideChangeRequest:
    """The owner's decision on a change request whose run is gone, or 501 when not wired."""
    port = _ports(request).change_request_decisions
    if port is None:
        raise _unwired(request)
    return port


def optional_change_request_decisions(request: Request) -> DecideChangeRequest | None:
    """The change request decision, or None when this build does not wire it (sessions off)."""
    return _ports(request).change_request_decisions


def workflow_reads(request: Request) -> WorkflowReads:
    """The workflow reads, or 501 when not wired."""
    port = _ports(request).workflow_reads
    if port is None:
        raise _unwired(request)
    return port


def run_starts(request: Request) -> StartWorkflowRun:
    """The workflow-run start, or 501 when not wired."""
    port = _ports(request).run_starts
    if port is None:
        raise _unwired(request)
    return port


def run_control(request: Request) -> ControlWorkflowRun:
    """The workflow-run cancel, resume and abandon, or 501 when not wired."""
    port = _ports(request).run_control
    if port is None:
        raise _unwired(request)
    return port


def scenario_investigations(request: Request) -> ScenarioInvestigations:
    """A scenario run's investigation session, or 501 when not wired."""
    port = _ports(request).scenario_investigations
    if port is None:
        raise _unwired(request)
    return port


def scenario_reads(request: Request) -> ScenarioCatalog:
    """The scenario reads, or 501 when not wired."""
    port = _ports(request).scenario_reads
    if port is None:
        raise _unwired(request)
    return port


def scenario_commands(request: Request) -> ScenarioCommands:
    """The scenario writes (plan, start, answer, findings), or 501 when not wired."""
    port = _ports(request).scenario_commands
    if port is None:
        raise _unwired(request)
    return port


def workflow_gates(request: Request) -> WorkflowGates:
    """The open gates of workflow runs, or 501 when not wired."""
    port = _ports(request).workflow_gates
    if port is None:
        raise _unwired(request)
    return port


def gate_decisions(request: Request) -> DecideWorkflowGate:
    """A workflow gate's decision from hub web, or 501 when not wired."""
    port = _ports(request).gate_decisions
    if port is None:
        raise _unwired(request)
    return port


def item_version_reads(request: Request) -> ItemVersionReads:
    """An item's version history reads, or 501 when not wired."""
    port = _ports(request).item_version_reads
    if port is None:
        raise _unwired(request)
    return port


def item_version_writes(request: Request) -> ItemVersionWrites:
    """An item's version restore, or 501 when not wired."""
    port = _ports(request).item_version_writes
    if port is None:
        raise _unwired(request)
    return port


@dataclass(frozen=True)
class EventLearningReads:
    """``LearningReads`` from the folded events alone, for a build that does not wire the hub
    reads: no note, no summary, the default target folder and no choices."""

    models: EventReadModels

    def list_learnings(self, learning_filter: LearningFilter) -> Page[Learning]:
        """The folded learnings, as before AGH-201."""
        return self.models.list_learnings(learning_filter)

    def get_learning(self, learning_id: str) -> LearningDetail:
        """The folded learning with no note."""
        learning = self.models.get_learning(learning_id)
        return LearningDetail.model_validate(
            learning.model_dump() | {"suggested_target": DEFAULT_ACCEPT_FOLDER}
        )


def learning_reads(request: Request) -> LearningReads:
    """The learning reads; the folded events alone when not wired, 501 when neither is."""
    port = _ports(request).learning_reads
    if port is not None:
        return port
    return EventLearningReads(event_read_models(request))


def learning_decisions(request: Request) -> LearningDecisions:
    """The learning decisions, or 501 when not wired."""
    port = _ports(request).learning_decisions
    if port is None:
        raise _unwired(request)
    return port


def agent_session_control(request: Request) -> AgentSessionCommands:
    """The agent-session commands, or 501 when not wired."""
    port = _ports(request).agent_sessions
    if port is None:
        raise _unwired(request)
    return port


def cloud_sessions(request: Request) -> CloudSessionCommands:
    """The cloud-session commands, or 501 when not wired."""
    port = _ports(request).cloud_sessions
    if port is None:
        raise _unwired(request)
    return port


def ingest_hook(request: Request) -> IngestHook:
    """The hook ingestion use case, or 501 when not wired."""
    port = _ports(request).ingest_hook
    if port is None:
        raise _unwired(request)
    return port


@dataclass(frozen=True)
class StreamPorts:
    """What a stream needs: the reader it replays from, the feed it waits on, the read models."""

    reader: EventReader
    feed: ChangeFeed
    models: EventReadModels
    counters: IngestionCounters | None


def stream_ports(request: Request) -> StreamPorts:
    """Every port of a stream, or 501 when one is not wired."""
    ports = _ports(request)
    if ports.event_reader is None or ports.change_feed is None or ports.event_read_models is None:
        raise _unwired(request)
    return StreamPorts(
        reader=ports.event_reader,
        feed=ports.change_feed,
        models=ports.event_read_models,
        counters=ports.counters,
    )


@dataclass(frozen=True)
class CollectorPorts:
    """What ``GET /collector/status`` reads: the counters and the store's high-water mark."""

    counters: IngestionCounters
    reader: EventReader


def collector_ports(request: Request) -> CollectorPorts:
    """The collector's counters and reader, or 501 when not wired."""
    ports = _ports(request)
    if ports.counters is None or ports.event_reader is None:
        raise _unwired(request)
    return CollectorPorts(counters=ports.counters, reader=ports.event_reader)


def linear_connection(request: Request) -> LinearConnection:
    """The Linear connection of Settings, or 501 when not wired."""
    port = _ports(request).linear
    if port is None:
        raise _unwired(request)
    return port


def feature_names(request: Request) -> FeatureNames:
    """The feature nicknames on this machine, or 501 when not wired."""
    port = _ports(request).feature_names
    if port is None:
        raise _unwired(request)
    return port


def ac_checks(request: Request) -> AcCheckRunner:
    """The runner of an AC's recorded check, or 501 when not wired."""
    port = _ports(request).ac_checks
    if port is None:
        raise _unwired(request)
    return port


def environment_discoveries(request: Request) -> EnvironmentDiscoveries:
    """The environment discoveries, or 501 when not wired."""
    port = _ports(request).environment_discoveries
    if port is None:
        raise _unwired(request)
    return port


def api_settings(request: Request) -> ApiSettings:
    """The settings ``create_app`` was given."""
    settings: ApiSettings = request.app.state.settings
    return settings


def parse_filter[M: BaseModel](model: type[M], **fields: object) -> M:
    """``model`` built from query parameters; a rule across parameters failing answers 400.

    FastAPI already checked each parameter; what is left are checks that span several
    (``cost_min`` above ``cost_max``), named by the first field they mention.
    """
    try:
        return model.model_validate(fields)
    except ValidationError as error:
        first = error.errors()[0]
        location = [str(part) for part in first.get("loc", ())]
        reason = str(first.get("msg", "invalid"))
        named = [name for name in fields if name in reason]
        parameter = location[0] if location else (named[0] if named else "query")
        raise InvalidParameterError(parameter=parameter, reason=reason) from None


EventReadModelsDep = Annotated[EventReadModels, Depends(event_read_models)]
HubReadModelsDep = Annotated[HubReadModels, Depends(hub_read_models)]
KnowledgeReadsDep = Annotated[KnowledgeReads, Depends(knowledge_reads)]
OwnerSignOffDep = Annotated[SignOffOwnerSteps, Depends(owner_signoff)]
ChangeRequestDecisionsDep = Annotated[DecideChangeRequest, Depends(change_request_decisions)]
OptionalChangeRequestDecisionsDep = Annotated[
    DecideChangeRequest | None, Depends(optional_change_request_decisions)
]
WorkflowReadsDep = Annotated[WorkflowReads, Depends(workflow_reads)]
RunStartsDep = Annotated[StartWorkflowRun, Depends(run_starts)]
RunControlDep = Annotated[ControlWorkflowRun, Depends(run_control)]
ScenarioInvestigationsDep = Annotated[ScenarioInvestigations, Depends(scenario_investigations)]
ScenarioReadsDep = Annotated[ScenarioCatalog, Depends(scenario_reads)]
ScenarioCommandsDep = Annotated[ScenarioCommands, Depends(scenario_commands)]
WorkflowGatesDep = Annotated[WorkflowGates, Depends(workflow_gates)]
GateDecisionsDep = Annotated[DecideWorkflowGate, Depends(gate_decisions)]
ItemVersionReadsDep = Annotated[ItemVersionReads, Depends(item_version_reads)]
ItemVersionWritesDep = Annotated[ItemVersionWrites, Depends(item_version_writes)]
IngestHookDep = Annotated[IngestHook, Depends(ingest_hook)]
LearningReadsDep = Annotated[LearningReads, Depends(learning_reads)]
LearningDecisionsDep = Annotated[LearningDecisions, Depends(learning_decisions)]
StreamPortsDep = Annotated[StreamPorts, Depends(stream_ports)]
CollectorPortsDep = Annotated[CollectorPorts, Depends(collector_ports)]
SettingsDep = Annotated[ApiSettings, Depends(api_settings)]
LinearConnectionDep = Annotated[LinearConnection, Depends(linear_connection)]
FeatureNamesDep = Annotated[FeatureNames, Depends(feature_names)]
AcChecksDep = Annotated[AcCheckRunner, Depends(ac_checks)]
AgentSessionControlDep = Annotated[AgentSessionCommands, Depends(agent_session_control)]
CloudSessionsDep = Annotated[CloudSessionCommands, Depends(cloud_sessions)]
EnvironmentDiscoveriesDep = Annotated[EnvironmentDiscoveries, Depends(environment_discoveries)]
