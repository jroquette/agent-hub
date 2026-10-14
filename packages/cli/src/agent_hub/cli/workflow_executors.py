"""The workflow engine's ``NodeRunner``: agent, shell and script nodes as children (ADR 0032).

An ``agent`` or ``loop`` turn is one ``claude -p`` in the hub's main checkout, so the hub's
settings, hooks and plugin load; the hub's repos are attached with ``--add-dir``. Its argv is
``hub run``'s (``implementing_argv``: permission mode ``dontAsk``, the tracker's tools denied),
with the node's tier from ``hub.json`` → ``models.tiers`` and its ``limits`` as ``--max-turns`` and
``--max-budget-usd``; ``--resume`` continues a session. Its output is the result's text, or, with
an ``output_format``, the result's last JSON line (the engine checks it). A ``prompt_file`` is
read from the pack's ``prompts/`` and rendered against the attempt's references.

A ``shell`` node runs its rendered argv, never through a shell; a ``script`` node runs
``sh <file>`` or ``uv run <file>`` from the pack's ``scripts/``, its ``args`` after the file. The
output is stdout, at most ``MAX_OUTPUT_BYTES``. The cwd is the node's ``cwd`` (relative to the
hub), else the hub.

Environments: an agent gets ``session_env`` (its step is the node id as recorded, its attempt the
run-wide one), a ``hub step`` node runs this hub's own executable with ``child_env`` (hub step
narrows it per call), any other command ``untrusted_env`` plus its ``env``, which may not name a
token. No child gets ``LINEAR_API_KEY``. A failure's kind comes from where it happened: the exit
code (``kind_for_exit``), a timeout, claude's ``is_error`` field, or a child that cannot start
(``config``); never from message text.
"""

import json
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
from agent_hub.core.runner.verdict import last_json_line, parse_session_output
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
AGENT_EFFORT: Final = "medium"
# Kept from a failed child's stderr for the run's record (never for events).
MAX_DETAIL_CHARS: Final = 1_500
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

    def run(self, call: NodeCall) -> NodeReply:
        node = call.node
        if isinstance(node, AgentNode | LoopNode):
            return self._agent(call, node)
        argv, env = self._command(call)
        result = self._spawn(argv, env=env, cwd=self._cwd(call.cwd), timeout=_timeout(node))
        if (kind := kind_for_exit(result.returncode)) is not None:
            raise NodeFailedError(kind, _detail(argv, result))
        return NodeReply(_bounded(result.stdout))

    def until_exit(self, argv: Sequence[str], call: NodeCall) -> int:
        result = self._spawn(
            argv, env=untrusted_env(self.environ), cwd=self.hub, timeout=_timeout(call.node)
        )
        return result.returncode

    def _agent(self, call: NodeCall, node: AgentNode | LoopNode) -> NodeReply:
        prompt = call.prompt if call.prompt is not None else self._prompt_file(call, node)
        if len(prompt.encode(errors="surrogatepass")) > MAX_ARGUMENT_BYTES:
            raise NodeFailedError("config", f"the prompt is larger than {MAX_ARGUMENT_BYTES} bytes")
        repos = self.config.repos
        argv = implementing_argv(
            prompt=prompt,
            max_turns=node.limits.max_turns,
            budget=node.limits.max_cost_usd,
            model=self.config.models.model_for(node.model),
            effort=AGENT_EFFORT,
            add_dirs=tuple(str(self.hub.parent / repo.dir) for repo in repos),
            tools=(
                *IMPLEMENTING_TOOLS,
                *gate_tools(command for repo in repos for command in (repo.check_fast, repo.check)),
            ),
            denied_tools=SESSION_DENIED_TOOLS,
        )
        if call.resume_session is not None:
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
            cwd=self.hub,
            timeout=_timeout(node, default=SESSION_TIMEOUT),
            output_limit=SESSION_OUTPUT_LIMIT,
        )
        reply = parse_session_output(result.stdout.decode(errors="replace"))
        if result.returncode != 0 or reply.is_error:
            detail = f"claude ended with exit {result.returncode} ({reply.subtype or 'no result'})"
            raise NodeFailedError("exec_failed", detail)
        text = reply.result
        if node.output_format is not None and (value := last_json_line(text)) is not None:
            text = json.dumps(value)
        return NodeReply(_bounded(text.encode(errors="surrogatepass")), reply.session_id)

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
        return self.hub if given is None else self.hub / given

    def _spawn(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        cwd: Path,
        timeout: float,
        output_limit: int = MAX_OUTPUT_BYTES + 1,
    ) -> ChildResult:
        try:
            return self.child(
                argv,
                cwd=cwd,
                env=env,
                timeout=timeout,
                own_session=False,
                output_limit=output_limit,
            )
        except ChildTimedOutError as error:
            raise NodeFailedError("timeout", str(error)) from None
        except OSError as error:
            detail = f"{argv[0]} could not start: {error.strerror or type(error).__name__}"
            raise NodeFailedError("config", detail) from None


def _timeout(node: ExecutableNode, *, default: float = GATE_TIMEOUT) -> float:
    return float(duration_seconds(node.timeout)) if node.timeout is not None else default


def _bounded(output: bytes) -> str:
    if len(output) > MAX_OUTPUT_BYTES:
        raise NodeFailedError(
            "output_contract", f"the output is larger than {MAX_OUTPUT_BYTES} bytes"
        )
    return output.decode(errors="replace")


def _detail(argv: Sequence[str], result: ChildResult) -> str:
    tail = result.stderr.decode(errors="replace")[-MAX_DETAIL_CHARS:]
    return f"{argv[0]} exited {result.returncode}: {tail}".rstrip()


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""
