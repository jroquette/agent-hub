"""An action's process (docs/design/scenarios.md § Actions and the script contract, ADR 0041).

The script runs as ``sh <script>`` or ``uv run <script>`` from a temporary folder that holds
exactly the files the action's content hash pinned (its document, script and pack helpers, as
read: E-4), so an edit after the read, a dot file or a ``__pycache__`` entry never reaches it; its
working folder is the pinned pack's. It reads one JSON object on stdin, ``{"mode", "inputs",
"endpoint"}``, and prints one JSON value.

- ``run_action``: the output must match the action's ``output_format``, else ``output_contract``;
  the process gets ``untrusted_env`` without the hub's credential names (``hidden``), plus the
  ``credentials`` injected for it alone. Every injected value of at least
  ``MIN_REDACTED_CHARS`` is replaced by ``<credential NAME>`` in its stdout and in a failure's
  detail before anything reads them (a shorter one cannot be told from ordinary output).
- ``plan_action``: ``mode: "plan"``, at most ``PLAN_TIMEOUT`` seconds, no credential (it takes
  none); its row is the ``summary`` (one string of at most ``MAX_SUMMARY_CHARS``) or ``plan
  failed: <kind>``.

The child runs in a session of its own: a timeout kills its whole group, and the group is killed
again once it ends, so nothing it left in the background outlives the call. Stdout is capped at
``MAX_OUTPUT_BYTES`` (a script node's cap); a failure's detail keeps the tail of stderr.
"""

import contextlib
import json
import os
import signal
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, Literal

from agent_hub.cli.child_process import ChildResult, run_child
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.cli.run_children import untrusted_env
from agent_hub.cli.workflow_executors import MAX_DETAIL_CHARS, MAX_OUTPUT_BYTES, SCRIPT_RUNNERS
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes
from agent_hub.core.scenarios.action_catalog import ActionEntry
from agent_hub.core.scenarios.credentials import NO_CREDENTIALS, CredentialNames
from agent_hub.core.workflows.failures import NodeFailedError, kind_for_exit
from agent_hub.core.workflows.nodes import duration_seconds
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs

PLAN_TIMEOUT: Final = 60.0
MAX_SUMMARY_CHARS: Final = 200
PLAN_FAILED: Final = "plan failed: {kind}"
MIN_REDACTED_CHARS: Final = 4

type Mode = Literal["plan", "run"]


@dataclass(frozen=True, kw_only=True, slots=True)
class ActionCall:
    """One call of an action: its entry, its pinned files (hub-relative path and bytes, from
    discovery or a scenario run's snapshot), its typed inputs and each ``service`` input's
    endpoint (``{"url", "resource"}``)."""

    entry: ActionEntry
    files: tuple[tuple[str, bytes], ...]
    inputs: Mapping[str, JsonValue]
    endpoint: Mapping[str, Mapping[str, JsonValue]]


