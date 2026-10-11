"""``hub setup``'s identity step: report the developer's identity, or propose and write it.

The identity home (the hub's main checkout) holds the developer's ``hub.local.json``. An
existing file is never rewritten: invalid, it is reported; valid, or when ``hub.json`` sets
every identity key, the identity is resolved as every command resolves it, git read only for
the keys no file sets. Otherwise the keys ``hub.json`` leaves unset are proposed from the
hub's git config, all or nothing: the proposal goes to stderr, then ``--yes`` writes it, a
terminal is asked, and no terminal writes nothing. The write never replaces a file
(``exclusive_write``). Then, when the file exists, ``gitignore_items`` asks the hub's git
whether it ignores it. Only the checklist goes to stdout. ``stdin_is_tty`` is a seam the tests
replace (docs/design/developer-identity.md).
"""

import os
import shutil
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

import typer

from agent_hub.cli.child_process import run_child
from agent_hub.cli.effective_config import git_identity_reader
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.cli.exclusive_write import write_exclusive
from agent_hub.cli.hub_config_reader import local_lines, read_local_json
from agent_hub.core.hub_config.effective_identity import (
    GitReader,
    IdentityKey,
    IdentityValues,
    ResolvedIdentity,
    Sourced,
    no_prefix_lines,
    resolve_identity,
)
from agent_hub.core.hub_config.local_config import LOCAL_FILE, LocalConfig, local_identity_bytes
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.workspace.setup_checklist import (
    PROBE_TIMEOUT_SECONDS,
    ChecklistItem,
    IdentityGap,
    git_lacks_item,
    gitignore_item,
    identity_missing_item,
    identity_resolved_item,
    identity_written_item,
    invalid_prefix_item,
    sourced_identity_text,
    write_error_item,
)

# An answer is read up to this many bytes; one that fills them without ending is no ``y``.
ANSWER_LIMIT: Final = 64
_YES: Final = frozenset({"y", "yes"})
_NO_VALUES: Final = IdentityValues(branch_prefix=None, author_name=None, author_email=None)
_GIT_KEYS: Final = (IdentityKey.AUTHOR_NAME, IdentityKey.AUTHOR_EMAIL)
# check-ignore's exit when the path is not ignored; 0 is ignored, 128 an error (no repo).
_NOT_IGNORED: Final = 1


def stdin_is_tty() -> bool:
    """Whether stdin is a terminal, where the developer can answer (tests replace this)."""
    return sys.stdin.isatty()


def identity_items(
    config: HubConfig, *, home: Path, is_confirmed_by_flag: bool
) -> list[ChecklistItem]:
    """The ``identity`` item, after writing ``home``'s ``hub.local.json`` when it is proposed
    and confirmed (``--yes`` or a ``y`` on the terminal)."""
    local = read_local_json(home / LOCAL_FILE)
    if not isinstance(local, LocalConfig):
        return [identity_missing_item(IdentityGap.INVALID_LOCAL, sub_lines=local_lines(local))]
    hub = IdentityValues.of(config.project)
    unset = [key for key in IdentityKey if hub.get(key) is None]
    read_git, git_problem = git_identity_reader(home)
    if os.path.lexists(home / LOCAL_FILE) or not unset:
        return [_resolved_item(local, hub=hub, read_git=read_git, git_problem=git_problem)]
    proposed = resolve_identity(local=_NO_VALUES, hub=hub, keys=unset, read_git=read_git)
    gap = _proposal_gap(proposed, git_problem=git_problem)
    if gap is not None:
        return [gap]
    values = {key: value for key, value in proposed.values.items() if value is not None}
    return [_write_item(values, home=home, is_confirmed_by_flag=is_confirmed_by_flag)]


def gitignore_items(home: Path, *, env: Mapping[str, str]) -> list[ChecklistItem]:
    """The ``gitignore`` item when ``home`` holds a ``hub.local.json`` its git does not ignore.

    Only a clear answer counts: no file, no git, a folder that is no repo, a timeout or any
    other exit gives no item. ``.gitignore`` is never edited.
    """
    if not os.path.lexists(home / LOCAL_FILE):
        return []
    found = shutil.which("git", path=env.get("PATH", os.defpath))
    if found is None:
        return []
    argv = [os.path.abspath(found), "-C", str(home), "check-ignore", "-q", LOCAL_FILE]
    try:
        result = run_child(argv, cwd=home, env=env, timeout=PROBE_TIMEOUT_SECONDS)
    except ChildTimedOutError, OSError:
        return []
    return [gitignore_item()] if result.returncode == _NOT_IGNORED else []


