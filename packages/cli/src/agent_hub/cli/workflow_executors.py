"""The workflow engine's ``NodeRunner``: agent, shell and script nodes as children (ADR 0032).

An ``agent`` or ``loop`` turn is one ``claude -p`` in the hub's main checkout, so the hub's
settings, hooks and plugin load; the hub's repos are attached with ``--add-dir``. With a ``cwd``
inside a repo (issue-to-pr's worktree) it runs there as ``hub run``'s session does: the hub and
the other repos attached, that repo's gates allowed. Its argv is
``hub run``'s (``implementing_argv``: permission mode ``dontAsk``, the tracker's tools denied),
with the node's tier from ``hub.json`` → ``models.tiers`` and its ``limits`` as ``--max-turns`` and
``--max-budget-usd``; ``--resume`` continues a session. Its output is the result's text, or, with
an ``output_format``, the result's last JSON line (the engine checks it). A ``prompt_file`` is
read from the pack's ``prompts/`` and rendered against the attempt's references.

A ``shell`` node runs its rendered argv, never through a shell; a ``script`` node runs
``sh <file>`` or ``uv run <file>`` from the pack's ``scripts/``, its ``args`` after the file. The
output is stdout, at most ``MAX_OUTPUT_BYTES``: the child writes to a temporary file and only
its last bytes are read back, so the memory is bounded, not the disk; past the cap the node fails
once the child ends (``run_child`` has no early stop). An agent's reply and a ``stdin`` are
capped at ``hub run``'s session output (1 MiB); a ``stdin`` is written to the child from a
temporary file (NUL and any length are safe there). The cwd is the node's
``cwd`` (relative to the hub), else the hub; its real path must stay in the hub or in one of its
repos.

Every child runs in a session of its own, so a timeout or Ctrl-C kills its whole group, and the
group is killed again once the child ends: nothing it left in the background outlives the
attempt, and a retry never runs beside an earlier copy. A session id from claude or a record is
passed to ``--resume`` only when it matches ``SESSION_ID``.

Environments: an agent gets ``session_env`` (its step is the node id as recorded, its attempt the
run-wide one), a ``hub step`` node runs this hub's own executable with ``child_env`` (hub step
narrows it per call), any other command ``untrusted_env`` plus its ``env``, which may not name a
token. No child gets ``LINEAR_API_KEY``. A failure's kind comes from where it happened: the exit
code (``kind_for_exit``), a timeout, claude's ``is_error`` field, or a child that cannot start
(``config``); never from message text.
"""

import contextlib
import json
import os
import re
import signal
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from agent_hub.cli.child_process import ChildResult, run_child
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.cli.run_children import (
    SESSION_DENIED_TOOLS,
    SESSION_HIDDEN,
    child_env,
    session_env,
    untrusted_env,
)
from agent_hub.cli.run_steps import GATE_TIMEOUT, SESSION_OUTPUT_LIMIT, SESSION_TIMEOUT
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.runner.session_prompt import (
    IMPLEMENTING_TOOLS,
    MAX_ARGUMENT_BYTES,
    gate_tools,
    implementing_argv,
)
from agent_hub.core.runner.verdict import SessionReply, last_json_line, parse_session_output
from agent_hub.core.workflows.failures import NodeFailedError, kind_for_exit
from agent_hub.core.workflows.nodes import (
    AgentNode,
    ExecutableNode,
    LoopNode,
    ScriptNode,
    ShellNode,
    duration_seconds,
)
from agent_hub.core.workflows.ports import NodeCall, NodeReply
from agent_hub.core.workflows.substitution import render
from agent_hub.generator.workflow_discovery import PackFolder, PackPathError, resolve_pack_file

MAX_OUTPUT_BYTES: Final = 512 * 1024
# An agent's reply and a stdin (which carries one to hub step verdict): hub run's session cap.
MAX_REPLY_BYTES: Final = SESSION_OUTPUT_LIMIT
AGENT_EFFORT: Final = "medium"
# Kept from a failed child's stderr for the run's record (never for events).
MAX_DETAIL_CHARS: Final = 1_500
# A session id ``--resume`` may get: no leading dash, no space or shell character.
SESSION_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
SCRIPT_RUNNERS: Final[Mapping[str, tuple[str, ...]]] = {"sh": ("sh",), "python": ("uv", "run")}