def run_action(
    call: ActionCall,
    *,
    environ: Mapping[str, str],
    hidden: CredentialNames = NO_CREDENTIALS,
    credentials: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> JsonValue:
    """The action's output in ``run`` mode, injected values redacted; raises
    ``NodeFailedError`` (``output_contract`` when it is not one JSON value matching
    ``output_format``), its detail redacted too."""
    document = call.entry.document
    injected = dict(credentials or {})
    seconds = timeout if timeout is not None else float(duration_seconds(document.timeout))
    env = {**untrusted_env(environ, hidden=hidden), **injected}
    try:
        result = _spawn(call, "run", env=env, timeout=seconds, credentials=injected)
    except NodeFailedError as error:
        raise NodeFailedError(error.kind, redacted(str(error), injected)) from None
    stdout = result.stdout
    for secret, name in _by_length(injected):
        stdout = stdout.replace(
            secret.encode(errors="surrogatepass"), f"<credential {name}>".encode()
        )
    value = _one_value(stdout)
    JsonSchemaOutputs().check(document.output_format, value)
    return value


def plan_action(
    call: ActionCall, *, environ: Mapping[str, str], hidden: CredentialNames = NO_CREDENTIALS
) -> str:
    """The plan row of the call: the script's ``summary`` in ``plan`` mode, or ``plan failed:
    <kind>``. It gets no credential: the process has ``untrusted_env`` without ``hidden``."""
    seconds = min(PLAN_TIMEOUT, float(duration_seconds(call.entry.document.timeout)))
    try:
        result = _spawn(call, "plan", env=untrusted_env(environ, hidden=hidden), timeout=seconds)
        value = _one_value(result.stdout)
    except NodeFailedError as error:
        return PLAN_FAILED.format(kind=error.kind)
    summary = value.get("summary") if isinstance(value, dict) and len(value) == 1 else None
    if not isinstance(summary, str) or len(summary) > MAX_SUMMARY_CHARS:
        return PLAN_FAILED.format(kind="output_contract")
    return summary


def redacted(text: str, credentials: Mapping[str, str]) -> str:
    """``text`` with each value of ``credentials`` of at least ``MIN_REDACTED_CHARS`` replaced
    by ``<credential NAME>``, the longest first (so a value holding another goes whole)."""
    for value, name in _by_length(credentials):
        text = text.replace(value, f"<credential {name}>")
    return text


def _by_length(credentials: Mapping[str, str]) -> list[tuple[str, str]]:
    """``(value, name)`` of each value long enough to redact, the longest first."""
    pairs = [(value, name) for name, value in credentials.items()]
    eligible = [pair for pair in pairs if len(pair[0]) >= MIN_REDACTED_CHARS]
    return sorted(eligible, key=lambda pair: -len(pair[0]))


def _spawn(
    call: ActionCall,
    mode: Mode,
    *,
    env: Mapping[str, str],
    timeout: float,
    credentials: Mapping[str, str] | None = None,
) -> ChildResult:
    stdin = {"mode": mode, "inputs": dict(call.inputs), "endpoint": dict(call.endpoint)}
    with tempfile.TemporaryDirectory(prefix="hub-action-") as folder:
        root = Path(folder)
        _write_pinned(root, call.files)
        entry = call.entry
        script = root / entry.script_path
        argv = [*SCRIPT_RUNNERS[entry.document.runtime], str(script)]
        result = _run(
            argv,
            cwd=(root / entry.document_path).parent,
            env=env,
            timeout=timeout,
            stdin=json.dumps(stdin).encode(),
        )
    if (kind := kind_for_exit(result.returncode)) is not None:
        # Redacted whole, then cut: a cut first would leave a value's end in the tail.
        stderr = redacted(result.stderr.decode(errors="replace"), credentials or {})
        tail = stderr[-MAX_DETAIL_CHARS:]
        raise NodeFailedError(kind, f"{argv[0]} exited {result.returncode}: {tail}")
    if len(result.stdout) > MAX_OUTPUT_BYTES:
        raise NodeFailedError(
            "output_contract", f"the output is larger than {MAX_OUTPUT_BYTES} bytes"
        )
    return result


def _write_pinned(root: Path, files: Sequence[tuple[str, bytes]]) -> None:
    """Each pinned file at its hub-relative path under ``root``, owner-only."""
    for relative, data in files:
        parts = PurePosixPath(relative).parts
        if not parts or PurePosixPath(relative).is_absolute() or ".." in parts:
            raise NodeFailedError("config", f"a pinned file has an unsafe path: {relative!r}")
        path = root.joinpath(*parts)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o700)


def _run(
    argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout: float, stdin: bytes
) -> ChildResult:
    groups: list[int] = []
    try:
        return run_child(
            argv,
            cwd=cwd,
            env=env,
            timeout=timeout,
            own_session=True,
            output_limit=MAX_OUTPUT_BYTES + 1,
            on_start=groups.append,
            stdin=stdin,
        )
    except ChildTimedOutError as error:
        raise NodeFailedError("timeout", str(error)) from None
    except OSError as error:
        detail = f"{argv[0]} could not start: {error.strerror or type(error).__name__}"
        raise NodeFailedError("config", detail) from None
    except ValueError as error:
        raise NodeFailedError("config", f"cannot start {argv[0]}: {error}") from None
    finally:
        for group in groups:
            # The leader has ended; what it left running ends with it.
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(group, signal.SIGKILL)


def _one_value(stdout: bytes) -> JsonValue:
    try:
        return load_json_bytes(stdout, strict=True)
    except InvalidJsonError:
        raise NodeFailedError("output_contract", "the output is not one JSON value") from None
