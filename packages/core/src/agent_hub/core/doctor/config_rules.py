"""The rules that judge the config: ``config.schema``, ``platform.version``, ``config.identity``.

``config_state`` turns what the cli read into the config or why it failed, in the order of
docs/design/project-config.md § Versioning: a pin other than the running ``hub`` is only a
``platform.version`` finding (the pinned release judges the rest, the developer's
``hub.local.json`` included); every other problem is a ``config.schema`` finding, and so is each
problem of ``hub.local.json``. ``config.identity`` names the branch prefix a developer gets
when no file sets one (docs/design/developer-identity.md).
"""

from collections.abc import Iterable
from typing import Final

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import ConfigFailure, DoctorSnapshot, PinMismatch
from agent_hub.core.hub_config.doctor_rules import (
    CONFIG_IDENTITY_RULE,
    CONFIG_SCHEMA_RULE,
    PLATFORM_VERSION_RULE,
    RULE_MODULES,
    Severity,
)
from agent_hub.core.hub_config.document_check import check_hub_document
from agent_hub.core.hub_config.local_config import LOCAL_FILE, LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ROOT_PATH, ConfigProblem
from agent_hub.core.hub_config.versions import cut_echo, pinned_release, pinned_release_command
from agent_hub.core.json_form import InvalidJsonError, load_json_bytes

CONFIG_PATH: Final = "hub.json"
CONFIG_SCHEMA_FIX: Final = "fix hub.json (docs/design/project-config.md)"
LOCAL_FILE_FIX: Final = "fix hub.local.json (docs/design/developer-identity.md)"
IDENTITY_FIX: Final = "set project.branch_prefix in hub.local.json to choose another"
PINNED_RELEASE_FIX: Final = "run the pinned release"


def config_state(
    read: bytes | tuple[ConfigProblem, ...], *, running_version: str
) -> HubConfig | ConfigFailure:
    """The config in the bytes read, or why it cannot be used; reader problems pass through."""
    if not isinstance(read, bytes):
        return ConfigFailure(problems=read, pin=None)
    try:
        document = load_json_bytes(read)
    except InvalidJsonError as error:
        return ConfigFailure(problems=(ConfigProblem(ROOT_PATH, error.message),), pin=None)
    pinned = pinned_release(document)
    if pinned is not None and pinned != running_version:
        mismatch = PinMismatch(
            pinned=pinned, running=running_version, command=pinned_release_command(pinned)
        )
        return ConfigFailure(problems=(), pin=mismatch)
    checked = check_hub_document(document, running_version=running_version)
    if isinstance(checked, HubConfig):
        return checked
    return ConfigFailure(problems=checked, pin=None)


def _config_schema(snapshot: DoctorSnapshot) -> Iterable[Finding]:
    config = snapshot.config
    if isinstance(config, ConfigFailure) and config.pin is not None:
        return ()
    hub = config.problems if isinstance(config, ConfigFailure) else ()
    local = () if isinstance(snapshot.local, LocalConfig) else snapshot.local
    return (
        *(_schema_finding(CONFIG_PATH, problem, fix=CONFIG_SCHEMA_FIX) for problem in hub),
        *(_schema_finding(LOCAL_FILE, problem, fix=LOCAL_FILE_FIX) for problem in local),
    )


def _schema_finding(path: str, problem: ConfigProblem, *, fix: str) -> Finding:
    return CONFIG_SCHEMA.finding(path=path, message=f"{problem.path}: {problem.message}", fix=fix)


def _config_identity(snapshot: DoctorSnapshot) -> Iterable[Finding]:
    prefix = snapshot.branch_prefix
    if prefix is None or not prefix.derived:
        return ()
    message = (
        f"branch prefix `{prefix.value}` is {prefix.describe()}"
        f" ({LOCAL_FILE} and {CONFIG_PATH} set none)"
    )
    return (CONFIG_IDENTITY.finding(path=None, message=message, fix=IDENTITY_FIX),)


def _platform_version(snapshot: DoctorSnapshot) -> Iterable[Finding]:
    if not isinstance(snapshot.config, ConfigFailure) or snapshot.config.pin is None:
        return ()
    pin = snapshot.config.pin
    # A pin is digits and dots only, but of any length: the message repeats a bounded part.
    message = f"this hub is pinned to {cut_echo(pin.pinned)} but this hub command is {pin.running}."
    fix = PINNED_RELEASE_FIX if pin.command is None else f"{PINNED_RELEASE_FIX}: {pin.command}"
    return (PLATFORM_VERSION.finding(path=CONFIG_PATH, message=message, fix=fix),)


CONFIG_SCHEMA: Final = Rule(
    id=CONFIG_SCHEMA_RULE,
    severity=Severity.ERROR,
    summary=(
        "hub.json against HubConfig, including schema_version and doctor.rules ids,"
        " and hub.local.json"
    ),
    module=RULE_MODULES.get(CONFIG_SCHEMA_RULE),
    reads=frozenset(),
    check=_config_schema,
)
PLATFORM_VERSION: Final = Rule(
    id=PLATFORM_VERSION_RULE,
    severity=Severity.ERROR,
    summary="the running hub command is the release hub.json pins in platform.version",
    module=RULE_MODULES.get(PLATFORM_VERSION_RULE),
    reads=frozenset(),
    check=_platform_version,
)
CONFIG_IDENTITY: Final = Rule(
    id=CONFIG_IDENTITY_RULE,
    severity=Severity.INFO,
    summary="the branch prefix derived from the developer's email when no file sets one",
    module=RULE_MODULES.get(CONFIG_IDENTITY_RULE),
    reads=frozenset({Read.DEVELOPER_IDENTITY}),
    check=_config_identity,
)
