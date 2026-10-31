"""``make check-changed``: the checks, and the fast tests of what a change set reaches.

The planner turns changed paths into pytest targets through the ``agent_hub`` import graph and a
table of paths; the runner starts the checks and the tests in two lanes. Both land in later
commits: for now every function raises ``NotImplementedError``.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# A package ("core", "cli", and "scripts" for the repo's own scripts) mapped to the
# agent_hub packages its Python files name.
type Graph = Mapping[str, frozenset[str]]
# The arguments that follow "git", mapped to its stdout; None when git fails.
type Git = Callable[[Sequence[str]], str | None]
# One step's argv, mapped to its exit code and its output.
type Start = Callable[[Sequence[str]], tuple[int, str]]


@dataclass(frozen=True, kw_only=True, slots=True)
class Tree:
    """What exists for the planner to name: test folders and files, and the built-in packs."""

    paths: frozenset[str]
    packs: frozenset[str]


@dataclass(frozen=True, kw_only=True, slots=True)
class Plan:
    """What a change set needs: pytest targets and ignores, the extra steps, and why."""

    full: bool
    tests: tuple[str, ...]
    ignores: tuple[str, ...]
    openapi: bool
    web: bool
    reasons: tuple[str, ...]


def import_graph(root: Path) -> Graph:
    """The packages under ``root`` and the ``agent_hub`` packages each one names."""
    raise NotImplementedError


def dependents(graph: Graph, name: str) -> frozenset[str]:
    """``name`` and every package that reaches it in ``graph``."""
    raise NotImplementedError


def read_tree(root: Path) -> Tree:
    """The test folders, test files and built-in packs that exist under ``root``."""
    raise NotImplementedError


def plan_change(paths: Sequence[str] | None, graph: Graph, tree: Tree) -> Plan:
    """The plan for ``paths``; None, an unknown change set, gets the full plan."""
    raise NotImplementedError


def change_set(
    argv: Sequence[str], environ: Mapping[str, str], git: Git
) -> tuple[str, tuple[str, ...] | None]:
    """Where the changed paths come from, and the paths (None when they cannot be known)."""
    raise NotImplementedError


def lanes(plan: Plan) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    """The checks lane's steps and the tests lane's steps, each step an argv."""
    raise NotImplementedError


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str],
    start: Start,
    git: Git,
) -> int:
    """Print the plan, then run it unless ``--plan`` is given; returns the exit code."""
    raise NotImplementedError