def _resolved_item(
    local: LocalConfig,
    *,
    hub: IdentityValues,
    read_git: GitReader,
    git_problem: Callable[[], str | None],
) -> ChecklistItem:
    resolved = resolve_identity(
        local=IdentityValues.of(local.project), hub=hub, keys=IdentityKey, read_git=read_git
    )
    lacking = [key for key in _GIT_KEYS if resolved.values[key] is None]
    if lacking:
        return git_lacks_item(lacking, rejected=resolved.rejected, git_problem=git_problem())
    if resolved.values[IdentityKey.BRANCH_PREFIX] is None:
        reasons = no_prefix_lines(
            email=resolved.email,
            git_problem=git_problem(),
            is_email_rejected=IdentityKey.AUTHOR_EMAIL in resolved.rejected,
        )
        return identity_missing_item(IdentityGap.NO_PREFIX, sub_lines=reasons)
    return identity_resolved_item(
        {key: value for key, value in resolved.values.items() if value is not None}
    )


def _proposal_gap(
    proposed: ResolvedIdentity, *, git_problem: Callable[[], str | None]
) -> ChecklistItem | None:
    """Why the proposal cannot be written (git lacks a key, no valid prefix), or None."""
    lacking = [key for key in _GIT_KEYS if key in proposed.values and proposed.values[key] is None]
    if lacking:
        return git_lacks_item(lacking, rejected=proposed.rejected, git_problem=git_problem())
    is_prefix_missing = (
        IdentityKey.BRANCH_PREFIX in proposed.values
        and proposed.values[IdentityKey.BRANCH_PREFIX] is None
    )
    if not is_prefix_missing:
        return None
    # The prefix is wanted, so the email was too: from hub.json, or from git and then valid
    # (else it is lacking above). A prefix is missing only for an email it cannot come from.
    assert proposed.email is not None  # noqa: S101 - narrows the type; see the comment above
    return invalid_prefix_item(proposed.email)


def _write_item(
    values: Mapping[IdentityKey, Sourced], *, home: Path, is_confirmed_by_flag: bool
) -> ChecklistItem:
    content = local_identity_bytes({key.value: value.value for key, value in values.items()})
    if not isinstance(content, bytes):
        # The proposed values passed the shapes the file checks: only its size is left.
        return identity_missing_item(IdentityGap.TOO_LARGE)
    shown_home = one_line(str(home))
    typer.echo(
        f"hub setup: proposed {LOCAL_FILE} in {shown_home}: {sourced_identity_text(values)}",
        err=True,
    )
    if not is_confirmed_by_flag:
        if not stdin_is_tty():
            return identity_missing_item(IdentityGap.NO_TERMINAL)
        typer.echo(f"Write {shown_home}/{LOCAL_FILE}? [y/N] ", err=True, nl=False)
        if not _is_yes(sys.stdin.buffer.readline(ANSWER_LIMIT)):
            return identity_missing_item(IdentityGap.DECLINED)
    try:
        is_written = write_exclusive(home, LOCAL_FILE, content)
    except OSError as error:
        # The error's own text names the paths: only the reason is shown.
        return write_error_item(error.strerror or type(error).__name__)
    if not is_written:
        return identity_missing_item(IdentityGap.APPEARED)
    return identity_written_item(values)


def _is_yes(answer: bytes) -> bool:
    """Whether the answer read is ``y`` or ``yes`` (any case, spaces around).

    An answer that fills ``ANSWER_LIMIT`` bytes without a newline was cut: it is no ``y``.
    Bytes that are not UTF-8 are replaced, so they never match and never raise.
    """
    if len(answer) >= ANSWER_LIMIT and not answer.endswith(b"\n"):
        return False
    return answer.decode("utf-8", errors="replace").strip().lower() in _YES
