"""A discovery's proposal: read from Claude's last reply, checked item by item, then compared.

``read_proposal`` takes the last fenced ```` ```json ```` block of the reply (at most
``MAX_PROPOSAL_BYTES``), parses it strictly and checks every item with the shapes ``hub.json``
itself takes (``hub_config.environments``): names, kinds, URLs, resources, profiles, env files,
and no text with a secret's shape. An item, or one field of it, that fails goes to ``dropped``
with the reason; it never fails the whole proposal. Evidence must name a file inside a picked
repo. Access never comes from Claude: ``access`` and ``production`` follow the ``preset``.
A ``dropped`` entry names an item by a name already checked, else by its place, never by text
the check refused (it may be a secret).

``with_statuses`` sets each item's ``status`` against the effective environments of now.
"""

import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Annotated, Final, cast, get_args

from pydantic import Field, TypeAdapter, ValidationError

from agent_hub.core.environment_discovery.discovery import (
    DiscoveryProposal,
    Dropped,
    Evidence,
    ItemStatus,
    MissingService,
    NotRead,
    Preset,
    ProposedAccess,
    ProposedAddress,
    ProposedEnvironment,
    ProposedService,
)
from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    SourcedEnvironment,
    SourcedService,
)
from agent_hub.core.hub_config.environments import (
    AwsProfile,
    EnvFilePath,
    EnvironmentDescription,
    EnvironmentName,
    NoSecretText,
    ServiceKind,
    ServiceName,
    Url,
)
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes

MAX_PROPOSAL_BYTES: Final = 512 * 1024
MAX_TEXT_CHARS: Final = 200
MAX_WHY_CHARS: Final = 500
MAX_PATH_CHARS: Final = 300
MAX_ENVIRONMENTS: Final = 50
MAX_SERVICES: Final = 200
MAX_ADDRESSES: Final = 50
MAX_EVIDENCE: Final = 10
MAX_LISTED: Final = 200
MAX_DROPPED: Final = 200

NO_BLOCK: Final = "Claude finished without a proposal"
# What each preset sets; Claude names the preset, never the access.
PRESET_ACCESS: Final[Mapping[str, tuple[ProposedAccess, bool]]] = {
    "local": ("write", False),
    "staging": ("ask", False),
    "production": ("read", True),
    "mine": ("write", False),
    "other": ("read", False),
}
PRESETS: Final = frozenset(get_args(Preset.__value__))

_FENCE = re.compile(r"```json[ \t]*\r?\n(.*?)\r?\n[ \t]*```", re.DOTALL)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

_ENVIRONMENT_NAME: TypeAdapter[str] = TypeAdapter(EnvironmentName)
_SERVICE_NAME: TypeAdapter[str] = TypeAdapter(ServiceName)
_SERVICE_KIND: TypeAdapter[str] = TypeAdapter(ServiceKind)
_DESCRIPTION: TypeAdapter[str] = TypeAdapter(EnvironmentDescription)
_TEXT: TypeAdapter[str] = TypeAdapter(Annotated[NoSecretText, Field(max_length=MAX_TEXT_CHARS)])
_WHY: TypeAdapter[str] = TypeAdapter(Annotated[NoSecretText, Field(max_length=MAX_WHY_CHARS)])
_AWS_PROFILE: TypeAdapter[str] = TypeAdapter(AwsProfile)
_ENV_FILE: TypeAdapter[str] = TypeAdapter(EnvFilePath)
_URL: TypeAdapter[str] = TypeAdapter(Url)


class ProposalError(Exception):
    """The reply holds no proposal that parses; the message says why in plain words."""


@dataclass(frozen=True)
class Asked:
    """What the discovery asked: the picked repo folders and environment names (as declared),
    whether new environments may be suggested, the declared environment names, and the
    workspace folder (the hub's parent) the evidence paths are relative to."""

    repos: tuple[str, ...]
    environments: tuple[str, ...]
    suggest_environments: bool
    declared: tuple[str, ...]
    workspace: str


def proposal_block(reply: str | None) -> str:
    """The last ```` ```json ```` block of ``reply``; ``ProposalError`` when there is none."""
    blocks = _FENCE.findall(reply or "")
    if not blocks:
        raise ProposalError(NO_BLOCK)
    block = cast("str", blocks[-1])
    if len(block.encode()) > MAX_PROPOSAL_BYTES:
        msg = f"Claude's proposal is over {MAX_PROPOSAL_BYTES // 1024} KiB"
        raise ProposalError(msg)
    return block


