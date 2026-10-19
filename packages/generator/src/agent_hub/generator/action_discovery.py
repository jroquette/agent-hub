"""Find the actions a hub has: ``actions/<pack>/<name>.yaml`` and their scripts (ADR 0041,
docs/design/scenarios.md § Actions and the script contract).

Each document is read through ``workflow_yaml`` (strict YAML, 256 KiB, the line of each key) and
parsed by core's ``parse_action``; a problem names the file (relative to the hub), the line and
the key, and never stops the scan. On top of the model's rules: the name is the file's stem, the
document is not a link, the script is a regular file under the pack's ``scripts/`` whose real path
is the path itself (no link, so it never leaves the pack), and ``output_format`` is a valid JSON
Schema. At most ``MAX_HUB_ACTIONS`` files are read; past that the root gets one problem.

Limit: as for workflows, a path is checked, then read; a link swapped in between could be followed.
The packs are the hub owner's own files.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from agent_hub.core.scenarios.action_catalog import (
    HUB_ACTIONS_FOLDER,
    ActionEntry,
    action_content_hash,
)
from agent_hub.core.scenarios.action_document import (
    SCRIPTS_FOLDER,
    ActionDocument,
    parse_action,
)
from agent_hub.core.workflows.catalog import WorkflowFile
from agent_hub.core.workflows.document import WorkflowLoadError, WorkflowProblem
from agent_hub.generator.workflow_discovery import (
    PackPathError,
    read_inside_pack,
    resolve_pack_file,
)
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs
from agent_hub.generator.workflow_yaml import LoadedWorkflow, WorkflowFileError, load_workflow_bytes

ACTION_SUFFIX: Final = ".yaml"
MAX_HUB_ACTIONS: Final = 200


@dataclass(frozen=True, kw_only=True, slots=True)
class ActionProblem:
    """Why a file or folder was left out: ``file`` relative to the hub; ``line`` (1-based) and
    ``key`` when known."""

    file: str
    line: int | None
    key: str | None
    reason: str

    def __str__(self) -> str:
        where = self.file if self.line is None else f"{self.file}:{self.line}"
        return (
            f"{where}: {self.reason}" if self.key is None else f"{where}: {self.key}: {self.reason}"
        )


@dataclass(frozen=True, kw_only=True, slots=True)
class ActionDiscovery:
    """The actions that loaded, by pack then name, and the problems found."""

    actions: tuple[ActionEntry, ...]
    problems: tuple[ActionProblem, ...]


def discover_actions(hub_root: Path) -> ActionDiscovery:
    """The hub's actions; a missing ``actions/`` reads as none. Every action is a draft here."""
    scan = _Scan(hub_root=hub_root)
    folder = hub_root / HUB_ACTIONS_FOLDER
    if folder.is_symlink():
        scan.problem(folder, "the actions folder is a link; it is not read")
    else:
        scan.root(folder)
    return ActionDiscovery(actions=tuple(scan.found), problems=tuple(scan.problems))


@dataclass(kw_only=True, slots=True)
class _Scan:
    hub_root: Path
    found: list[ActionEntry] = field(default_factory=list)
    problems: list[ActionProblem] = field(default_factory=list)
    read: int = 0

    def root(self, folder: Path) -> None:
        for entry in self._entries(folder):
            path = Path(entry.path)
            if entry.is_symlink():
                self.problem(path, "a pack folder is a link; it is not read")
            elif entry.is_dir(follow_symlinks=False):
                if not self._pack(path):
                    reason = f"more than {MAX_HUB_ACTIONS} action files; the rest is not read"
                    self.problem(folder, reason)
                    return
            elif path.suffix == ACTION_SUFFIX:
                self.problem(path, "an action file belongs in a pack folder")

    def _pack(self, pack_root: Path) -> bool:
        """Read the pack's action files; False once the budget is spent."""
        for entry in self._entries(pack_root):
            path = Path(entry.path)
            if path.suffix != ACTION_SUFFIX or entry.is_dir():
                continue
            if self.read >= MAX_HUB_ACTIONS:
                return False
            self.read += 1
            if entry.is_symlink():
                self.problem(path, "an action file is a link; it is not read")
            else:
                self._take(pack_root, path)
        return True

    def _take(self, pack_root: Path, path: Path) -> None:
        content = read_inside_pack(pack_root, path)
        if isinstance(content, str):
            self.problem(path, content)
            return
        try:
            loaded = load_workflow_bytes(content, source=str(path))
        except WorkflowFileError as error:
            self.problem(path, error.reason, line=error.line)
            return
        try:
            document = parse_action(loaded.document)
        except WorkflowLoadError as error:
            for item in error.problems:
                self._at(path, loaded, item)
            return
        if document.name != path.stem:
            reason = f"name {document.name!r} is not the file name {path.stem!r}"
            self._at(path, loaded, WorkflowProblem(("name",), reason))
            return
        self._found(pack_root, path, content, loaded=loaded, document=document)

    def _found(
        self,
        pack_root: Path,
        path: Path,
        content: bytes,
        *,
        loaded: LoadedWorkflow,
        document: ActionDocument,
    ) -> None:
        script = _script_bytes(pack_root, document.script)
        if isinstance(script, str):
            self._at(path, loaded, WorkflowProblem(("script",), script))
            return
        if schema_problems := JsonSchemaOutputs().schema_problems(document.output_format):
            reason = "not a valid JSON Schema: " + "; ".join(schema_problems)
            self._at(path, loaded, WorkflowProblem(("output_format",), reason))
            return
        document_path = self._shown(path)
        script_path = self._shown(pack_root / document.script)
        self.found.append(
            ActionEntry(
                pack=pack_root.name,
                document=document,
                document_path=document_path,
                script_path=script_path,
                content_hash=action_content_hash(
                    document_path=document_path,
                    document=content,
                    script_path=script_path,
                    script=script,
                ),
                draft=True,
            )
        )

    def _at(self, path: Path, loaded: LoadedWorkflow, item: WorkflowProblem) -> None:
        line = WorkflowFile(file="", stem="", content=None, lines=loaded.lines).line_of(item.loc)
        self.problems.append(
            ActionProblem(file=self._shown(path), line=line, key=item.key, reason=item.message)
        )

    def problem(self, path: Path, reason: str, *, line: int | None = None) -> None:
        self.problems.append(
            ActionProblem(file=self._shown(path), line=line, key=None, reason=reason)
        )

    def _shown(self, path: Path) -> str:
        """``path`` relative to the hub, so no absolute path reaches a message."""
        return path.relative_to(self.hub_root).as_posix()

    def _entries(self, folder: Path) -> list[os.DirEntry[str]]:
        try:
            with os.scandir(folder) as listing:
                entries = [entry for entry in listing if not entry.name.startswith(".")]
        except FileNotFoundError:
            return []
        except OSError as error:
            self.problem(folder, f"cannot read: {error.strerror or type(error).__name__}")
            return []
        return sorted(entries, key=lambda entry: entry.name)


def _script_bytes(pack_root: Path, script: str) -> bytes | str:
    """The script's bytes, or why it cannot be an action's script."""
    relative = script.removeprefix(f"{SCRIPTS_FOLDER}/")
    try:
        real = resolve_pack_file(pack_root, SCRIPTS_FOLDER, relative)
    except PackPathError as error:
        return str(error)
    if real != pack_root.resolve() / script:
        return f"{script} is a link; an action's script is read by its real path"
    try:
        return real.read_bytes()
    except OSError as error:
        return f"cannot read {script}: {error.strerror or type(error).__name__}"
