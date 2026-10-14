"""The ``loop`` node: one agent turn repeated until a channel says done (workflow-schema.md).

Channels are read in order, each only when the one before did not end the loop: ``until`` (the
reply's last non-blank line, trimmed, equals it), ``until_field`` (that output property is
exactly ``true``), ``until_bash`` (exit 0, run through the ``NodeRunner``). A turn past
``max_iterations`` that met none fails ``max_iterations``. Without ``fresh_context`` each turn
resumes the previous turn's session. The loop's output is its last turn's.
"""

from collections.abc import Callable
from dataclasses import dataclass

from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.nodes import LoopNode


@dataclass(frozen=True)
class Turn:
    """A turn that ended ``ok``: its output, text and session."""

    output: JsonValue
    text: str
    session: str | None


def last_line(text: str) -> str:
    """The last non-blank line of ``text``, trimmed; empty when there is none."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def until_met(node: LoopNode, turn: Turn, until_exit: Callable[[], int]) -> bool:
    """Whether ``turn`` ends the loop; ``until_exit`` runs ``until_bash`` only when reached."""
    if node.until is not None and last_line(turn.text) == node.until.strip():
        return True
    if node.until_field is not None:
        output = turn.output
        if isinstance(output, dict) and output.get(node.until_field) is True:
            return True
    return node.until_bash is not None and until_exit() == 0


class MaxIterationsError(NodeFailedError):
    """The last allowed turn did not end the loop; ``output`` is that turn's, for the record."""

    def __init__(self, detail: str, output: JsonValue) -> None:
        super().__init__("max_iterations", detail)
        self.output = output


def check_turn(node: LoopNode, iteration: int, turn: Turn, *, done: bool) -> None:
    """Raise ``MaxIterationsError`` when the last allowed turn did not end the loop."""
    if not done and iteration >= node.max_iterations:
        channels = [
            name
            for name, value in (
                ("until", node.until),
                ("until_field", node.until_field),
                ("until_bash", node.until_bash),
            )
            if value is not None
        ]
        detail = f"{node.max_iterations} iterations met none of {', '.join(channels)}"
        raise MaxIterationsError(detail, turn.output)


def next_session(node: LoopNode, turn: Turn) -> str | None:
    """The session the next turn resumes: none under ``fresh_context``."""
    return None if node.fresh_context else turn.session
