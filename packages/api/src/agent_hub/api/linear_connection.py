"""Connecting ``hub web`` to Linear from Settings: the key kept on this machine, and its check.

``hub web`` reads Linear with ``LINEAR_API_KEY`` (ADR 0025). Besides its own environment, the
key may now come from a file the owner fills from Settings, ``linear-api-key`` beside the hub
registry (``~/.config/agent-hub``), written with mode 0600 and never inside a repository.
``LinearEnviron`` is the environment the tracker adapters read: the process's own value wins,
else the file's, read at call time, so a key saved or removed while ``hub web`` runs takes
effect at once and survives a restart.

``LinearConnection`` checks the key with one ``viewer`` read (``graphql_viewer``), cached for
``CHECK_TTL`` unless a fresh check is asked; ``connect`` checks a new key first and saves it
only when Linear accepts it. The key is never returned, logged or put in a message.
"""

import os
import re
import threading
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final, Literal, override

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.core.errors import TrackerError
from agent_hub.tracker_linear.graphql_transport import LINEAR_API_KEY_VARIABLE, Post
from agent_hub.tracker_linear.graphql_viewer import LinearAccount, linear_account

KEY_FILE_NAME: Final = "linear-api-key"
CHECK_TTL: Final = timedelta(seconds=60)
MAX_KEY_CHARS: Final = 200
_KEY_PATTERN: Final = re.compile(r"[\x21-\x7e]+")

type KeySource = Literal["environment", "settings"]


class LinearKeyFile:
    """The key saved from Settings: one line in a 0600 file; empty or missing is no key."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> str:
        """The saved key, or "" when there is none (or it cannot be read)."""
        try:
            return self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def write(self, key: str) -> None:
        """Save ``key``, readable by this user only."""
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(key + "\n")
        os.chmod(self.path, 0o600)

    def delete(self) -> None:
        """Forget the saved key."""
        self.path.unlink(missing_ok=True)


class LinearEnviron(Mapping[str, str]):
    """``base`` with ``LINEAR_API_KEY`` from the key file when ``base`` has none."""

    def __init__(self, base: Mapping[str, str], key_file: LinearKeyFile) -> None:
        self._base = base
        self._key_file = key_file

    def source(self) -> KeySource | None:
        """Where the key comes from, or None when there is no key."""
        if self._base.get(LINEAR_API_KEY_VARIABLE):
            return "environment"
        if self._key_file.read():
            return "settings"
        return None

    @override
    def __getitem__(self, name: str) -> str:
        if name == LINEAR_API_KEY_VARIABLE and not self._base.get(name):
            saved = self._key_file.read()
            if saved:
                return saved
        return self._base[name]

    @override
    def __iter__(self) -> Iterator[str]:
        yield from self._base
        if LINEAR_API_KEY_VARIABLE not in self._base and self._key_file.read():
            yield LINEAR_API_KEY_VARIABLE

    @override
    def __len__(self) -> int:
        return sum(1 for _ in self)


class LinearAccountView(BaseModel):
    """The key's user and workspace."""

    model_config = ConfigDict(frozen=True)

    name: str
    email: str
    workspace: str
    url: str


class LinearConnectionView(BaseModel):
    """``GET /tracker/linear``: whether hub web reads Linear, as whom, or why not."""

    model_config = ConfigDict(frozen=True)

    connected: bool
    source: KeySource | None
    account: LinearAccountView | None
    problem: str | None
    problem_kind: str | None
    checked_at: datetime | None
    key_path: str


class LinearKeyBody(BaseModel):
    """``PUT /tracker/linear``: a Linear personal API key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_key: str = Field(min_length=1, max_length=MAX_KEY_CHARS)


type AccountOf = Callable[[Mapping[str, str]], LinearAccount]


class LinearConnection:
    """The Settings view of the Linear connection: its check, and the key's save and removal."""

    def __init__(
        self,
        environ: LinearEnviron,
        key_file: LinearKeyFile,
        *,
        clock: Callable[[], datetime],
        post: Post | None = None,
        account_of: AccountOf | None = None,
    ) -> None:
        self._environ = environ
        self._key_file = key_file
        self._clock = clock
        self._account_of: AccountOf = account_of or (lambda env: linear_account(env, post=post))
        self._guard = threading.Lock()
        self._last: tuple[str, LinearConnectionView] | None = None

    def status(self, *, fresh: bool = False) -> LinearConnectionView:
        """The connection, checked with Linear at most once per ``CHECK_TTL`` unless ``fresh``."""
        source = self._environ.source()
        if source is None:
            return self._view(source=None)
        key = self._environ[LINEAR_API_KEY_VARIABLE]
        with self._guard:
            last = self._last
        if (
            not fresh
            and last is not None
            and last[0] == key
            and last[1].checked_at is not None
            and self._clock() - last[1].checked_at < CHECK_TTL
        ):
            return last[1].model_copy(update={"source": source})
        view = self._check(self._environ, source=source)
        with self._guard:
            self._last = (key, view)
        return view

    def connect(self, api_key: str) -> LinearConnectionView:
        """Check ``api_key`` and save it when Linear accepts it; the view says which."""
        key = api_key.strip()
        if not _KEY_PATTERN.fullmatch(key):
            return self._view(
                source=self._environ.source(),
                problem="The key has a space or a character outside printable ASCII.",
                problem_kind="unauthorized",
            )
        view = self._check({LINEAR_API_KEY_VARIABLE: key}, source="settings")
        if view.connected:
            self._key_file.write(key)
            with self._guard:
                self._last = (key, view)
            source = self._environ.source()
            if source != "settings":
                # The environment's key still wins: show the connection hub web really uses.
                return self.status(fresh=True)
        return view

    def disconnect(self) -> LinearConnectionView:
        """Forget the key saved from Settings (an environment key stays)."""
        self._key_file.delete()
        with self._guard:
            self._last = None
        return self.status(fresh=True)

    def _check(self, environ: Mapping[str, str], *, source: KeySource) -> LinearConnectionView:
        try:
            account = self._account_of(environ)
        except TrackerError as error:
            return self._view(
                source=source,
                problem=f"{error.cause[:1].upper()}{error.cause[1:]}.",
                problem_kind=error.kind,
                checked_at=self._clock(),
            )
        return LinearConnectionView(
            connected=True,
            source=source,
            account=LinearAccountView(
                name=account.name,
                email=account.email,
                workspace=account.workspace,
                url=f"https://linear.app/{account.url_key}",
            ),
            problem=None,
            problem_kind=None,
            checked_at=self._clock(),
            key_path=str(self._key_file.path),
        )

    def _view(
        self,
        *,
        source: KeySource | None,
        problem: str | None = None,
        problem_kind: str | None = None,
        checked_at: datetime | None = None,
    ) -> LinearConnectionView:
        return LinearConnectionView(
            connected=False,
            source=source,
            account=None,
            problem=problem,
            problem_kind=problem_kind,
            checked_at=checked_at,
            key_path=str(self._key_file.path),
        )
