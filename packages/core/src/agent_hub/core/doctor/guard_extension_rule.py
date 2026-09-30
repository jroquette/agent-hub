"""``hooks.guard-extension``: the project's guard extension is one the base guard can call (E26).

The base guard runs ``plugin/<project>/hooks/project_guard.py`` on the system ``python3`` (3.9 or
newer), loads it by path and calls ``check(event, cfg)`` with two positional arguments (docs/design/
hub-generator.md § Hooks and plugin wiring). The rule reads the file statically, as the runner's
loader would: a regular file of at most 1 MiB, UTF-8 without NUL bytes, that ``ast.parse`` accepts
from its raw bytes (so a ``# coding:`` line and a BOM count as they do for the loader) as Python
3.9. The 3.9 check is best-effort: ``feature_version`` does not catch every newer syntax (newer
f-string forms pass). The last top-level statement that binds ``check`` (a def, class, import,
assignment or ``del``) must be a plain ``def`` that ``check(event, cfg)`` can call: at most two
required positional parameters, room for two (or ``*args``), and a default for each keyword-only
one. No file: nothing to check. The project's code is never imported or run.
"""

import ast
from collections.abc import Iterable
from typing import Final, NamedTuple

from agent_hub.core.doctor.finding import Finding, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot, guard_extension_path, text_of
from agent_hub.core.hub_config.doctor_rules import GUARD_EXTENSION_RULE, RULE_MODULES, Severity
from agent_hub.core.hub_files.tree_snapshot import FileEntry, TreeEntry

# The oldest ``python3`` the hooks run on.
HOOKS_PYTHON: Final = (3, 9)
FIX: Final = "make it a UTF-8 Python 3.9 file with a top-level def check(event, cfg)"
NOT_READ_FIX: Final = "run hub doctor again"
TOO_LARGE_FIX: Final = "keep it under 1 MiB"
NOT_REGULAR: Final = "not a regular file"
NOT_READ: Final = "content was not read, so it cannot be checked"
NOT_TEXT: Final = "not UTF-8 text without NUL bytes"
NOT_PARSED: Final = "does not parse as Python 3.9"
TOO_COMPLEX: Final = "too complex to parse"
NO_CHECK: Final = "defines no top-level def check"
IS_ASYNC: Final = "check is async; the guard calls it as a plain function"
TOO_LARGE: Final = "too large to check ({size} bytes, limit 1 MiB)"
NOT_A_DEF: Final = "check is last bound by {kind} at line {line}, not a def"
GUARD_ARGUMENTS: Final = 2
MAX_BYTES: Final = 1 << 20


class _Problem(NamedTuple):
    """Why the extension cannot be called as the guard calls it: the finding's fields."""

    message: str
    line: int | None = None
    fix: str = FIX


def _guard_extension(snapshot: DoctorSnapshot) -> Iterable[Finding]:
    path = guard_extension_path(snapshot.hub_config)
    entry = snapshot.hub.entries.get(path)
    # Absent (or not reached by a failed read, which the runner reports): nothing to check.
    problem = None if entry is None else _problem_of(entry)
    if problem is None:
        return ()
    return (
        GUARD_EXTENSION.finding(
            path=path, line=problem.line, message=problem.message, fix=problem.fix
        ),
    )


def _problem_of(entry: TreeEntry) -> _Problem | None:
    if not isinstance(entry, FileEntry):
        return _Problem(NOT_REGULAR)
    if entry.content is None:
        return _Problem(NOT_READ, fix=NOT_READ_FIX)
    if len(entry.content) > MAX_BYTES:
        return _Problem(TOO_LARGE.format(size=len(entry.content)), fix=TOO_LARGE_FIX)
    if text_of(entry) is None:
        return _Problem(NOT_TEXT)
    parsed = _parsed(entry.content)
    if isinstance(parsed, _Problem):
        return parsed
    return _check_problem(parsed)


