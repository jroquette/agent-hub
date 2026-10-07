import hashlib
import os
import random
import subprocess
import sys

import pytest

from agent_hub.core.workspace.worktree_slot import (
    PORT_STEP,
    SLOT_COUNT,
    port_offset,
    worktree_slot,
)

_NAME_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789.-_"


@pytest.mark.parametrize(("name", "slot"), [("dem-7-x", 34), ("agh-59-worktree-environment", 30)])
def test_gives_pinned_slot_when_name_known(name: str, slot: int) -> None:
    independent = int(hashlib.sha256(name.encode()).hexdigest(), 16) % 50

    assert worktree_slot(name) == slot
    assert slot == independent


def test_states_slot_count_and_step_when_module_read() -> None:
    assert SLOT_COUNT == 50
    assert PORT_STEP == 100


def test_shifts_ports_by_hundreds_when_offset_computed() -> None:
    assert port_offset(0) == 0
    assert port_offset(34) == 3400
    assert port_offset(49) == 4900


def test_stays_in_range_when_names_generated() -> None:
    rng = random.Random(59)  # noqa: S311 - seeded test names, not cryptography
    names = ["".join(rng.choices(_NAME_CHARS, k=rng.randint(1, 80))) for _ in range(1000)]
    names += ["", "dem-7-ção"]

    slots = [worktree_slot(name) for name in names]

    assert all(slot in range(50) for slot in slots)
    assert len(set(slots)) > 40


@pytest.mark.parametrize("seed", ["1", "2"])
def test_gives_same_slot_when_hash_seed_differs(seed: str) -> None:
    code = (
        "from agent_hub.core.workspace.worktree_slot import worktree_slot;"
        " print(worktree_slot('dem-7-x'))"
    )

    result = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONHASHSEED": seed},
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout == "34\n"
