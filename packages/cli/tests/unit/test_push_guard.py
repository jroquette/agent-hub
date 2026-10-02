import pytest

from agent_hub.cli.push_guard import (
    CONFIG_FILE,
    ConfigSnapshot,
    changed_keys,
    file_digest,
    parse_config_list,
    risky_keys,
)

LISTED = (
    "core.bare\nfalse\0remote.origin.url\n/origin.git\0"
    "remote.origin.fetch\na\0remote.origin.fetch\nb\0"
)


def snapshot(output: str = LISTED, *, file: bytes = b"[core]\n") -> ConfigSnapshot:
    return ConfigSnapshot(
        entries=parse_config_list(output, scope="local"), files={"config": file_digest(file)}
    )


def test_reads_repeated_keys_when_config_listed() -> None:
    assert parse_config_list(LISTED, scope="local") == {
        ("local", "core.bare"): ("false",),
        ("local", "remote.origin.url"): ("/origin.git",),
        ("local", "remote.origin.fetch"): ("a", "b"),
    }
    assert parse_config_list("flag\0", scope="worktree") == {("worktree", "flag"): ("",)}


def test_names_keys_not_values_when_config_changed() -> None:
    after = snapshot(LISTED.replace("/origin.git", "/elsewhere.git") + "credential.helper\nstore\0")

    assert changed_keys(snapshot(), after) == ["credential.helper", "remote.origin.url"]


def test_names_file_when_only_bytes_changed() -> None:
    assert changed_keys(snapshot(), snapshot(file=b"[core]\n# note\n")) == [CONFIG_FILE]
    assert changed_keys(snapshot(), snapshot()) == []


@pytest.mark.parametrize(
    "key",
    [
        "credential.helper",
        "credential.https://github.com.username",
        "core.sshCommand",
        "core.askPass",
        "url.git@x:.insteadOf",
        "url.git@x:.pushInsteadOf",
        "include.path",
        "includeIf.gitdir:/x.path",
        "http.extraHeader",
    ],
)
def test_flags_key_when_push_would_use_it(key: str) -> None:
    assert risky_keys(snapshot(f"{key}\nx\0core.bare\nfalse\0")) == [key]


def test_flags_nothing_when_config_plain() -> None:
    assert risky_keys(snapshot()) == []
