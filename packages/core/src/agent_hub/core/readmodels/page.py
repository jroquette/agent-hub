"""One page of a list endpoint: items, an opaque cursor to the next page, an estimated total."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field

# Cursors are opaque base64url text; longer ones are refused before decoding.
MAX_CURSOR_CHARS = 512


class Page[T](BaseModel):
    """``{items, next_cursor, total_estimate}``; ``next_cursor`` is None on the last page."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[T, ...]
    next_cursor: str | None = Field(default=None, max_length=MAX_CURSOR_CHARS)
    total_estimate: int = Field(ge=0)

    @classmethod
    def empty(cls) -> Self:
        """A page with nothing on it."""
        return cls(items=(), next_cursor=None, total_estimate=0)
