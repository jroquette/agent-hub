"""``hooks.guard-extension``: the project's guard extension is one the base guard can call (Q-15).

The base guard runs ``plugin/<project>/hooks/project_guard.py`` on the system ``python3`` (3.9 or
newer) and calls ``check(event, cfg)`` with two positional arguments (docs/design/
hub-generator.md § Hooks and plugin wiring). The rule reads the file statically: it must be a
regular UTF-8 file that ``ast.parse`` accepts as Python 3.9, whose last top-level binding of
``check`` is a plain ``def`` with exactly two positional parameters (positional-only or regular,
any names), no ``*args``, and a default for each keyword-only one. No file: nothing to check.
The project's code is never imported or run.
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
NOT_REGULAR: Final = "not a regular file"
NOT_READ: Final = "content was not read, so it cannot be checked"
NOT_TEXT: Final = "not UTF-8 text without NUL bytes"
NOT_PARSED: Final = "does not parse as Python 3.9"
TOO_COMPLEX: Final = "too complex to parse"
NO_CHECK: Final = "defines no top-level def check"
IS_ASYNC: Final = "check is async; the guard calls it as a plain function"
GUARD_ARGUMENTS: Final = 2


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
    text = text_of(entry)
    if text is None:
        return _Problem(NOT_TEXT)
    parsed = _parsed(text)
    if isinstance(parsed, _Problem):
        return parsed
    return _check_problem(parsed)


def _parsed(text: str) -> ast.Module | _Problem:
    """The module's tree, or why it has none; the problem is built outside the ``try``."""
    outcome: ast.Module | SyntaxError | None
    try:
        outcome = ast.parse(text, feature_version=HOOKS_PYTHON)
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
    defined = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "check"
    ]
    if not defined:
        return _Problem(NO_CHECK)
    # The last definition is the module's binding of ``check`` when the guard calls it.
    check = defined[-1]
    message = _signature_problem(check)
    return None if message is None else _Problem(message, line=check.lineno)


def _signature_problem(check: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    if isinstance(check, ast.AsyncFunctionDef):
        return IS_ASYNC
    arguments = check.args
    if arguments.vararg is not None:
        return (
            f"check takes *{arguments.vararg.arg}; "
            f"the guard passes exactly {GUARD_ARGUMENTS} arguments (event, cfg)"
        )
    for keyword, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True):
        if default is None:
            return f"check's keyword-only parameter {keyword.arg} has no default"
    count = len(arguments.posonlyargs) + len(arguments.args)
    if count != GUARD_ARGUMENTS:
        noun = "parameter" if count == 1 else "parameters"
        return (
            f"check takes {count} positional {noun}; "
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
