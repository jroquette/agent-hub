"""One action call's plan: the inputs it gets and each ``service`` input's endpoint
(docs/design/scenarios.md § Actions and the script contract).

A given value must be one of the action's inputs and fit its type. An input the step leaves out
takes the run's value of the same name (a scenario input: a value of the run, such as the account
it works in, set once and the same for every step, so one run cannot drift between accounts); an
input with neither takes its default, and a required one without a value is refused. A
``service`` value names a service of ``repos[].services`` (``<service>``, or ``<repo>/<service>``
when two repos have one of that name) and is resolved to that service's endpoint in the bound
environment, or refused naming the service and the environment. Messages name inputs and
services, never a given value. A ``pending`` input (a scenario step's value known only at run
time) is neither checked nor resolved: the plan then leaves it out.
"""

from collections.abc import Iterable, Mapping

from pydantic import BaseModel, ConfigDict

from agent_hub.core.errors import AgentHubError
from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    SourcedService,
)
from agent_hub.core.hub_config.environments import Endpoint
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.action_document import ActionDocument


def with_run_values(
    declared: Iterable[str], given: Mapping[str, JsonValue], run: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    """A step's inputs with the run's values for the declared inputs it leaves out: each input of
    the action named like a scenario input, with no ``with`` value, takes that input's value. A
    value the step gives always wins."""
    return {name: run[name] for name in declared if name not in given and name in run} | dict(given)


class ActionCallError(AgentHubError):
    """An action call that cannot be planned, as one plain line."""


class ActionCallPlan(BaseModel):
    """The call's inputs (defaults filled), the ``endpoint`` object its script reads, the
    ``<repo>/<service>`` names it reaches and those endpoints (whose credentials may win)."""

    model_config = ConfigDict(frozen=True)

    inputs: Mapping[str, JsonValue]
    endpoint: Mapping[str, Mapping[str, JsonValue]]
    services: tuple[str, ...]
    endpoints: tuple[Endpoint, ...]


def plan_action_call(
    action: ActionDocument,
    given: Mapping[str, JsonValue],
    *,
    environment: str,
    view: EffectiveEnvironments,
    pending: frozenset[str] = frozenset(),
) -> ActionCallPlan:
    """The plan of ``action`` called with ``given`` in ``environment``, ``pending`` inputs left
    out; raises ``ActionCallError`` at the first problem."""
    inputs = _typed_inputs(action, given, pending)
    endpoint: dict[str, Mapping[str, JsonValue]] = {}
    services: list[str] = []
    endpoints: list[Endpoint] = []
    for name, declared in action.inputs.items():
        value = inputs.get(name)
        if declared.type != "service" or not isinstance(value, str):
            continue
        service = _service(name, value, view)
        found = _endpoint(name, service, environment)
        endpoint[name] = {"url": found.url, "resource": found.resource}
        services.append(f"{service.repo}/{service.name}")
        endpoints.append(found)
    return ActionCallPlan(
        inputs=inputs, endpoint=endpoint, services=tuple(services), endpoints=tuple(endpoints)
    )


def _typed_inputs(
    action: ActionDocument, given: Mapping[str, JsonValue], pending: frozenset[str]
) -> dict[str, JsonValue]:
    """``given`` checked against the action's inputs, each missing one at its default."""
    if unknown := [name for name in (*given, *sorted(pending)) if name not in action.inputs]:
        raise ActionCallError(f"unknown input {unknown[0]}")
    inputs: dict[str, JsonValue] = {}
    for name, declared in action.inputs.items():
        if name in pending:
            continue
        if name in given:
            if not declared.fits(given[name]):
                raise ActionCallError(f"input {name} must be of type {declared.type}")
            inputs[name] = given[name]
        elif declared.required:
            raise ActionCallError(f"input {name} is required")
        elif declared.default is not None:
            inputs[name] = declared.default
    return inputs


def _service(name: str, value: str, view: EffectiveEnvironments) -> SourcedService:
    repo, _, service = value.rpartition("/")
    found = [item for item in view.services if item.name == service and repo in ("", item.repo)]
    if not found:
        raise ActionCallError(f"input {name}: no service {value} in repos[].services")
    if len(found) > 1:
        repos = ", ".join(sorted(item.repo for item in found))
        raise ActionCallError(
            f"input {name}: service {service} is in more than one repo ({repos}):"
            f" name it as <repo>/{service}"
        )
    return found[0]


def _endpoint(name: str, service: SourcedService, environment: str) -> Endpoint:
    for endpoint in service.endpoints:
        if endpoint.environment == environment:
            return endpoint.endpoint
    raise ActionCallError(
        f"input {name}: service {service.name} has no endpoint in environment {environment}"
    )
