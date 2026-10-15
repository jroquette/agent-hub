"""Copying a workflow node with its ids and references rewritten (includes, loop group bodies).

A ``Rewrite`` says what each reference, ``depends_on`` id and ``context.resume`` target becomes;
``map_node`` applies it to every text of a node that may hold a reference, in one pass per text
(``substitution.rewrite_refs``: inserted text is never scanned again). A ``loop_group``'s body is
copied with its own ids left alone (``Local``): body ids are local to the group.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from typing import Final

from pydantic import JsonValue

from agent_hub.core.workflows.document import Loc
from agent_hub.core.workflows.nodes import (
    AgentNode,
    ApprovalNode,
    FromBinding,
    HaltNode,
    LoopGroupNode,
    LoopNode,
    Node,
    ResumeContext,
    ScriptNode,
    ShellNode,
    read_only,
)
from agent_hub.core.workflows.substitution import (
    LoopPrevRef,
    NodeRef,
    Ref,
    SubstitutionError,
    rewrite_refs,
)

type _Replace = Callable[[Ref, str], str]

# Between a namespace (an include, a loop group) and an id; authored ids never hold it.
SEPARATOR: Final = "__"


class RewriteError(Exception):
    """A problem at ``loc`` inside the node being copied."""

    def __init__(self, loc: Loc, message: str) -> None:
        super().__init__(message)
        self.loc, self.message = loc, message


class Rewrite(ABC):
    """How one node's ids and references are rewritten as it is copied."""

    def text(self, loc: Loc, text: str) -> str:
        return rewritten(loc, text, lambda ref, spelling: self.reference(loc, ref, spelling))

    @abstractmethod
    def reference(self, loc: Loc, ref: Ref, spelling: str) -> str: ...

    @abstractmethod
    def ids(self, targets: Sequence[str]) -> tuple[str, ...]: ...

    @abstractmethod
    def resume(self, target: str, loc: Loc) -> str: ...


class Local(Rewrite):
    """``outer`` for every reference, except those to ``local`` ids, which stay as written."""

    def __init__(self, outer: Rewrite, local: frozenset[str]) -> None:
        self.outer, self.local = outer, local

    def reference(self, loc: Loc, ref: Ref, spelling: str) -> str:
        if isinstance(ref, NodeRef | LoopPrevRef) and ref.node in self.local:
            return spelling
        return self.outer.reference(loc, ref, spelling)

    def ids(self, targets: Sequence[str]) -> tuple[str, ...]:
        return tuple(targets)

    def resume(self, target: str, loc: Loc) -> str:
        return target if target in self.local else self.outer.resume(target, loc)


def rewritten(loc: Loc, text: str, replace: _Replace) -> str:
    try:
        return rewrite_refs(text, replace)
    except SubstitutionError as error:
        raise RewriteError(loc, str(error)) from None


def map_node(node: Node, rewrite: Rewrite) -> Node:
    """``node`` with its ids and the references in its texts rewritten."""
    update: dict[str, object] = {"depends_on": rewrite.ids(node.depends_on)}
    if node.when is not None:
        update["when"] = rewrite.text(("when",), node.when)
    if isinstance(node, AgentNode | LoopNode):
        update |= _agent_update(node, rewrite)
    elif isinstance(node, ShellNode | ScriptNode):
        update |= _command_update(node, rewrite)
    elif isinstance(node, ApprovalNode):
        update["message"] = rewrite.text(("message",), node.message)
    elif isinstance(node, HaltNode):
        update["reason"] = rewrite.text(("reason",), node.reason)
    elif isinstance(node, LoopGroupNode):
        update |= _group_update(node, rewrite)
    return node.model_copy(update=update)


def _group_update(node: LoopGroupNode, rewrite: Rewrite) -> dict[str, object]:
    """The body copied with its own ids left alone; the ``until`` channels read body ids too."""
    local = Local(rewrite, frozenset(body.id for body in node.nodes))
    update: dict[str, object] = {
        "nodes": tuple(map_node(body, local) for body in node.nodes),
    }
    if node.until_when is not None:
        update["until_when"] = local.text(("until_when",), node.until_when)
    if node.until_bash is not None:
        update["until_bash"] = _argv(("until_bash",), node.until_bash, local)
    return update


def _agent_update(node: AgentNode | LoopNode, rewrite: Rewrite) -> dict[str, object]:
    update: dict[str, object] = {"with_": read_only(_bindings(node, rewrite))}
    if node.prompt is not None:
        update["prompt"] = rewrite.text(("prompt",), node.prompt)
    if isinstance(node.context, ResumeContext):
        target = rewrite.resume(node.context.resume, ("context", "resume"))
        update["context"] = ResumeContext(resume=target)
    if node.cwd is not None:
        update["cwd"] = rewrite.text(("cwd",), node.cwd)
    if isinstance(node, LoopNode) and node.until_bash is not None:
        update["until_bash"] = _argv(("until_bash",), node.until_bash, rewrite)
    return update


def _bindings(node: AgentNode | LoopNode, rewrite: Rewrite) -> dict[str, object]:
    bindings: dict[str, object] = {}
    for name, binding in node.with_.items():
        if isinstance(binding, FromBinding):
            source = rewrite.text(("with", name, "from"), binding.from_)
            bindings[name] = binding.model_copy(update={"from_": source})
        else:
            bindings[name] = _json_texts(("with", name), binding, rewrite)
    return bindings


def _command_update(node: ShellNode | ScriptNode, rewrite: Rewrite) -> dict[str, object]:
    update: dict[str, object] = {
        "env": read_only({name: rewrite.text(("env", name), v) for name, v in node.env.items()})
    }
    if isinstance(node, ShellNode):
        update["command"] = _argv(("command",), node.command, rewrite)
    else:
        update["args"] = _argv(("args",), node.args, rewrite)
    if node.cwd is not None:
        update["cwd"] = rewrite.text(("cwd",), node.cwd)
    if node.stdin is not None:
        update["stdin"] = rewrite.text(("stdin",), node.stdin)
    return update


def _argv(key: Loc, argv: Sequence[str], rewrite: Rewrite) -> tuple[str, ...]:
    return tuple(rewrite.text((*key, index), element) for index, element in enumerate(argv))


def _json_texts(loc: Loc, value: JsonValue, rewrite: Rewrite) -> JsonValue:
    if isinstance(value, str):
        return rewrite.text(loc, value)
    if isinstance(value, list):
        return [_json_texts((*loc, index), item, rewrite) for index, item in enumerate(value)]
    if isinstance(value, dict):
        return {key: _json_texts((*loc, key), item, rewrite) for key, item in value.items()}
    return value
