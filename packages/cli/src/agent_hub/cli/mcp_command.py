"""``hub mcp``: the hub's knowledge as a local stdio MCP server for Claude Code (ADR 0044).

The only cli module that imports ``agent_hub.mcp_server`` (import contract), and only inside its
functions, so no other ``hub`` command loads the MCP SDK. The hub is resolved once, before the
protocol starts, the way ``hub search`` resolves it (O-1: nothing moves out of ``cli``): exit 2
when the folder is not a hub, 1 when ``hub.json`` or ``hub.local.json`` is not valid, each with
the existing lines on stderr and nothing on stdout. The checkout, the knowledge index, the
author and the branch prefix are then handed to ``mcp_server``; the index is opened on the first
``search`` only, so a database problem is a tool error, not a failed start.
"""

import os
import shutil
from collections.abc import Mapping
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Final

from agent_hub.cli.database_path import default_database_path
from agent_hub.cli.effective_config import git_identity_reader, load_effective_config_or_exit
from agent_hub.cli.hub_config_reader import DISTRIBUTION
from agent_hub.cli.knowledge_hub import knowledge_hub_or_exit
from agent_hub.core.hub_config.effective_identity import (
    IdentityKey,
    IdentityValues,
    resolve_identity,
)
from agent_hub.core.hub_config.local_config import LocalProject
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.knowledge.knowledge_index import KnowledgeIndex
from agent_hub.core.knowledge.sync_knowledge import KnowledgeCheckoutError
from agent_hub.core.learnings.brain_change_requests import CommitAuthor
from agent_hub.hub_git.knowledge_checkout import GitKnowledgeCheckout
from agent_hub.storage.knowledge_index import open_knowledge_index

if TYPE_CHECKING:
    from agent_hub.mcp_server.hub_context import HubContext, ProposalFacts

COMMAND: Final = "mcp"
DATABASE_VARIABLE: Final = "AGENT_HUB_DB"
SESSION_VARIABLE: Final = "CLAUDE_CODE_SESSION_ID"
NO_GIT: Final = "git is not on PATH; install git"


def mcp() -> None:
    """Serve the hub's brain and repo docs to Claude Code over stdio (MCP tools: search, read,
    propose)."""
    environ = dict(os.environ)
    hub = hub_context(environ)
    from agent_hub.mcp_server.server import serve  # noqa: PLC0415 - only hub mcp loads the SDK

    serve(hub, environ=environ)


def hub_context(environ: Mapping[str, str]) -> HubContext:
    """The hub ``hub mcp`` serves: ``hub search``'s hub, with the effective author and branch
    prefix (``hub.local.json``, ``hub.json``, git config) and the session id. Exits as
    ``hub search`` does when the folder is not a hub or its config is not valid."""
    from agent_hub.mcp_server.hub_context import HubContext  # noqa: PLC0415 - see mcp

    knowledge = knowledge_hub_or_exit(environ, command=COMMAND)
    effective = load_effective_config_or_exit(knowledge.checkout, environ=environ)
    snapshot = dict(environ)

    def checkout() -> GitKnowledgeCheckout:
        found = shutil.which("git", path=snapshot.get("PATH", os.defpath))
        if found is None:
            raise KnowledgeCheckoutError(NO_GIT)
        git = os.path.abspath(found)
        return GitKnowledgeCheckout(
            knowledge.checkout, knowledge.repo_dirs, git=git, environ=snapshot
        )

    def index() -> KnowledgeIndex:
        configured = snapshot.get(DATABASE_VARIABLE, "")
        path = Path(configured) if configured else default_database_path(snapshot)
        return open_knowledge_index(path)

    return HubContext(
        project=knowledge.project,
        hub_path=knowledge.key,
        repo_dirs=knowledge.repo_dirs,
        version=version(DISTRIBUTION),
        proposal=_proposal_facts(effective.config, effective.local.project, effective.home),
        session=snapshot.get(SESSION_VARIABLE),
        checkout=checkout,
        index=index,
    )


def _proposal_facts(config: HubConfig, local: LocalProject, home: Path) -> ProposalFacts:
    """The hub's repo and default branch, and the developer's effective identity, as ``hub web``
    resolves them for a learning decision: no prefix is ``""``; no name or email, no author."""
    from agent_hub.mcp_server.hub_context import ProposalFacts  # noqa: PLC0415 - see mcp

    read_git, _ = git_identity_reader(home)
    values = resolve_identity(
        local=IdentityValues.of(local),
        hub=IdentityValues.of(config.project),
        keys=tuple(IdentityKey),
        read_git=read_git,
    ).values
    prefix = values[IdentityKey.BRANCH_PREFIX]
    name, email = values[IdentityKey.AUTHOR_NAME], values[IdentityKey.AUTHOR_EMAIL]
    author = None
    if name is not None and email is not None:
        author = CommitAuthor(name=name.value, email=email.value)
    return ProposalFacts(
        hub_repo=config.project.hub_repo,
        default_branch=config.project.default_branch,
        branch_prefix="" if prefix is None else prefix.value,
        author=author,
    )
