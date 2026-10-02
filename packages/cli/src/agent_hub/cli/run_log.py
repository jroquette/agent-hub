"""The run's identity, outside core (E20): its id comes from a random source here."""

import uuid
from typing import Final

RUN_ID_LENGTH: Final = 8


def new_run_id() -> str:
    """A fresh run id: 8 hexadecimal characters, as the old runner wrote them."""
    return uuid.uuid4().hex[:RUN_ID_LENGTH]
