"""Find the actions a hub has: ``actions/<pack>/<name>.yaml`` and their scripts (ADR 0041,
docs/design/scenarios.md § Actions and the script contract).

Each document is read through ``workflow_yaml`` (strict YAML, 256 KiB, the line of each key) and
parsed by core's ``parse_action``; a problem names the file (relative to the hub), the line and
the key, and never stops the scan. On top of the model's rules: the name is the file's stem, the
document is not a link, the script is a regular file under the pack's ``scripts/`` whose real path
is the path itself (no link, so it never leaves the pack), and ``output_format`` is a valid JSON
Schema. Every other file under the pack's ``scripts/`` (``__pycache__`` aside, and not another
action's own script) is a helper the script may source: it is read once per pack, never through a
link, and joins each action's content hash and draft check. At most ``MAX_HUB_ACTIONS`` files are
read; past that the root gets one problem.

Limit: as for workflows, a path is checked, then read; a link swapped in between could be followed.
The packs are the hub owner's own files.
"""

import os
from collections.abc import Iterator
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
from agent_hub.generator.git_answers import git_answer
from agent_hub.generator.workflow_discovery import (
    PackPathError,
    read_inside_pack,
    resolve_pack_file,
)
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs
from agent_hub.generator.workflow_yaml import LoadedWorkflow, WorkflowFileError, load_workflow_bytes

ACTION_SUFFIX: Final = ".yaml"
MAX_HUB_ACTIONS: Final = 200
MAX_PACK_SCRIPT_FILES: Final = 200
PYTHON_CACHE: Final = "__pycache__"


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
    """The hub's actions, each a draft unless committed; a missing ``actions/`` reads as none."""
    scan = _Scan(hub_root=hub_root)
    folder = hub_root / HUB_ACTIONS_FOLDER
    if folder.is_symlink():
        scan.problem(folder, "the actions folder is a link; it is not read")
    else:
        scan.root(folder)
    uncommitted = _uncommitted(hub_root) if scan.found else None
    actions = tuple(
        entry.model_copy(update={"draft": _is_draft(scan.files[entry.document_path], uncommitted)})
        for entry in scan.found
    )
    return ActionDiscovery(actions=actions, problems=tuple(scan.problems))


def _uncommitted(hub_root: Path) -> frozenset[str] | None:
    """The hub-relative paths under ``actions/`` that differ from ``HEAD`` (staged, changed,
    untracked or ignored; a folder ends in ``/``), from one ``git status``; ``None`` when the
    hub is not in a git checkout or git cannot answer."""
    prefix = git_answer(("rev-parse", "--show-prefix"), cwd=hub_root)
    if prefix is None or prefix[0] != 0:
        return None
    status = git_answer(
        (
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignored=matching",
            "--",
            HUB_ACTIONS_FOLDER,
        ),
        cwd=hub_root,
    )
    if status is None or status[0] != 0:
        return None
    # Porcelain paths are relative to the repository's top; the hub may sit below it.
    hub_prefix = os.fsdecode(prefix[1]).strip("\n")
    paths: set[str] = set()
    records = iter(status[1].split(b"\0"))
    for record in records:
        if not record:
            continue
        # ``XY <path>``; a rename or copy is followed by a record holding its source path alone.
        paths.add(os.fsdecode(record[3:]).removeprefix(hub_prefix))
        if record[:1] in {b"R", b"C"} or record[1:2] in {b"R", b"C"}:
            paths.add(os.fsdecode(next(records, b"")).removeprefix(hub_prefix))
    return frozenset(paths)


