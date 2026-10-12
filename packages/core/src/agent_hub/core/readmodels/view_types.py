"""Value types every read model shares: money, API timestamps and the frozen view base.

Money is a ``Decimal`` written as a string with exactly 4 decimal places, so totals add up
exactly in the UI; API timestamps are UTC with milliseconds and a ``Z``.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, PlainSerializer, WithJsonSchema
from pydantic.config import JsonDict

from agent_hub.core.events.event import EventSource, UtcTimestamp

MONEY_PATTERN = r"^-?[0-9]+\.[0-9]{4}$"

# A deprecated field stays in the API (v1 only grows) and is marked so in the OpenAPI document,
# as ``Field(json_schema_extra=DEPRECATED_FIELD)``: only the schema says so, reading the
# attribute raises no warning.
DEPRECATED_FIELD: Final[JsonDict] = {"deprecated": True}


def money_text(value: Decimal) -> str:
    """``value`` with exactly 4 decimal places, rounded half-even (``1.2734``)."""
    return f"{value.quantize(Decimal('0.0001')):f}"


def timestamp_text(value: datetime) -> str:
    """``value`` as ISO 8601 UTC with milliseconds and a ``Z`` (``2026-10-09T14:05:41.882Z``)."""
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


type Money = Annotated[
    Decimal,
    PlainSerializer(money_text, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": MONEY_PATTERN}),
]

type ApiTimestamp = Annotated[
    UtcTimestamp,
    PlainSerializer(timestamp_text, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "format": "date-time"}),
]


class ViewModel(BaseModel):
    """Base of every read model: frozen and strict about unknown keys."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class DerivedView(ViewModel):
    """A view computed from events: ``derived`` is shown as a label in the UI.

    ``sources_missing`` names the sources not connected in this version (otel, github,
    linear) whose fields are therefore ``null``.
    """

    derived: bool = True
    sources_missing: tuple[EventSource, ...] = ()
