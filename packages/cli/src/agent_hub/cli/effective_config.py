"""The config a command uses: ``hub.json`` with the developer's ``hub.local.json`` over it.

``hub.json`` is read from the hub root as before; ``hub.local.json`` from the identity home, the
hub's main checkout (``hub_root.local_home``), so a hub worktree uses the developer's file. A
local key replaces ``hub.json``'s; an absent file changes nothing. Git, for the identity keys no
file sets, is read only when a caller asks (docs/design/developer-identity.md).
"""

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import NamedTuple

import typer

from agent_hub.cli.child_process import git_env
from agent_hub.cli.git_defaults import read_git_defaults
from agent_hub.cli.hub_config_reader import (
    FAILURE,
    FILE_LABEL,
    load_hub_config_or_exit,
    local_lines,
    read_local_json,
)
from agent_hub.cli.hub_root import local_home
from agent_hub.cli.run_children import SESSION_HIDDEN, without
from agent_hub.core.hub_config.effective_identity import (
    GitReader,
    IdentityKey,
    IdentityValues,
    effective_config,
    no_prefix_lines,
    resolve_identity,
)
from agent_hub.core.hub_config.local_config import LOCAL_FILE, LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem


class EffectiveConfig(NamedTuple):
    """The merged config, the local file it took values from, and the identity home."""

    config: HubConfig
    local: LocalConfig
    home: Path


def effective_or_problems(
    config: HubConfig, *, home: Path
) -> EffectiveConfig | tuple[ConfigProblem, ...]:
    """``config`` merged with ``home``'s ``hub.local.json``, or that file's problems."""
    local = read_local_json(home / LOCAL_FILE)
    if not isinstance(local, LocalConfig):
        return local
    return EffectiveConfig(config=effective_config(config, local), local=local, home=home)


def load_effective_config_or_exit(
    root: Path, *, environ: Mapping[str, str] = os.environ
) -> EffectiveConfig:
    """The effective config of the hub at ``root``; exit 1 with each file's lines when invalid."""
    config = load_hub_config_or_exit(root / FILE_LABEL)
    # No token reaches git, which only looks for the main checkout.
    home = local_home(root, environ=without(environ, SESSION_HIDDEN))
    loaded = effective_or_problems(config, home=home)
    if not isinstance(loaded, EffectiveConfig):
        for line in local_lines(loaded):
            typer.echo(line, err=True)
        raise typer.Exit(FAILURE)
    return loaded


def git_identity_reader(home: Path) -> tuple[GitReader, Callable[[], str | None]]:
    """A ``GitReader`` that reads git config in ``home``, and the last reason git gave none.

    Git's location variables are dropped, so ``home``'s repo is read, never one they name.
    """
    problems: list[str] = []

    def read(keys: frozenset[str]) -> Mapping[str, str]:
        env = git_env(without(os.environ, SESSION_HIDDEN), optional_locks=False)
        defaults = read_git_defaults(missing=keys, target=home, env=env)
        problems.extend(defaults.problems.values())
        return defaults.values

    def last_problem() -> str | None:
        return problems[-1] if problems else None

    return read, last_problem


def branch_prefix_or_lines(
    effective: EffectiveConfig, *, read_git: GitReader | None = None
) -> str | list[str]:
    """The developer's branch prefix, or the lines that say why there is none.

    Git, in the identity home unless ``read_git`` is given, is read only when no file sets the
    prefix, and then only for the email.
    """
    git_problem = _no_git_problem
    if read_git is None:
        read_git, git_problem = git_identity_reader(effective.home)
    resolved = resolve_identity(
        local=IdentityValues.of(effective.local.project),
        # Merged: a key the local file sets is found there first and keeps its source.
        hub=IdentityValues.of(effective.config.project),
        keys=(IdentityKey.BRANCH_PREFIX,),
        read_git=read_git,
    )
    prefix = resolved.values[IdentityKey.BRANCH_PREFIX]
    if prefix is not None:
        return prefix.value
    return no_prefix_lines(
        email=resolved.email,
        git_problem=git_problem(),
        is_email_rejected=IdentityKey.AUTHOR_EMAIL in resolved.rejected,
    )


def _no_git_problem() -> str | None:
    # A reader the caller gives says nothing of why git gave no value.
    return None
