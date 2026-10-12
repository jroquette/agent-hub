from datetime import date
from decimal import Decimal

import pytest

from agent_hub.core.sessions.pricing import PRICES, PRICES_AS_OF, PerMillion, price_for


def test_dates_table_when_prices_copied() -> None:
    assert date(2026, 10, 11) == PRICES_AS_OF


def test_prices_every_model_with_decimals_when_table_read() -> None:
    assert PRICES
    for model, price in PRICES.items():
        assert model.startswith("claude-")
        assert all(isinstance(value, Decimal) for value in price.model_dump().values())
        assert price.cache_write == price.input * Decimal("1.25")


def test_finds_price_when_model_id_carries_date_suffix() -> None:
    assert price_for("claude-haiku-4-5-20251001") == PRICES["claude-haiku-4-5"]


@pytest.mark.parametrize("model", ["claude-unknown-9", "gpt-x", "", "claude-opus-5-5-extra"])
def test_finds_no_price_when_model_unknown(model: str) -> None:
    assert price_for(model) is None


def test_rejects_negative_price_when_built() -> None:
    with pytest.raises(ValueError, match="greater than or equal"):
        PerMillion(
            input=Decimal(-1), output=Decimal(1), cache_read=Decimal(0), cache_write=Decimal(0)
        )
