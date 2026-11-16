"""A node's reference scope: how a text written inside an include (or a loop group's body) reads
in the run (docs/design/workflow-schema.md § Nodes).

Expansion rewrites a node's own texts at load. A ``prompt_file`` is read only when the node runs,
so the plan keeps, for each node that needs one, the rewrites its texts went through: a
``RefScope`` of ``ScopeStep``s, innermost first. ``NodeCall.scope`` carries it, and the runner
renders a prompt file with ``scope.render``: the file reads its own workflow's inputs and nodes
exactly as an inline prompt does. Each step is one pass over the text (``rewrite_refs``); a step
reads only the text the step before it gave. Planning reads no file (core loads none), so a prompt
file's references are checked when it renders: one that does not resolve fails the node ``config``.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from agent_hub.core.workflows.substitution import (
    InputRef,
    LoopPrevRef,
    NodeRef,
    Ref,
    RefContext,
    SubstitutionError,
    render,
    rewrite_refs,
    spell,
)


@dataclass(frozen=True)
class ScopeStep:
    """One rewrite: node ids renamed one level up, inputs replaced by their texts.

    ``names`` maps an id as written to its id one level up; ``refused`` names ids whose reading
    is an error (an include with several sinks and no ``returns``). ``inputs`` replaces each
    ``$INPUTS.<name>`` (``None`` keeps them). In a ``hermetic`` step (an include's block) a node
    outside ``names`` is an error. ``keep`` names ids left as written: a loop group's body ids,
    local to the group, in a body node's scope.
    """

    names: Mapping[str, str] = field(default_factory=dict)
    inputs: Mapping[str, str] | None = None
    hermetic: bool = False
    refused: frozenset[str] = frozenset()
    keep: frozenset[str] = frozenset()

    def apply(self, text: str) -> str:
        return rewrite_refs(text, self._replace)

    def _replace(self, ref: Ref, spelling: str) -> str:
        if isinstance(ref, InputRef) and self.inputs is not None:
            if ref.name not in self.inputs:
                raise SubstitutionError("unknown_input", spelling, "its workflow has no such input")
            return self.inputs[ref.name]
        if isinstance(ref, NodeRef | LoopPrevRef):
            if ref.node in self.keep:
                return spelling
            if ref.node in self.refused:
                raise SubstitutionError("unknown_node", spelling, "it has several sinks")
            if ref.node in self.names:
                return spell(type(ref)(self.names[ref.node], ref.path))
            if self.hermetic:
                raise SubstitutionError("unknown_node", spelling, "not a node of its workflow")
        return spelling


@dataclass(frozen=True)
class RefScope:
    """The steps a node's texts went through, innermost first; empty for a top-level node."""

    steps: tuple[ScopeStep, ...] = ()

    def then(self, step: ScopeStep) -> RefScope:
        return RefScope((*self.steps, step))

    def rewrite(self, text: str) -> str:
        """``text`` as written in the node's own workflow, rewritten as the run reads it."""
        for step in self.steps:
            text = step.apply(text)
        return text

    def render(self, template: str, context: RefContext) -> str:
        """``template`` (a prompt file) rewritten, then rendered against ``context``."""
        return render(self.rewrite(template), context)
