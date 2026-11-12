"""The hooks' reader and core give the same verdict on secret-shaped names and words.

The reader ports the shapes that fit an environment name (a safe segment of at most 40
characters) or a blocked word (at most 64, letters, digits and ``-_.``), plus two the prompt secret
hook needs: core's private-key header, as is, and a credential assignment of its own (a name
ending in ``SECRET``, ``TOKEN``, ``PASSWORD``, ``PASSWD``, ``API_KEY`` or ``PRIVATE_KEY``, ``=`` or
``:``, then 8 or more characters that are not a ``$``, ``<`` or ``*`` reference). The Fernet shape
is not ported. The assignment shapes differ on purpose (core's takes ``ENCRYPTION_KEY``, any case
and 6 characters, ``=`` only); neither fits a name or a word, which holds no space, ``=`` or ``:``,
so the cases below are the ones both judge alike. Each case is judged by core's ``secret_kind`` and
by the rendered reader's ``secret_shaped`` on ``hook_python``. Secret-shaped cases are assembled at
run time, so the repo holds none.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.secret_shapes import secret_kind

HOOKS = "plugin/hub-workflow/hooks"
CASES = (
    "AK" + "IA" + "A" * 16,
    "demo-" + "AK" + "IA" + "B" * 16,
    "AK" + "IA" + "A" * 15,
    "gh" + "p_" + "a" * 30,
    "gh" + "p_" + "a" * 29,
    "sk" + "_live_" + "a" * 16,
    "pk" + "_test_" + "a" * 16,
    "sk" + "_live_" + "a" * 15,
    "sk" + "-" + "a" * 20,
    "sk" + "-" + "a" * 19,
    "lin" + "_api_" + "a" * 20,
    "lin" + "_api_" + "a" * 19,
    "ey" + "J" + "a" * 15 + "." + "b" * 15,
    "ey" + "J" + "a" * 14 + "." + "b" * 15,
    "x" + "ey" + "J" + "a" * 15 + "." + "b" * 15,
    "a" * 43,
    "demo-live",
    "prod",
    "jane-cloud",
    "skeleton-key",
    "task-a" + "_live_" + "b" * 16,
    "-" * 5 + "BEGIN RSA " + "PRIVATE" + " KEY" + "-" * 5,
    "-" * 5 + "BEGIN " + "PRIVATE" + " KEY" + "-" * 4,
    "AUTH" + "_SECRET=" + "abcd1234efgh",
    "GITHUB" + "_TOKEN=$GITHUB" + "_TOKEN",
    "AUTH" + "_SECRET=",
)
READER_CODE = (
    "import json, sys\nfrom stdlib_reader import secret_shaped\n"
    "print(json.dumps([secret_shaped(text) for text in json.loads(sys.argv[1])]))\n"
)


def test_judges_same_cases_when_core_and_reader_read(
    *,
    rendered_hub: Callable[[HubConfig], Path],
    demo_config: HubConfig,
    each_python: str,
    run_python: Callable[..., Any],
    tmp_path: Path,
) -> None:
    hub = rendered_hub(demo_config)

    shaped = run_python(
        each_python, READER_CODE, path=hub / HOOKS, args=[json.dumps(list(CASES))], cwd=tmp_path
    )

    assert shaped == [secret_kind(text) is not None for text in CASES]
    assert shaped.count(True) == 11
