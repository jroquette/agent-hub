"""The envelope the hook sensor posts: a Claude Code hook input plus where it came from (v1)."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, JsonValue, model_validator

from agent_hub.core.events.event import MAX_ID_CHARS, UtcTimestamp, longer_than_cap
from agent_hub.core.hub_config.model import exact_int

# A request body larger than this is refused before parsing.
MAX_BODY_BYTES = 1_048_576
# The sensor replaces a hook string longer than this with {"_omitted_bytes": n}.
MAX_STRING_BYTES = 65_536
# A body nested deeper than this is refused (bounded recursion while parsing).
MAX_JSON_DEPTH = 64


class HookDecision(BaseModel):
    """What the guard or the Stop gate decided, sent with the hook input that caused it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    by: Literal["guard", "stop_gate"]
    kind: Literal["deny", "ask", "block"]
    rule: str | None = None
    command: str | None = None
    exit_code: int | None = None


class HookEnvelope(BaseModel):
    """Version 1 of the sensor's envelope.

    ``project`` comes from the hub's ``hub.json``; ``repo`` from the hook's cwd (a repo checkout
    or one of its worktrees), else None; ``run``, ``step`` and ``attempt`` from the variables
    ``hub run`` sets for its session. ``hook`` is the Claude Code hook input as received, with
    oversized strings already omitted by the sensor.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    v: Annotated[Literal[1], BeforeValidator(exact_int)]
    project: str = Field(min_length=1)
    repo: str | None = None
    run: str | None = None
    step: str | None = None
    attempt: int | None = None
    sent_at: UtcTimestamp
    hook: dict[str, JsonValue]
    decision: HookDecision | None = None

    # ``project``, ``run`` and the hook's ``session_id`` are refused when longer than
    # ``MAX_ID_CHARS`` (the API answers 422). Kept out of the docstring, which is the published
    # schema's description.
    @model_validator(mode="after")
    def _ids_within_cap(self) -> Self:
        session = self.hook.get("session_id")
        for name, value in (("project", self.project), ("run", self.run), ("session_id", session)):
            if isinstance(value, str) and len(value) > MAX_ID_CHARS:
                raise ValueError(longer_than_cap(name))
        return self
