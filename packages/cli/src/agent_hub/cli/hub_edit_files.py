"""The hub files that ``hub env`` and ``hub repo`` read and check around an edit.

``read_hub_files`` reads both files once, as bytes, and checks them as a read does;
``checked_documents`` checks an edited document the same way, then the rules across both files.
Each exits 1 with the files' lines when a check fails.
"""

import os
from importlib.metadata import version
from pathlib import Path
from typing import NamedTuple

from agent_hub.cli.command_exits import fail
from agent_hub.cli.hub_config_reader import (
    DISTRIBUTION,
    FILE_LABEL,
    hub_lines,
    load_hub_json_or_exit,
    local_lines,
)
from agent_hub.cli.hub_root import hub_root_or_exit, local_home
from agent_hub.cli.run_children import SESSION_HIDDEN, without
from agent_hub.core.hub_config.document_check import check_hub_document
from agent_hub.core.hub_config.effective_environments import local_environment_problems
from agent_hub.core.hub_config.environment_edits import Document
from agent_hub.core.hub_config.local_config import (
    LOCAL_FILE,
    LOCAL_FILE_MAX_BYTES,
    LocalConfig,
    check_local_document,
)
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.generator.hub_config_files import UnreadFile, parse_json, read_file_bytes


class HubFiles(NamedTuple):
    """Both files as read: each one's bytes (``None``: no ``hub.local.json``) and config."""

    hub_path: Path
    hub_content: bytes
    config: HubConfig
    local_path: Path
    local_content: bytes | None
    local: LocalConfig


def read_hub_files(*, command: str) -> HubFiles:
    """Both files, each read once as bytes; exit 1 when either is unusable."""
    root = hub_root_or_exit(os.environ, command=command)
    loaded = load_hub_json_or_exit(root / FILE_LABEL)
    # No token reaches git, which only looks for the main checkout.
    home = local_home(root, environ=without(os.environ, SESSION_HIDDEN))
    local_path = home / LOCAL_FILE
    found = read_file_bytes(local_path, max_bytes=LOCAL_FILE_MAX_BYTES)
    content: bytes | None = None
    local = LocalConfig()
    if isinstance(found, UnreadFile):
        if not found.is_missing:
            fail(*local_lines((found.problem,)))
    else:
        content = found
        parsed = parse_json(content)
        checked = (parsed,) if isinstance(parsed, ConfigProblem) else check_local_document(parsed)
        if not isinstance(checked, LocalConfig):
            fail(*local_lines(checked))
        local = checked
    across = local_environment_problems(loaded.config, local)
    if across:
        fail(*local_lines(across))
    return HubFiles(root / FILE_LABEL, loaded.content, loaded.config, local_path, content, local)


def checked_documents(
    edited: Document, files: HubFiles, *, is_local: bool
) -> tuple[HubConfig, LocalConfig]:
    """Both configs after the edit, checked as a read checks them; exit 1 with their lines."""
    config, local = files.config, files.local
    if is_local:
        checked_local = check_local_document(edited)
        if not isinstance(checked_local, LocalConfig):
            fail(*local_lines(checked_local))
        local = checked_local
    else:
        checked = check_hub_document(edited, running_version=version(DISTRIBUTION))
        if not isinstance(checked, HubConfig):
            fail(*hub_lines(checked))
        config = checked
    across = local_environment_problems(config, local)
    if across:
        # A hub.json change refused for the developer's file says so before that file's lines.
        prefix = (
            ()
            if is_local
            else (f"{FILE_LABEL}: not changed: {LOCAL_FILE} would no longer be valid",)
        )
        fail(*prefix, *local_lines(across))
    return config, local
