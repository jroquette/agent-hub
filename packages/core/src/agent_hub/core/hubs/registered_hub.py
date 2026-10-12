"""A registered hub (D18): the registry entry and the view the API shows for it."""

from pydantic import Field

from agent_hub.core.projects.project_views import LockState
from agent_hub.core.readmodels.view_types import ApiTimestamp, ViewModel


class RegisteredHub(ViewModel):
    """An entry of ``hubs.json``: an id minted at registration (UUIDv7), the path, when."""

    id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    added_at: ApiTimestamp


class ValidationProblem(ViewModel):
    """One problem of a hub's ``hub.json``, located by a JSON pointer."""

    pointer: str
    message: str


class HubView(ViewModel):
    """A registered hub as read now.

    ``valid`` is false when ``hub.json`` is unreadable or does not match the schema
    (``validation_errors``). A pin other than the running version is read anyway and shows as
    a warning ("pinned X, running Y").
    """

    id: str
    path: str
    added_at: ApiTimestamp
    project: str | None
    platform_pin: str | None
    running_version: str
    lock_version: str | None
    lock_state: LockState | None
    modules: tuple[str, ...]
    guard_ask_before_edit: tuple[str, ...]
    repos: tuple[str, ...]
    valid: bool
    validation_errors: tuple[ValidationProblem, ...] = ()
    warnings: tuple[str, ...] = ()
