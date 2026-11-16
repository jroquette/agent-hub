"""The dated price table that turns transcript token usage into an estimated cost (D15).

USD per million tokens per model, copied from Anthropic's published Claude API prices on
``PRICES_AS_OF``: input, output, cache write (the 5-minute duration, 1.25 x input; a transcript
does not say which duration a write used) and cache read. Claude Haiku 5.5's prices are those
of prompts up to 100K tokens. Costs computed from it are always labelled "Estimated from
transcript". A model missing here has no price: its cost is unknown, never guessed.
"""

import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

PRICES_AS_OF = date(2026, 10, 11)

type UsdPerMillion = Annotated[Decimal, Field(ge=0)]


class PerMillion(BaseModel):
    """What a million tokens of each kind cost, in USD."""

    model_config = ConfigDict(frozen=True)

    input: UsdPerMillion
    output: UsdPerMillion
    cache_read: UsdPerMillion
    cache_write: UsdPerMillion


def _per_million(input_usd: str, output_usd: str, cache_read_usd: str) -> PerMillion:
    input_price = Decimal(input_usd)
    return PerMillion(
        input=input_price,
        output=Decimal(output_usd),
        cache_read=Decimal(cache_read_usd),
        cache_write=input_price * Decimal("1.25"),
    )


PRICES: Mapping[str, PerMillion] = {
    "claude-fable-5-1": _per_million("10", "50", "0.25"),
    "claude-mythos-5-1": _per_million("10", "50", "0.25"),
    "claude-fable-5": _per_million("10", "50", "1.00"),
    "claude-mythos-5": _per_million("10", "50", "1.00"),
    "claude-opus-5-5": _per_million("4", "20", "0.20"),
    "claude-opus-5": _per_million("5", "25", "0.50"),
    "claude-opus-4-8": _per_million("5", "25", "0.50"),
    "claude-opus-4-7": _per_million("5", "25", "0.50"),
    "claude-opus-4-6": _per_million("5", "25", "0.50"),
    "claude-sonnet-5-5": _per_million("2", "10", "0.20"),
    "claude-sonnet-5": _per_million("2", "10", "0.20"),
    "claude-sonnet-4-6": _per_million("3", "15", "0.30"),
    "claude-haiku-5-5": _per_million("0.10", "0.50", "0.01"),
    "claude-haiku-4-5": _per_million("1", "5", "0.10"),
}

# A snapshot id is the model id plus "-YYYYMMDD" (claude-haiku-4-5-20251001).
_SNAPSHOT_SUFFIX = re.compile(r"-\d{8}$")


def price_for(model: str, prices: Mapping[str, PerMillion] = PRICES) -> PerMillion | None:
    """The price of ``model`` (a dated snapshot id resolves to its model), or None."""
    return prices.get(model) or prices.get(_SNAPSHOT_SUFFIX.sub("", model))