type ChildRunner = Callable[..., ChildResult]


@dataclass(frozen=True, kw_only=True)
class WorkflowExecutors:
    """Runs one workflow run's node attempts.

    ``hub`` is the hub's main checkout, ``pack_root`` the run's pack (its snapshot), ``hub_program``
    the argv that starts this hub (an absolute path first), ``child`` ``run_child`` or a fake.
    """

    hub: Path
    config: HubConfig
    run_id: str
    pack_root: Path
    environ: Mapping[str, str]
    hub_program: tuple[str, ...]
    child: ChildRunner = field(default=run_child)
    # Each agent node's last ``claude`` result (cost, turns, verdict), for issue-to-pr's records.
    replies: dict[str, SessionReply] = field(default_factory=dict)

    def run(self, call: NodeCall) -> NodeReply:
        node = call.node
        if isinstance(node, AgentNode | LoopNode):
            return self._agent(call, node)
        argv, env = self._command(call)
        stdin = None
        if call.stdin is not None:
            stdin = call.stdin.encode(errors="surrogatepass")
            if len(stdin) > MAX_REPLY_BYTES:
                raise NodeFailedError("config", f"stdin is larger than {MAX_REPLY_BYTES} bytes")
        result = self._spawn(
            argv, env=env, cwd=self._cwd(call.cwd), timeout=_timeout(node), stdin=stdin
        )
        if (kind := kind_for_exit(result.returncode)) is not None:
            raise NodeFailedError(kind, _detail(argv, result))
        return NodeReply(_bounded(result.stdout))

    def until_exit(self, argv: Sequence[str], call: NodeCall) -> int:
        result = self._spawn(
            argv, env=untrusted_env(self.environ), cwd=self._cwd(None), timeout=_timeout(call.node)
        )
        return result.returncode

    def _agent(self, call: NodeCall, node: AgentNode | LoopNode) -> NodeReply:
        prompt = call.prompt if call.prompt is not None else self._prompt_file(call, node)
        if len(prompt.encode(errors="surrogatepass")) > MAX_ARGUMENT_BYTES:
            raise NodeFailedError("config", f"the prompt is larger than {MAX_ARGUMENT_BYTES} bytes")
        cwd = self._cwd(call.cwd)
        repos = self.config.repos
        # In a repo (its worktree), as hub run's session: the hub and the other repos attached,
        # that repo's gates allowed. In the hub: every repo attached, every gate allowed.
        home = next((r for r in repos if cwd.is_relative_to(self._root(r.dir))), None)
        folders = (str(self.hub),) if home is not None else ()
        others = (r for r in repos if r is not home)
        gated = (home,) if home is not None else repos
        argv = implementing_argv(
            prompt=prompt,
            max_turns=node.limits.max_turns,
            budget=node.limits.max_cost_usd,
            model=self.config.models.model_for(node.model),
            effort=AGENT_EFFORT,
            add_dirs=(*folders, *(str(self.hub.parent / repo.dir) for repo in others)),
            tools=(
                *IMPLEMENTING_TOOLS,
                *gate_tools(command for repo in gated for command in (repo.check_fast, repo.check)),
            ),
            denied_tools=SESSION_DENIED_TOOLS,
        )
        if call.resume_session is not None:
            if not SESSION_ID.fullmatch(call.resume_session):
                raise NodeFailedError("config", "the session to resume has an unsafe id")
            argv += ["--resume", call.resume_session]
        inputs = call.context.inputs
        env = session_env(
            self.environ,
            repo=_text(inputs.get("repo")),
            issue_id=_text(inputs.get("issue")),
            run_id=self.run_id,
            attempt=call.attempt,
            step=node.id,
        )
        result = self._spawn(
            argv,
            env=env,
            cwd=cwd,
            timeout=_timeout(node, default=SESSION_TIMEOUT),
            output_limit=SESSION_OUTPUT_LIMIT,
        )
        reply = parse_session_output(result.stdout.decode(errors="replace"))
        self.replies[node.id] = reply
        if result.returncode != 0 or reply.is_error:
            detail = f"claude ended with exit {result.returncode} ({reply.subtype or 'no result'})"
            raise NodeFailedError("exec_failed", detail)
        text = reply.result
        if node.output_format is not None and (value := last_json_line(text)) is not None:
            text = json.dumps(value)
        session = reply.session_id
        safe = session if session is not None and SESSION_ID.fullmatch(session) else None
        reply_bytes = text.encode(errors="surrogatepass")
        return NodeReply(_bounded(reply_bytes, limit=MAX_REPLY_BYTES), safe)

    def _prompt_file(self, call: NodeCall, node: AgentNode | LoopNode) -> str:
        path = self._pack_file("prompts", node.prompt_file or "")
        try:
            template = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            detail = f"cannot read prompts/{node.prompt_file}: {type(error).__name__}"
            raise NodeFailedError("config", detail) from None
        return render(template, call.context)

    def _command(self, call: NodeCall) -> tuple[list[str], dict[str, str]]:
        node = call.node
        if isinstance(node, ScriptNode):
            script = self._pack_file("scripts", node.script)
            argv = [*SCRIPT_RUNNERS[node.runtime], str(script), *call.argv]
        else:
            argv = list(call.argv)
        if isinstance(node, ShellNode) and node.is_hub_step:
            return [*self.hub_program, *argv[1:]], child_env(self.environ)
        if tokens := sorted(set(call.env) & set(SESSION_HIDDEN)):
            raise NodeFailedError("config", f"env may not set {', '.join(tokens)}")
        return argv, {**untrusted_env(self.environ), **call.env}

    def _pack_file(self, folder: PackFolder, relative: str) -> Path:
        try:
            return resolve_pack_file(self.pack_root, folder, relative)
        except PackPathError as error:
            raise NodeFailedError("config", str(error)) from None

    def _cwd(self, given: str | None) -> Path:
        """The real path of ``given`` (relative to the hub); ``config`` unless it stays in the
        hub or one of its repos."""
        hub = self.hub.resolve()
        path = hub if given is None else (hub / given).resolve()
        roots = (hub, *(self._root(repo.dir) for repo in self.config.repos))
        if not any(path.is_relative_to(root) for root in roots):
            raise NodeFailedError("config", "the cwd leaves the hub and its repos")
        return path

    def _root(self, repo: str) -> Path:
        return (self.hub.resolve().parent / repo).resolve()

    def _spawn(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        cwd: Path,
        timeout: float,
        output_limit: int = MAX_OUTPUT_BYTES + 1,
        stdin: bytes | None = None,
    ) -> ChildResult:
        groups: list[int] = []
        try:
            return self.child(
                argv,
                cwd=cwd,
                env=env,
                timeout=timeout,
                own_session=True,
                output_limit=output_limit,
                on_start=groups.append,
                **({} if stdin is None else {"stdin": stdin}),
            )
        except ChildTimedOutError as error:
            raise NodeFailedError("timeout", str(error)) from None
        except OSError as error:
            detail = f"{argv[0]} could not start: {error.strerror or type(error).__name__}"
            raise NodeFailedError("config", detail) from None
        except ValueError as error:
            # An argument or variable the OS cannot take (a NUL byte, for one).
            raise NodeFailedError("config", f"cannot start {argv[0]}: {error}") from None
        finally:
            for group in groups:
                # The leader has ended; what it left running ends with it.
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(group, signal.SIGKILL)


def _timeout(node: ExecutableNode, *, default: float = GATE_TIMEOUT) -> float:
    return float(duration_seconds(node.timeout)) if node.timeout is not None else default


def _bounded(output: bytes, *, limit: int = MAX_OUTPUT_BYTES) -> str:
    if len(output) > limit:
        raise NodeFailedError("output_contract", f"the output is larger than {limit} bytes")
    return output.decode(errors="replace")


def _detail(argv: Sequence[str], result: ChildResult) -> str:
    tail = result.stderr.decode(errors="replace")[-MAX_DETAIL_CHARS:]
    return f"{argv[0]} exited {result.returncode}: {tail}".rstrip()


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""
