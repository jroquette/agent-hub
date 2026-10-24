"""Run control (ADR 0049; docs/design/workflow-engine-rules.md § Run control): a run paused
before a node by a breakpoint or by Step, which is not a gate.

``EnginePorts.control`` answers, for a node id as recorded, whether to pause before it, with the
block the node enters (an address the engine never reads) and why. The engine asks it when a
layer starts (a ``loop_group`` body's included), and only while ``debugging()``: a layer holding
a node to pause at runs one node at a time in declaration order and stops before that node, so
nothing of it starts. No gate opens and nothing is recorded; the report is ``paused`` with the
node as ``reason`` and its ``DebugPause`` in ``RunState.pause``. Mapping a block to the nodes it
enters by (a ``<step>__ask`` gate in front of a gated step among them), and knowing which blocks
are leaves for Step, are the port's: the engine knows only nodes.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

type DebugReason = Literal["breakpoint", "step"]


@dataclass(frozen=True)
class PauseReason:
    """Why to pause before a node: the block it enters and what asks, a ``breakpoint`` on that
    block or ``step`` mode."""

    block: str
    reason: DebugReason


@dataclass(frozen=True)
class DebugPause:
    """A run paused by run control: the node it stopped before, that node's block and why."""

    node: str
    block: str
    reason: DebugReason


class RunControl(Protocol):
    """A debugging run's breakpoints and step mode, read as the run goes."""

    def debugging(self) -> bool:
        """Whether a breakpoint or step mode is on; while neither is, nothing else is asked."""
        ...

    def pause_before(self, node: str) -> PauseReason | None:
        """Why to pause before ``node`` (an id as recorded), or ``None`` to run it. A query,
        asked once per visit (a body node's in each iteration), at times from several threads
        (concurrent groups' bodies)."""
        ...
