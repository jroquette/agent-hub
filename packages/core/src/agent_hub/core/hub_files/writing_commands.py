"""A model of Claude Code's permission rules, and the writing commands no allow rule may let run.

The test of the managed ``.claude/settings.json`` runs every command of ``WRITING_COMMANDS``
through ``effective_allows``, to prove that no allow rule lets a writing command run without a
prompt. The model lives in core, beside the other managed-settings facts, so that the doctor rule
``permissions.writing`` can hold a hub's own rules to it too.

The model:

- Only a ``Bash`` rule matches a command. ``Bash`` alone matches every command; any other rule
  that is not ``Bash(<pattern>)`` matches none.
- The command is split at ``&&``, ``||``, ``;``, ``|`` and newlines outside quotes, and the
  pattern must match one subcommand whole. The quotes stay in the text: a rule reads the literal
  text of the call.
- A pattern that ends with a space and ``*`` matches its prefix alone, or the prefix, a space and
  any text; the legacy ``:*`` suffix reads the same. Any other ``*`` matches any run of
  characters, the empty one included. Every other character is literal, so a rule without ``*``
  matches only its exact text.
- A deny wins: a command is allowed when some allow rule matches it and no deny rule does.

It models the matching Claude Code documents and is not Claude Code's own code, so the guard hook
and the sandbox stay the first barriers. Known limits, which no rule catches: a redirect after an
allowed read (``git status > f``), a method flag bundled with another short flag (``-iX POST``)
and a method flag in quotes (``'-X' POST``).
"""

import re
import shlex
from collections.abc import Iterable
from typing import Final

# Commands that write, so each must reach the permission prompt. The spec's commands come first;
# the probes after them try an interpreter, a shell and a second method flag on an allowed read.
WRITING_COMMANDS: Final[tuple[str, ...]] = (
    "git diff --output=f",
    "git log --output=f",
    "git show --output=f",
    "git push origin b",
    "git commit -m x",
    "git checkout main",
    "git reset --hard HEAD~1",
    "gh pr merge 1",
    "gh pr review 1 --approve",
    "gh pr comment 1 --body x",
    "gh pr create --title t --body b",
    "gh run rerun 1",
    "gh api -X POST repos/o/r/issues -f title=t",
    "gh api repos/o/r/pulls -f title=x",
    "gh api --method PATCH repos/o/r/pulls/1 -f title=t",
    "python3 scripts/../write.py",
    "sh -c 'echo > f'",
    "gh api -X GET -X POST repos/o/r/issues -f title=t",
    "gh api -X GET --method DELETE repos/o/r/git/refs/heads/b",
    "gh api -X GET repos/o/r/issues -X POST -f title=t",
    "gh api -X GET repos/o/r/issues --method=PATCH",
)

# A word of an MCP tool's name that marks the tool as one that writes.
WRITING_TOOL_WORDS: Final[tuple[str, ...]] = (
    "create",
    "update",
    "save",
    "delete",
    "merge",
    "add",
    "submit",
    "write",
    "request",
    "assign",
    "run",
    "rerun",
    "cancel",
    "push",
    "fork",
    "dismiss",
    "lock",
    "upload",
)

_BASH_RULE: Final = re.compile(r"Bash\((.*)\)", re.DOTALL)
_OPERATOR: Final = re.compile(r"&&|\|\||[;|\n]")
_ANY_ARGUMENTS: Final = " *"
_LEGACY_ANY_ARGUMENTS: Final = ":*"


def matches(rule: str, command: str) -> bool:
    """Whether the permission rule matches one subcommand of the Bash command."""
    if rule == "Bash":
        return True
    bash_rule = _BASH_RULE.fullmatch(rule)
    if bash_rule is None:
        return False
    pattern = _pattern_regex(bash_rule[1])
    return any(pattern.fullmatch(part) for part in _subcommands(command))


def effective_allows(allow: Iterable[str], deny: Iterable[str], command: str) -> bool:
    """Whether some allow rule matches the command and no deny rule does."""
    if any(matches(rule, command) for rule in deny):
        return False
    return any(matches(rule, command) for rule in allow)


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    """The rule's pattern as a regex: ``*`` is any text, every other character is itself."""
    if pattern.endswith(_LEGACY_ANY_ARGUMENTS):
        pattern = pattern.removesuffix(_LEGACY_ANY_ARGUMENTS) + _ANY_ARGUMENTS
    arguments = r"(?: .*)?" if pattern.endswith(_ANY_ARGUMENTS) else ""
    pieces = pattern.removesuffix(_ANY_ARGUMENTS).split("*")
    return re.compile(".*".join(re.escape(piece) for piece in pieces) + arguments, re.DOTALL)


def _subcommands(command: str) -> list[str]:
    """The command's parts between shell operators outside quotes, as written."""
    parts: list[str] = []
    start = 0
    for operator in _OPERATOR.finditer(command):
        part = command[start : operator.start()]
        if _quotes_closed(part):
            parts.append(part)
            start = operator.end()
    parts.append(command[start:])
    return [part.strip() for part in parts if part.strip()]


def _quotes_closed(text: str) -> bool:
    """Whether the text ends outside a quote and outside a backslash escape."""
    try:
        shlex.split(text)
    except ValueError:
        return False
    return True
