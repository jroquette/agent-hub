"""The commit of the pinned release's tag, read with one ``git ls-remote`` (ADR 0054).

``hub sync`` fills core's ``ReleaseLookup`` port with ``lookup_release`` at a pin change, and
``hub doctor`` probes the tag with ``tag_commit`` when the lock records a commit. Both ask the
platform repository (``git+https://…`` from ``hub.json``, already validated: one host, safe path
segments, no ``@``) for the tag and its peeled ``^{}`` line, with no terminal prompt, within
``timeout`` seconds, keeping only the last ``OUTPUT_LIMIT`` bytes of each stream. A tag missing,
git missing, a refused transport or a timeout is never an exception: it is the answer.
"""

import os
import re
from typing import Final

from agent_hub.cli.child_process import git_env, run_child
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.hub_files.release_commit import (
    LookupFailure,
    ReleaseCommit,
    ReleaseLookup,
    commit_from_ls_remote,
)

# The time ``hub sync`` waits for the tag at a pin change, and ``hub doctor`` for its probe.
SYNC_LOOKUP_TIMEOUT: Final = 20.0
DOCTOR_PROBE_TIMEOUT: Final = 5.0
# Two short lines are expected; a larger answer keeps its end (a cut first line never matches).
OUTPUT_LIMIT: Final = 65536
# ``hub.json`` names the repository as pip does; git takes the URL after this prefix.
_PIP_GIT_PREFIX: Final = "git+"
# A reason is shown on one line; git's message is cut to this many characters.
_REASON_CHARS: Final = 200
# The ``user[:password]@`` part of a URL git names: a rewrite (``url.<base>.insteadOf``, as the CI
# template's ``x-access-token:<token>@``) can put a credential in the URL git prints.
_URL_CREDENTIALS: Final = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@")


def lookup_release(*, cwd: str) -> ReleaseLookup:
    """The ``ReleaseLookup`` ``hub sync`` injects: git runs in ``cwd`` (the hub), within
    ``SYNC_LOOKUP_TIMEOUT`` seconds."""

    def lookup(repository: str, version: str) -> ReleaseCommit | LookupFailure:
        found = tag_commit(repository, version, cwd=cwd, timeout=SYNC_LOOKUP_TIMEOUT)
        if isinstance(found, LookupFailure):
            return found
        if found is None:
            return LookupFailure(reason=f"{_shown(repository)} has no tag v{version}")
        return ReleaseCommit(commit=found, repository=repository)

    return lookup


def tag_commit(
    repository: str, version: str, *, cwd: str, timeout: float
) -> str | None | LookupFailure:
    """The commit tag ``v<version>`` names in ``repository``, ``None`` when the remote answered
    without the tag, or why it could not be read; git runs in ``cwd``."""
    url = repository.removeprefix(_PIP_GIT_PREFIX)
    tag = f"refs/tags/v{version}"
    env = git_env(os.environ, optional_locks=False) | {"GIT_TERMINAL_PROMPT": "0"}
    try:
        result = run_child(
            ["git", "ls-remote", url, tag, f"{tag}^{{}}"],
            cwd=cwd,
            env=env,
            timeout=timeout,
            output_limit=OUTPUT_LIMIT,
        )
    except ChildTimedOutError:
        return LookupFailure(reason=f"git ls-remote timed out after {timeout:g} s")
    except OSError as error:
        return LookupFailure(reason=f"git could not run: {_shown(str(error.strerror or error))}")
    if result.returncode != 0:
        lines = [line.strip() for line in result.stderr.decode(errors="replace").splitlines()]
        said = next((line for line in lines if line), f"git exited {result.returncode}")
        return LookupFailure(reason=_shown(said))
    return commit_from_ls_remote(result.stdout.decode(errors="replace"), version)


def _shown(text: str) -> str:
    """``text`` on one line, its control characters escaped and any URL's credentials removed, at
    most ``_REASON_CHARS`` long."""
    return one_line(_URL_CREDENTIALS.sub(r"\1", text))[:_REASON_CHARS]
