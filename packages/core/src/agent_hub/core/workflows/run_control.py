"""Run control (ADR 0049; docs/design/workflow-engine-rules.md § Run control): a run paused
before a node by a breakpoint or by Step, which is not a gate.

``EnginePorts.control`` answers, for a node id as recorded, whether to pause before it, with the
block the node enters (an address the engine never reads) and why. The engine asks it when a
layer starts (a ``loop_group`` body's included), and only while ``debugging()``: a layer holding
a node to pause at runs one node at a time in declaration order and stops before that node, so
nothing of it starts and nothing is recorded for it. The report is ``paused`` with the node as
``reason``, its ``DebugPause`` in ``RunState.pause`` and the stopped pass in
``RunState.paused_pass``, which the resume goes on with. The first visit, in the resumed
process, of the node that pause stopped before (or of a node the port names the same block for)
takes it up once: the engine runs it even when the port answers a stop, and a port that answers
``None`` for that visit has taken it up too. Mapping a block to the nodes it enters by (a
``<step>__ask`` gate in front of a gated step among them), and knowing which blocks are leaves
for Step, are the port's: the engine knows only nodes.
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
        """Whether to ask about the nodes of the layer starting: a breakpoint or step mode is on
        (a port may also stay on all through a resume from a debug pause, so it is asked at
        every visit); while it is off, nothing else is asked."""
        ...

    def pause_before(self, node: str) -> PauseReason | None:
        """Why to pause before ``node`` (an id as recorded), or ``None`` to run it. A query,
        asked once per visit (a body node's in each iteration), at times from several threads
        (concurrent groups' bodies)."""
        ...
