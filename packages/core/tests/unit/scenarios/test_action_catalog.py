"""The actions a hub has: their content hash and how a reference finds one (AC-350.10)."""

import re

import pytest

from agent_hub.core.scenarios.action_catalog import (
    ActionEntry,
    ActionRefError,
    action_content_hash,
    resolve_action,
)
from agent_hub.core.scenarios.action_document import parse_action

DOCUMENT = b"version: 1\nname: get-order\n"
SCRIPT = b"#!/bin/sh\necho '{}'\n"


def a_hash(*, document: bytes = DOCUMENT, script: bytes = SCRIPT) -> str:
    return action_content_hash(
        document_path="actions/orders/get-order.yaml",
        document=document,
        script_path="actions/orders/scripts/get_order.sh",
        script=script,
    )


def test_changes_action_content_hash_when_script_byte_changes() -> None:
    # AC-350.10: the hash covers the document and the script, byte for byte.
    pinned = a_hash()

    assert re.fullmatch(r"sha256:[0-9a-f]{64}", pinned)
    assert a_hash() == pinned
    assert a_hash(script=SCRIPT.replace(b"{}", b"{ }")) != pinned
    assert a_hash(document=DOCUMENT + b"\n") != pinned
    # The framing keeps a byte moved from the document to the script from giving the same hash.
    assert a_hash(document=DOCUMENT + b"#", script=SCRIPT[1:]) != pinned


def an_entry(pack: str, name: str) -> ActionEntry:
    document = parse_action(
        {
            "version": 1,
            "name": name,
            "description": "A demo action",
            "effect": "read",
            "runtime": "sh",
            "script": f"scripts/{name}.sh",
            "output_format": {"type": "object"},
        }
    )
    return ActionEntry(
        pack=pack,
        document=document,
        document_path=f"actions/{pack}/{name}.yaml",
        script_path=f"actions/{pack}/scripts/{name}.sh",
        content_hash=a_hash(),
        draft=False,
    )


ENTRIES = (
    an_entry("orders", "get-order"),
    an_entry("orders", "send-message"),
    an_entry("queues", "send-message"),
)


def test_resolves_action_when_ref_names_pack_or_same_pack() -> None:
    same_pack = resolve_action(ENTRIES, "send-message", pack="queues")
    named_pack = resolve_action(ENTRIES, "orders/send-message", pack="queues")
    only_one = resolve_action(ENTRIES, "get-order")

    assert (same_pack.pack, same_pack.document.name) == ("queues", "send-message")
    assert (named_pack.pack, named_pack.ref) == ("orders", "orders/send-message")
    assert only_one.document_path == "actions/orders/get-order.yaml"


@pytest.mark.parametrize(
    ("ref", "pack", "message"),
    [
        pytest.param(
            "get-order", "queues", "unknown action 'get-order' in pack queues", id="other_pack"
        ),
        pytest.param("billing/get-order", None, "unknown action 'billing/get-order'", id="no_pack"),
        pytest.param("missing", None, "unknown action 'missing'", id="no_name"),
        pytest.param(
            "send-message",
            None,
            "action 'send-message' is in more than one pack (orders, queues):"
            " name it as <pack>/send-message",
            id="ambiguous",
        ),
    ],
)
def test_refuses_ref_when_action_unknown_or_ambiguous(
    ref: str, pack: str | None, message: str
) -> None:
    with pytest.raises(ActionRefError) as caught:
        resolve_action(ENTRIES, ref, pack=pack)

    assert str(caught.value) == message