def _is_draft(files: tuple[tuple[str, bytes], ...], uncommitted: frozenset[str] | None) -> bool:
    if uncommitted is None:
        return True
    return any(
        path in uncommitted
        or any(folder.endswith("/") and path.startswith(folder) for folder in uncommitted)
        for path, _ in files
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class _Parsed:
    """An action file that loaded, before its pack's scripts are pinned."""

    path: Path
    content: bytes
    loaded: LoadedWorkflow
    document: ActionDocument


@dataclass(kw_only=True, slots=True)
class _Scan:
    hub_root: Path
    found: list[ActionEntry] = field(default_factory=list)
    # Each action's files (its document, then its pack's scripts) and the bytes read, by
    # document path; each pack's scripts, read once.
    files: dict[str, tuple[tuple[str, bytes], ...]] = field(default_factory=dict)
    scripts: dict[Path, tuple[tuple[str, bytes], ...] | str] = field(default_factory=dict)
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
        parsed: list[_Parsed] = []
        within_budget = True
        for entry in self._entries(pack_root):
            path = Path(entry.path)
            if path.suffix != ACTION_SUFFIX or entry.is_dir():
                continue
            if self.read >= MAX_HUB_ACTIONS:
                within_budget = False
                break
            self.read += 1
            if entry.is_symlink():
                self.problem(path, "an action file is a link; it is not read")
            elif (item := self._take(pack_root, path)) is not None:
                parsed.append(item)
        # Another action's own script is not a helper of this one: only the other files are.
        declared = frozenset(self._shown(pack_root / item.document.script) for item in parsed)
        for item in parsed:
            self._found(pack_root, item, declared=declared)
        return within_budget

    def _take(self, pack_root: Path, path: Path) -> _Parsed | None:
        content = read_inside_pack(pack_root, path)
        if isinstance(content, str):
            self.problem(path, content)
            return None
        try:
            loaded = load_workflow_bytes(content, source=str(path))
        except WorkflowFileError as error:
            self.problem(path, error.reason, line=error.line)
            return None
        try:
            document = parse_action(loaded.document)
        except WorkflowLoadError as error:
            for item in error.problems:
                self._at(path, loaded, item)
            return None
        if document.name != path.stem:
            reason = f"name {document.name!r} is not the file name {path.stem!r}"
            self._at(path, loaded, WorkflowProblem(("name",), reason))
            return None
        return _Parsed(path=path, content=content, loaded=loaded, document=document)

    def _found(self, pack_root: Path, item: _Parsed, *, declared: frozenset[str]) -> None:
        path, content, loaded, document = item.path, item.content, item.loaded, item.document
        scripts = self._scripts_of(pack_root)
        problem = _script_problem(pack_root, document.script)
        if problem is not None or isinstance(scripts, str):
            reason = problem if problem is not None else str(scripts)
            self._at(path, loaded, WorkflowProblem(("script",), reason))
            return
        if schema_problems := JsonSchemaOutputs().schema_problems(document.output_format):
            reason = "not a valid JSON Schema: " + "; ".join(schema_problems)
            self._at(path, loaded, WorkflowProblem(("output_format",), reason))
            return
        document_path = self._shown(path)
        script_path = self._shown(pack_root / document.script)
        script = dict(scripts)[script_path]
        helpers = [file for file in scripts if file[0] not in declared]
        self.files[document_path] = ((document_path, content), (script_path, script), *helpers)
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
                    helpers=helpers,
                ),
                draft=True,
            )
        )

    def _scripts_of(self, pack_root: Path) -> tuple[tuple[str, bytes], ...] | str:
        """Every file under the pack's ``scripts/`` (``__pycache__`` aside) with its bytes, in
        path order, read once per pack; or why the pack's scripts cannot be pinned."""
        if pack_root not in self.scripts:
            self.scripts[pack_root] = self._read_scripts(pack_root)
        return self.scripts[pack_root]

    def _read_scripts(self, pack_root: Path) -> tuple[tuple[str, bytes], ...] | str:
        folder = pack_root / SCRIPTS_FOLDER
        if folder.is_symlink():
            return f"{SCRIPTS_FOLDER}/ is a link; a pack's scripts are read by their real path"
        found: list[tuple[str, bytes]] = []
        try:
            for path in _script_files(folder, pack_root) if folder.is_dir() else ():
                if len(found) >= MAX_PACK_SCRIPT_FILES:
                    return f"more than {MAX_PACK_SCRIPT_FILES} files under {SCRIPTS_FOLDER}/"
                found.append((self._shown(path), path.read_bytes()))
        except _ScriptsError as error:
            return str(error)
        except OSError as error:
            return f"cannot read {SCRIPTS_FOLDER}/: {error.strerror or type(error).__name__}"
        return tuple(sorted(found))

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


class _ScriptsError(Exception):
    """Why a pack's scripts cannot be pinned, as one line."""


def _script_files(folder: Path, pack_root: Path) -> Iterator[Path]:
    """Every regular file under ``folder``, ``__pycache__`` aside; raises ``_ScriptsError`` at a
    link or a special file (a link is never followed, so nothing leaves the pack)."""
    with os.scandir(folder) as listing:
        entries = sorted(listing, key=lambda entry: entry.name)
    for entry in entries:
        path = Path(entry.path)
        shown = path.relative_to(pack_root).as_posix()
        if entry.is_symlink():
            msg = f"{shown} is a link; a pack's scripts are read by their real path"
            raise _ScriptsError(msg)
        if entry.is_dir(follow_symlinks=False):
            if entry.name != PYTHON_CACHE:
                yield from _script_files(path, pack_root)
        elif entry.is_file(follow_symlinks=False):
            yield path
        else:
            raise _ScriptsError(f"{shown} is not a regular file")


def _script_problem(pack_root: Path, script: str) -> str | None:
    """Why ``script`` cannot be an action's script, or ``None``."""
    relative = script.removeprefix(f"{SCRIPTS_FOLDER}/")
    try:
        real = resolve_pack_file(pack_root, SCRIPTS_FOLDER, relative)
    except PackPathError as error:
        return str(error)
    if real != pack_root.resolve() / script:
        return f"{script} is a link; an action's script is read by its real path"
    return None
