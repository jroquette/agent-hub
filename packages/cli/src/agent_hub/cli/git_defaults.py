"""The defaults ``hub init`` reads from git: the author and the hub repo (spec Q-8).

Git is read, never written: one ``git config --get <key>`` per missing value, plus
``git rev-parse --show-toplevel`` before the remote, each with a timeout and the environment
unchanged. A remote URL can carry a credential, so it never leaves this module: only the
parsed ``owner/name`` does, and no message or exception quotes the URL.
"""

import contextlib
import os
import re
import shutil
import signal
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from pydantic import TypeAdapter, ValidationError

from agent_hub.core.hub_config.model import GitHubRepo

# The hub.json values git can supply, by their key in ``project``.
AUTHOR_NAME = "author_name"
AUTHOR_EMAIL = "author_email"
HUB_REPO = "hub_repo"
# Why a value is missing when git itself could not answer.
GIT_NOT_FOUND = "git not found"
GIT_TIMED_OUT = "git timed out"
GIT_FAILED = "git could not run"
GIT_TIMEOUT_SECONDS = 10.0

# Read in this order; hub_repo last, since it takes two calls.
_READ_ORDER = (AUTHOR_NAME, AUTHOR_EMAIL, HUB_REPO)
_CONFIG_KEYS = {AUTHOR_NAME: "user.name", AUTHOR_EMAIL: "user.email"}
_REMOTE_KEY = "remote.origin.url"

# The three URL forms of a GitHub remote. The host is exactly github.com; the https form may
# carry a userinfo (a user or a token), limited to RFC 3986's characters so that a host cannot
# hide in front of it behind ``#``, ``?``, ``/`` or another ``@``.
_GITHUB_REMOTE = re.compile(
    r"(?:git@github\.com:"
    r"|ssh://git@github\.com/"
    r"|https://(?:[A-Za-z0-9._~%!$&'()*+,;=:-]*@)?github\.com/)"
    r"(?P<path>.*)"
)
_GIT_SUFFIX = ".git"
# The model's own shape of ``owner/name``, so a parsed value is one hub.json accepts.
_GITHUB_REPO: TypeAdapter[str] = TypeAdapter(GitHubRepo)


def hub_repo_from_remote(url: str) -> str | None:
    """``owner/name`` of a GitHub remote URL, or None for any other host or shape."""
    matched = _GITHUB_REMOTE.fullmatch(url)
    if matched is None:
        return None
    candidate = matched["path"].removesuffix(_GIT_SUFFIX)
    try:
        return _GITHUB_REPO.validate_python(candidate)
    except ValidationError:
        # The error would quote the input: it is dropped, not chained.
        return None


class GitDefaults(NamedTuple):
    """The values git supplied, and for the others why git could not answer.

    A key in neither mapping is simply missing: git holds no value, or the remote is not a
    GitHub URL of the hub (its text is never kept).
    """

    values: Mapping[str, str]
    problems: Mapping[str, str]


def read_git_defaults(
    *, missing: frozenset[str], target: Path, timeout: float = GIT_TIMEOUT_SECONDS
) -> GitDefaults:
    """Read from git only the keys in ``missing``, in ``target`` if it is a folder, else the cwd.

    The remote is read only when ``target`` is the top of a git work tree, so a parent repo's
    remote is never taken. Git missing, failing to start or running past ``timeout`` seconds
    stops the reading: every key not yet read gets that reason.
    """
    unknown = missing - set(_READ_ORDER)
    if unknown:
        raise ValueError(f"not a git default: {', '.join(sorted(unknown))}")
    keys = [key for key in _READ_ORDER if key in missing]
    if not keys:
        return GitDefaults(values={}, problems={})
    git = _Git.find(target=target, timeout=timeout)
    values: dict[str, str] = {}
    for key in keys:
        value = git.hub_repo(target) if key == HUB_REPO else git.config(_CONFIG_KEYS[key])
        if value is not None:
            values[key] = value
    failure = git.failure
    problems = {key: failure for key in keys if key not in values} if failure else {}
    return GitDefaults(values=values, problems=problems)


@dataclass(kw_only=True, slots=True)
class _Git:
    """Runs read-only git calls; after the first failure it runs nothing and keeps the reason."""

    executable: str | None
    cwd: Path | None
    timeout: float
    failure: str | None = None

    @classmethod
    def find(cls, *, target: Path, timeout: float) -> _Git:
        found = shutil.which("git")
        # PATH may hold a relative folder, found from the process cwd; git runs elsewhere.
        executable = None if found is None else os.path.abspath(found)
        cwd = target if target.is_dir() else None
        return cls(
            executable=executable,
            cwd=cwd,
            timeout=timeout,
            failure=GIT_NOT_FOUND if executable is None else None,
        )

    def config(self, key: str) -> str | None:
        return self._run("config", "--get", key)

    def hub_repo(self, target: Path) -> str | None:
        if self.cwd is None:
            # An absent target (or a file) is no work tree top: the cwd's repo is not the hub.
            return None
        top = self._run("rev-parse", "--show-toplevel")
        if top is None or os.path.realpath(top) != os.path.realpath(target):
            return None
        url = self._run("config", "--get", _REMOTE_KEY)
        return None if url is None else hub_repo_from_remote(url)

    def _run(self, *arguments: str) -> str | None:
        if self.failure is not None or self.executable is None:
            return None
        try:
            output = self._output([self.executable, *arguments])
        except subprocess.TimeoutExpired:
            self.failure = GIT_TIMED_OUT
            return None
        except FileNotFoundError:
            self.failure = GIT_NOT_FOUND
            return None
        except OSError:
            self.failure = GIT_FAILED
            return None
        return None if output is None else _decoded_value(output)

    def _output(self, argv: list[str]) -> bytes | None:
        # A new session, so a timeout kills git and every child it started: a child left
        # running would hold stdout open and the read would never end.
        with subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            argv,
            cwd=self.cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        ) as child:
            try:
                output, _ = child.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGKILL)
                child.communicate()
                raise
        return output if child.returncode == 0 else None


def _decoded_value(output: bytes) -> str | None:
    try:
        text = output.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return text.removesuffix("\n") or None
