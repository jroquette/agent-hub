"""``environments.production``: one finding per production environment (environments.md), and
``environments.env_file``: the declared env files' problems (scenarios.md § Credentials).

Each production environment of ``hub.json`` and the developer's ``hub.local.json`` is named at
its source, the file its effective ``access`` comes from: a warning when the agent may write
there or ask to (``write``, ``ask``), an info when it may only read. Only the ``production`` flag
counts, never a name. A warning adds that actions are denied writes and destroys there, whatever
the access (the access policy, docs/design/scenarios.md). An ordinary ``doctor.rules`` entry: it
can be disabled or retuned. A local file that is invalid, or that ``config.schema`` refuses
against ``hub.json``, adds nothing: the committed environments are still named.
"""

from collections.abc import Iterable
from dataclasses import replace
from typing import Final

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot, EnvFileFacts
from agent_hub.core.hub_config.doctor_rules import (
    ENVIRONMENTS_ENV_FILE_RULE,
    ENVIRONMENTS_PRODUCTION_RULE,
    RULE_MODULES,
    Severity,
)
from agent_hub.core.hub_config.effective_environments import (
    effective_environments,
    local_environment_problems,
)
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.workspace.environment_lines import production_line

FIX: Final = (
    "keep the agent's access to a production environment at read, or confirm it on purpose"
    " (docs/design/environments.md)"
)
# The access policy denies an action's write or destroy on production (AC-350.3).
ACTIONS_DENIED: Final = "; actions: writes and destroys are denied there"


def _environments_production(snapshot: DoctorSnapshot) -> Iterable[Finding]:
    config = snapshot.hub_config
    local = snapshot.local
    if not isinstance(local, LocalConfig) or local_environment_problems(config, local):
        local = LocalConfig()
    findings = []
    for environment in effective_environments(config, local).environments:
        if not environment.production:
            continue
        message = production_line(environment.name, environment.access, environment.source)
        if environment.access != "read":
            message += ACTIONS_DENIED
        finding = ENVIRONMENTS_PRODUCTION.finding(path=environment.source, message=message, fix=FIX)
        if environment.access == "read":
            finding = replace(finding, severity=Severity.INFO)
        findings.append(finding)
    return tuple(findings)


ENVIRONMENTS_PRODUCTION: Final = Rule(
    id=ENVIRONMENTS_PRODUCTION_RULE,
    severity=Severity.WARNING,
    summary="each production environment, a warning when the agent's access is write or ask",
    module=RULE_MODULES.get(ENVIRONMENTS_PRODUCTION_RULE),
    reads=frozenset(),
    check=_environments_production,
)


ENV_FILE_FIX: Final = (
    "keep each declared env file present, git-ignored and inside the hub or a declared repo"
    " (docs/design/scenarios.md)"
)


def _environments_env_file(snapshot: DoctorSnapshot) -> Iterable[Finding]:
    """``environments.env_file``: a warning per problem of each declared env file, at the file
    that declares it; nothing when no env file is declared."""
    return tuple(
        ENVIRONMENTS_ENV_FILE.finding(
            path=facts.source,
            message=f"env file {facts.path} of {facts.environment} {problem}",
            fix=ENV_FILE_FIX,
        )
        for facts in snapshot.env_files or ()
        for problem in _env_file_problems(facts)
    )


def _env_file_problems(facts: EnvFileFacts) -> Iterable[str]:
    if not facts.exists:
        yield "is missing"
    if facts.holder is None:
        yield "is outside the hub and every declared repo"
    elif facts.ignored is False:
        yield f"is not ignored by git in {facts.holder}"
    if facts.linked:
        yield "is reached through a link"


ENVIRONMENTS_ENV_FILE: Final = Rule(
    id=ENVIRONMENTS_ENV_FILE_RULE,
    severity=Severity.WARNING,
    summary="each declared env file, a warning when it is missing, not git-ignored, outside"
    " the hub and its repos or reached through a link",
    module=RULE_MODULES.get(ENVIRONMENTS_ENV_FILE_RULE),
    reads=frozenset({Read.ENV_FILES}),
    check=_environments_env_file,
)
