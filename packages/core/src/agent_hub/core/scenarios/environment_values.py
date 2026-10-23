"""An environment's values as a scenario's inputs (docs/design/scenarios.md § Inputs).

A scenario planned or started in environment E takes, for each declared input the request does
not give, E's value of the same name, typed as the input declares; the input's declared default
comes after. So the order is: the given input, then E's value, then the default. A value whose
name the scenario does not declare is ignored, and an undeclared environment gives nothing (the
plan reports it). Both composition roots call ``with_environment_values`` before the defaults
are filled (``start_inputs``), so the run record keeps the effective inputs.
"""

import math
from collections.abc import Mapping

from agent_hub.core.hub_config.effective_environments import EffectiveEnvironments
from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.document import WorkflowInput
from agent_hub.core.workflows.launch import RunInputError
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.substitution import echo

_BOOLEANS = {"true": True, "false": False}


def with_environment_values(
    plan: WorkflowPlan,
    given: Mapping[str, JsonValue],
    *,
    view: EffectiveEnvironments,
    environment: str,
) -> dict[str, JsonValue]:
    """``given`` with each declared input it leaves out taken from ``environment``'s values;
    ``RunInputError`` naming the input when a value does not read as the input's type."""
    found = next((item for item in view.environments if item.name == environment), None)
    filled = dict(given)
    if found is None:
        return filled
    for name, spec in plan.document.inputs.items():
        if name not in filled and name in found.values:
            filled[name] = _typed(found.values[name], spec, name=name, environment=environment)
    return filled


def _typed(text: str, spec: WorkflowInput, *, name: str, environment: str) -> JsonValue:
    value: JsonValue = text
    try:
        if spec.type == "integer":
            value = int(text)
        elif spec.type == "number":
            value = float(text)
            value = value if math.isfinite(value) else None
        elif spec.type == "boolean":
            value = _BOOLEANS[text]
    except ValueError, KeyError:
        value = None
    if value is None or not spec.fits(value):
        raise RunInputError(
            f"the value of {echo(name)} in environment {echo(environment)} must be of type"
            f" {spec.type}"
        )
    return value
