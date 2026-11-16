"""``release_lookup``: the reason a failed ``git ls-remote`` of the release tag shows (ADR 0054)."""

from collections.abc import Sequence
from typing import Any

import pytest

from agent_hub.cli import release_lookup
from agent_hub.cli.child_process import ChildResult
from agent_hub.core.hub_files.release_commit import LookupFailure

REPOSITORY = "git+https://github.com/jroquette/agent-hub"
# Stands for a credential a rewrite put in the URL; not a real one.
PLANTED = "planted-value"


def failing_git(stderr: bytes) -> Any:
    """A ``run_child`` whose git exits 128 with ``stderr``."""

    def run(argv: Sequence[str], **_options: Any) -> ChildResult:
        assert list(argv[:2]) == ["git", "ls-remote"]
        return ChildResult(returncode=128, stdout=b"", stderr=stderr)

    return run


@pytest.mark.parametrize(
    "userinfo",
    [f"x-access-token:{PLANTED}@", f"{PLANTED}@"],
    ids=["user-and-password", "user-only"],
)
def test_hides_url_credentials_when_git_names_rewritten_url(
    monkeypatch: pytest.MonkeyPatch, userinfo: str
) -> None:
    # A rewrite (url.<base>.insteadOf) put a credential in the URL git names in its message.
    stderr = (
        f"fatal: unable to access 'https://{userinfo}github.com/jroquette/agent-hub/':"
        " Could not resolve host: github.com\n"
    ).encode()
    monkeypatch.setattr(release_lookup, "run_child", failing_git(stderr))

    found = release_lookup.tag_commit(REPOSITORY, "1.2.3", cwd="/", timeout=1.0)

    assert found == LookupFailure(
        reason=(
            "fatal: unable to access 'https://github.com/jroquette/agent-hub/':"
            " Could not resolve host: github.com"
        )
    )


def test_keeps_git_message_when_url_has_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    stderr = b"fatal: repository 'https://github.com/jroquette/agent-hub/' not found\n"
    monkeypatch.setattr(release_lookup, "run_child", failing_git(stderr))

    found = release_lookup.tag_commit(REPOSITORY, "1.2.3", cwd="/", timeout=1.0)

    assert found == LookupFailure(
        reason="fatal: repository 'https://github.com/jroquette/agent-hub/' not found"
    )