def read_proposal(reply: str | None, asked: Asked) -> DiscoveryProposal:
    """The checked proposal of ``reply`` (every status ``new`` until ``with_statuses``);
    ``ProposalError`` when no proposal parses."""
    block = proposal_block(reply)
    try:
        document = load_json_bytes(block.encode(), strict=True)
    except InvalidJsonError as error:
        msg = f"Claude's proposal is not valid JSON: {error.message}"
        raise ProposalError(msg) from None
    if not isinstance(document, dict):
        msg = "Claude's proposal is not a JSON object"
        raise ProposalError(msg)
    return _Checker(asked).proposal(document)


def _reason(error: ValidationError) -> str:
    first = error.errors()[0]
    return str(first.get("msg", "invalid"))


@dataclass
class _Checker:
    asked: Asked
    dropped: list[Dropped] = field(default_factory=list)
    names: set[str] = field(default_factory=set)

    def drop(self, what: str, reason: str) -> None:
        if len(self.dropped) < MAX_DROPPED:
            self.dropped.append(Dropped(what=what, reason=reason))

    def proposal(self, document: dict[str, JsonValue]) -> DiscoveryProposal:
        environments = self.items(
            document, "environments", limit=MAX_ENVIRONMENTS, check=self.environment
        )
        self.names = {item.name for item in environments}
        services = self.items(document, "services", limit=MAX_SERVICES, check=self.service)
        missing = self.items(document, "missing", limit=MAX_LISTED, check=self.missing)
        not_read = self.items(document, "not_read", limit=MAX_LISTED, check=self.not_read)
        return DiscoveryProposal(
            environments=tuple(environments),
            services=tuple(_unique_services(services, self)),
            missing=tuple(missing),
            not_read=tuple(not_read),
            dropped=tuple(self.dropped),
        )

    def items[T](
        self,
        document: dict[str, JsonValue],
        key: str,
        *,
        limit: int,
        check: Callable[[str, dict[str, JsonValue]], T | None],
    ) -> list[T]:
        value = document.get(key, [])
        if not isinstance(value, list):
            self.drop(key, "not a list")
            return []
        if len(value) > limit:
            self.drop(key, f"more than {limit}; the rest was left out")
        checked: list[T] = []
        for index, item in enumerate(value[:limit]):
            place = f"{key} #{index + 1}"
            if not isinstance(item, dict):
                self.drop(place, "not an object")
                continue
            result = check(place, item)
            if result is not None:
                checked.append(result)
        return checked

    # Environments

    def environment(self, place: str, item: dict[str, JsonValue]) -> ProposedEnvironment | None:
        name = self.environment_name(place, item.get("name"))
        if name is None:
            return None
        what = f"environment {name}"
        if name in self.names:
            self.drop(what, "proposed twice")
            return None
        self.names.add(name)
        preset = item.get("preset")
        if not isinstance(preset, str) or preset not in PRESETS:
            self.drop(what, "preset is not one of " + ", ".join(sorted(PRESETS)))
            return None
        access, production = PRESET_ACCESS[preset]
        return ProposedEnvironment(
            name=name,
            preset=cast("Preset", preset),
            access=access,
            production=production,
            description=self.optional(what, "description", item, shape=_DESCRIPTION),
            aws_profile=self.optional(what, "aws_profile", item, shape=_AWS_PROFILE),
            env_file=self.optional(what, "env_file", item, shape=_ENV_FILE),
            evidence=self.evidence(what, item.get("evidence")),
            status="new",
            yours=None,
        )

    def environment_name(self, place: str, value: JsonValue) -> str | None:
        """The name as declared when it is a picked one, a new name when suggestions are on,
        else None (dropped)."""
        try:
            name = _ENVIRONMENT_NAME.validate_python(value)
        except ValidationError as error:
            self.drop(place, "name: " + _reason(error))
            return None
        picked = _match(name, self.asked.environments)
        if picked is not None:
            return picked
        if self.asked.suggest_environments and _match(name, self.asked.declared) is None:
            return name
        self.drop(f"environment {name}", "not one of the environments you picked")
        return None

    # Services

    def service(self, place: str, item: dict[str, JsonValue]) -> ProposedService | None:
        repo = self.repo(place, item.get("repo"))
        if repo is None:
            return None
        try:
            name = _SERVICE_NAME.validate_python(item.get("name"))
        except ValidationError as error:
            self.drop(place, "name: " + _reason(error))
            return None
        what = f"service {repo}/{name}"
        raw_addresses = item.get("addresses", [])
        addresses: list[ProposedAddress] = []
        if not isinstance(raw_addresses, list):
            self.drop(what, "addresses: not a list")
            raw_addresses = []
        if len(raw_addresses) > MAX_ADDRESSES:
            self.drop(what, f"more than {MAX_ADDRESSES} addresses; the rest was left out")
        for index, raw in enumerate(raw_addresses[:MAX_ADDRESSES]):
            address = self.address(f"{what} address #{index + 1}", raw, addresses)
            if address is not None:
                addresses.append(address)
        return ProposedService(
            repo=repo,
            name=name,
            kind=self.optional(what, "kind", item, shape=_SERVICE_KIND),
            description=self.optional(what, "description", item, shape=_TEXT),
            evidence=self.evidence(what, item.get("evidence")),
            status="new",
            addresses=tuple(addresses),
        )

    def address(
        self, place: str, raw: JsonValue, seen: list[ProposedAddress]
    ) -> ProposedAddress | None:
        if not isinstance(raw, dict):
            self.drop(place, "not an object")
            return None
        try:
            environment = _ENVIRONMENT_NAME.validate_python(raw.get("environment"))
        except ValidationError as error:
            self.drop(place, "environment: " + _reason(error))
            return None
        environment = _match(environment, (*self.asked.environments, *self.names)) or ""
        if not environment:
            self.drop(place, "its environment is neither picked nor proposed")
            return None
        if any(item.environment == environment for item in seen):
            self.drop(f"{place} ({environment})", "a second address in the same environment")
            return None
        value = raw.get("address")
        shape = _URL if isinstance(value, str) and "://" in value else _TEXT
        try:
            address = shape.validate_python(value)
        except ValidationError as error:
            self.drop(f"{place} ({environment})", "address: " + _reason(error))
            return None
        what = f"{place} ({environment})"
        return ProposedAddress(
            environment=environment,
            address=address,
            note=self.optional(what, "note", raw, shape=_TEXT),
            evidence=self.evidence(what, raw.get("evidence")),
            status="new",
            yours=None,
        )

    def missing(self, place: str, item: dict[str, JsonValue]) -> MissingService | None:
        repo = self.repo(place, item.get("repo"))
        if repo is None:
            return None
        try:
            name = _TEXT.validate_python(item.get("name"))
            why = _WHY.validate_python(item.get("why"))
        except ValidationError as error:
            self.drop(place, _reason(error))
            return None
        what = f"missing {repo} #{place.rsplit('#', 1)[-1]}"
        return MissingService(
            repo=repo,
            name=name,
            kind=self.optional(what, "kind", item, shape=_SERVICE_KIND),
            why=why,
            evidence=self.evidence(what, item.get("evidence")),
        )

    def not_read(self, place: str, item: dict[str, JsonValue]) -> NotRead | None:
        path = self.path(item.get("path"))
        if path is None:
            self.drop(place, "path: not a file inside a picked repo")
            return None
        try:
            reason = _TEXT.validate_python(item.get("reason"))
        except ValidationError as error:
            self.drop(place, "reason: " + _reason(error))
            return None
        return NotRead(path=path, reason=reason)

    # Shared checks

    def repo(self, place: str, value: JsonValue) -> str | None:
        if isinstance(value, str) and value in self.asked.repos:
            return value
        self.drop(place, "repo: not one of the repos you picked")
        return None

    def optional(
        self, what: str, key: str, item: dict[str, JsonValue], *, shape: TypeAdapter[str]
    ) -> str | None:
        value = item.get(key)
        if value is None or value == "":
            return None
        try:
            return shape.validate_python(value)
        except ValidationError as error:
            self.drop(f"{what}: {key}", _reason(error))
            return None

    def evidence(self, what: str, value: JsonValue) -> tuple[Evidence, ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            self.drop(f"{what}: evidence", "not a list")
            return ()
        kept: list[Evidence] = []
        refused = 0
        for raw in value[:MAX_EVIDENCE]:
            evidence = self.one_evidence(raw)
            if evidence is None:
                refused += 1
            else:
                kept.append(evidence)
        if refused:
            self.drop(f"{what}: evidence", f"{refused} not a file inside a picked repo")
        return tuple(kept)

    def one_evidence(self, raw: JsonValue) -> Evidence | None:
        if isinstance(raw, str):
            raw = {"path": raw}
        if not isinstance(raw, dict):
            return None
        path = self.path(raw.get("path"))
        line = raw.get("line")
        if path is None:
            return None
        if not (line is None or (type(line) is int and line >= 1)):
            line = None
        return Evidence(path=path, line=line)

    def path(self, value: JsonValue) -> str | None:
        """``value`` as a path relative to the workspace inside a picked repo, else None."""
        if not isinstance(value, str) or not value or len(value) > MAX_PATH_CHARS:
            return None
        if _CONTROL.search(value) or "\\" in value:
            return None
        prefix = self.asked.workspace.rstrip("/") + "/"
        if value.startswith(prefix):
            value = value[len(prefix) :]
        if value.startswith(("/", "~")):
            return None
        parts = [part for part in PurePosixPath(value).parts if part != "."]
        if not parts or ".." in parts or parts[0] not in self.asked.repos:
            return None
        return "/".join(parts)


def _match(name: str, names: Collection[str]) -> str | None:
    """The entry of ``names`` equal to ``name`` ignoring case, or None."""
    folded = name.casefold()
    return next((one for one in names if one.casefold() == folded), None)


def _unique_services(services: list[ProposedService], checker: _Checker) -> list[ProposedService]:
    seen: set[tuple[str, str]] = set()
    kept: list[ProposedService] = []
    for service in services:
        key = (service.repo, service.name.casefold())
        if key in seen:
            checker.drop(f"service {service.repo}/{service.name}", "proposed twice")
            continue
        seen.add(key)
        kept.append(service)
    return kept


# Statuses


def with_statuses(
    proposal: DiscoveryProposal, effective: EffectiveEnvironments
) -> DiscoveryProposal:
    """``proposal`` with each item's status against the effective environments and services."""
    environments = tuple(
        _environment_status(item, effective.environments) for item in proposal.environments
    )
    services = tuple(_service_status(item, effective.services) for item in proposal.services)
    return proposal.model_copy(update={"environments": environments, "services": services})


def _environment_status(
    item: ProposedEnvironment, declared: tuple[SourcedEnvironment, ...]
) -> ProposedEnvironment:
    folded = item.name.casefold()
    current = next((one for one in declared if one.name.casefold() == folded), None)
    if current is None:
        return item.model_copy(update={"status": "new", "yours": None})
    if current.access == item.access and current.production == item.production:
        return item.model_copy(update={"status": "declared", "yours": None})
    yours = current.access + (", production" if current.production else "")
    return item.model_copy(update={"status": "differs", "yours": yours})


def _service_status(item: ProposedService, declared: tuple[SourcedService, ...]) -> ProposedService:
    folded = item.name.casefold()
    current = next(
        (one for one in declared if one.repo == item.repo and one.name.casefold() == folded), None
    )
    if current is None:
        addresses = tuple(
            address.model_copy(update={"status": "new", "yours": None})
            for address in item.addresses
        )
        return item.model_copy(update={"status": "new", "addresses": addresses})
    values: dict[str, tuple[str, ...]] = {}
    for sourced in current.endpoints:
        endpoint = sourced.endpoint
        shown = tuple(value for value in (endpoint.url, endpoint.resource) if value)
        values[sourced.environment.casefold()] = shown
    addresses = tuple(_address_status(address, values) for address in item.addresses)
    status: ItemStatus = (
        "declared" if all(address.status == "declared" for address in addresses) else "differs"
    )
    return item.model_copy(update={"status": status, "addresses": addresses})


def _address_status(
    address: ProposedAddress, values: Mapping[str, tuple[str, ...]]
) -> ProposedAddress:
    current = values.get(address.environment.casefold())
    if not current:
        return address.model_copy(update={"status": "new", "yours": None})
    if address.address in current:
        return address.model_copy(update={"status": "declared", "yours": None})
    return address.model_copy(update={"status": "differs", "yours": current[0]})