def _parsed(content: bytes) -> ast.Module | _Problem:
    """The module's tree, or why it has none; the problem is built outside the ``try``.

    The raw bytes are parsed, so the parser applies a coding cookie and skips a BOM as the
    loader does; an unknown or failing coding is a ``SyntaxError`` at line 0 (no line).
    """
    outcome: ast.Module | SyntaxError | None
    try:
        outcome = ast.parse(content, feature_version=HOOKS_PYTHON)
    except SyntaxError as error:
        outcome = error
    except MemoryError, RecursionError:
        # The parser's stack or the tree's depth ran out: the input, not the doctor, is at fault.
        outcome = None
    if outcome is None:
        return _Problem(TOO_COMPLEX)
    if isinstance(outcome, SyntaxError):
        return _Problem(f"{NOT_PARSED}: {outcome.msg}", line=outcome.lineno or None)
    return outcome


def _check_problem(module: ast.Module) -> _Problem | None:
    bindings = [node for node in module.body if _binds_check(node)]
    if not bindings:
        return _Problem(NO_CHECK)
    # The last binding is the module's ``check`` when the guard calls it.
    last = bindings[-1]
    if isinstance(last, ast.FunctionDef | ast.AsyncFunctionDef):
        message = _signature_problem(last)
    else:
        message = NOT_A_DEF.format(kind=_kind_of(last), line=last.lineno)
    return None if message is None else _Problem(message, line=last.lineno)


def _binds_check(node: ast.stmt) -> bool:
    """Whether a top-level statement binds the name ``check``."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return node.name == "check"
    if isinstance(node, ast.Import | ast.ImportFrom):
        return any(_imported_name(alias) == "check" for alias in node.names)
    targets: list[ast.expr]
    if isinstance(node, ast.Assign | ast.Delete):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign):
        targets = [] if node.value is None else [node.target]
    elif isinstance(node, ast.AugAssign):
        targets = [node.target]
    else:
        targets = []
    return any(_target_binds_check(target) for target in targets)


def _imported_name(alias: ast.alias) -> str:
    # ``import a.b`` binds ``a``; ``from m import b`` binds ``b``; ``as`` names the binding.
    return alias.asname or alias.name.partition(".")[0]


def _target_binds_check(target: ast.expr) -> bool:
    if isinstance(target, ast.Name):
        return target.id == "check"
    if isinstance(target, ast.Starred):
        return _target_binds_check(target.value)
    if isinstance(target, ast.Tuple | ast.List):
        return any(_target_binds_check(element) for element in target.elts)
    return False


def _kind_of(node: ast.stmt) -> str:
    kinds: tuple[tuple[type[ast.stmt], str], ...] = (
        (ast.ClassDef, "class"),
        (ast.Import, "import"),
        (ast.ImportFrom, "import"),
        (ast.AnnAssign, "annotated assignment"),
        (ast.AugAssign, "augmented assignment"),
        (ast.Delete, "del"),
    )
    return next((kind for type_, kind in kinds if isinstance(node, type_)), "assignment")


def _signature_problem(check: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Why ``check(event, cfg)`` would fail on this def, or ``None`` when the call binds."""
    if isinstance(check, ast.AsyncFunctionDef):
        return IS_ASYNC
    arguments = check.args
    for keyword, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True):
        if default is None:
            return f"check's keyword-only parameter {keyword.arg} has no default"
    positional = len(arguments.posonlyargs) + len(arguments.args)
    required = positional - len(arguments.defaults)
    if required > GUARD_ARGUMENTS:
        return (
            f"check requires {required} positional parameters; "
            f"the guard passes {GUARD_ARGUMENTS} (event, cfg)"
        )
    if positional < GUARD_ARGUMENTS and arguments.vararg is None:
        noun = "parameter" if positional == 1 else "parameters"
        return (
            f"check takes {positional} positional {noun}; "
            f"the guard passes {GUARD_ARGUMENTS} (event, cfg)"
        )
    return None


GUARD_EXTENSION: Final = Rule(
    id=GUARD_EXTENSION_RULE,
    severity=Severity.ERROR,
    summary="the project's guard extension parses as Python 3.9 and defines check(event, cfg)",
    module=RULE_MODULES.get(GUARD_EXTENSION_RULE),
    reads=frozenset(),
    check=_guard_extension,
)
