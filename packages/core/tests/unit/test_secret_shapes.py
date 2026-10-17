import pytest

from agent_hub.core.doctor import text_rules
from agent_hub.core.secret_shapes import SECRETS, secret_kind

# Assembled at run time, so the repo holds no secret-shaped text.
AWS_KEY = "AK" + "IA" + "A" * 16
JWT = "ey" + "J" + "a" * 15 + "." + "b" * 15


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        pytest.param(f"key {AWS_KEY} here", "AWS access key", id="aws"),
        pytest.param(f"Bearer {JWT}", "JWT", id="jwt"),
    ],
)
def test_names_kind_when_text_holds_secret_shape(text: str, kind: str) -> None:
    assert secret_kind(text) == kind


@pytest.mark.parametrize(
    "text",
    ["docker compose stack on this machine", "demo-live-ro", "https://api.example.com", ""],
)
def test_names_no_kind_when_text_plain(text: str) -> None:
    assert secret_kind(text) is None


def test_shares_shapes_when_doctor_reads_them() -> None:
    assert text_rules.SECRETS is SECRETS
