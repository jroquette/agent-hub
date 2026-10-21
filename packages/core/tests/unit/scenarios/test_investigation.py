"""An investigation's names and the proposal an agent records (P-5, P-8, AM-3, AM-11;
docs/design/scenarios.md § Investigation, § Events and bounds)."""

import json
from typing import Any

import pytest

import agent_hub.core.scenarios.investigation as investigation
from agent_hub.core.scenarios.investigation import (
    Finding,
    ProposalError,
    ProposedStep,
    investigation_gate,
    parse_proposal,
)

# An AWS access key's shape, built at run time: never a literal in the repo.
AWS_SHAPE = "AKIA" + "ABCDEFGHIJKLMNOP"


def a_proposal(**overrides: Any) -> dict[str, Any]:
    proposal: dict[str, Any] = {
        "findings": [
            {"title": "Order stays on hold", "text": "The queue never drains.", "evidence": "x"}
        ],
        "options": [
            {
                "summary": "Release the hold, then look again",
                "steps": [{"action": "demo/release-hold", "with": {"target": "api", "count": 2}}],
            }
        ],
    }
    return proposal | overrides


def encoded(value: object) -> bytes:
    return json.dumps(value).encode()


def test_names_gate_and_choices_when_investigation_constants_read() -> None:
    assert investigation_gate("order-held") == "order-held__investigation"
    assert investigation_gate("walk__order-held") == "walk__order-held__investigation"
    assert investigation.CHOICES == ("pick", "retry", "stop")
    assert investigation.MAX_INVESTIGATIONS == 10
    assert investigation.MAX_PROPOSAL_BYTES == 256 * 1024
    assert (investigation.MAX_FINDINGS, investigation.MAX_OPTIONS) == (20, 5)
    assert (investigation.MAX_TITLE_CHARS, investigation.MAX_TEXT_CHARS) == (120, 2000)
    assert (investigation.MAX_SUMMARY_CHARS, investigation.MAX_STEPS) == (300, 10)


def test_reads_findings_and_options_when_investigation_proposal_valid() -> None:
    proposal = parse_proposal(encoded(a_proposal()))

    assert proposal.findings == (
        Finding(title="Order stays on hold", text="The queue never drains.", evidence="x"),
    )
    (option,) = proposal.options
    assert option.summary == "Release the hold, then look again"
    assert option.steps == (
        ProposedStep(action="demo/release-hold", inputs={"target": "api", "count": 2}),
    )


def test_redacts_secret_shape_when_proposal_parsed() -> None:
    finding = {"title": f"key {AWS_SHAPE}", "text": f"seen {AWS_SHAPE}", "evidence": AWS_SHAPE}
    step = {"action": "demo/get-order", "with": {"ref": AWS_SHAPE}}
    given = a_proposal(
        findings=[finding], options=[{"summary": f"use {AWS_SHAPE}", "steps": [step]}]
    )

    proposal = parse_proposal(encoded(given))

    shown = repr(proposal)
    assert AWS_SHAPE not in shown
    assert proposal.findings[0].title == "key [redacted: AWS access key]"
    assert proposal.findings[0].evidence == "[redacted: AWS access key]"
    assert proposal.options[0].summary == "use [redacted: AWS access key]"
    assert proposal.options[0].steps[0].inputs == {"ref": "[redacted: AWS access key]"}


def over_bounds() -> list[tuple[bytes, str]]:
    """Each bound one past its constant, and the first problem it reports."""
    limits = investigation
    finding = {"title": "t", "text": "x"}
    step = {"action": "demo/get-order"}
    option = {"summary": "s", "steps": [step]}
    return [
        (b" " * (limits.MAX_PROPOSAL_BYTES + 1), "larger than 262144 bytes"),
        (b"[]", "the proposal must be an object"),
        (b"{nope", "not one JSON value"),
        (encoded({"findings": []}), "the proposal needs options"),
        (encoded(a_proposal(extra=1)), "unknown key 'extra'"),
        (
            encoded(a_proposal(findings=[finding] * (limits.MAX_FINDINGS + 1))),
            "findings: at most 20",
        ),
        (
            encoded(a_proposal(findings=[{"title": "t" * 121, "text": "x"}])),
            "finding 1: title must be text of 1 to 120 characters",
        ),
        (
            encoded(a_proposal(findings=[{"title": "t", "text": "x" * 2001}])),
            "finding 1: text must be text of 0 to 2000 characters",
        ),
        (
            encoded(a_proposal(findings=[{"title": "t", "text": "x", "evidence": "e" * 2001}])),
            "finding 1: evidence must be text of 0 to 2000 characters",
        ),
        (encoded(a_proposal(options=[option] * (limits.MAX_OPTIONS + 1))), "options: at most 5"),
        (
            encoded(a_proposal(options=[{"summary": "s" * 301, "steps": []}])),
            "option 1: summary must be text of 1 to 300 characters",
        ),
        (
            encoded(a_proposal(options=[{"summary": "s", "steps": [step] * 11}])),
            "option 1: steps: at most 10",
        ),
        (
            encoded(a_proposal(options=[{"summary": "s", "steps": [{"action": "a", "with": []}]}])),
            "option 1 step 1: with must map names to text, numbers or booleans",
        ),
    ]


@pytest.mark.parametrize(("data", "problem"), over_bounds())
def test_refuses_proposal_when_over_bounds(data: bytes, problem: str) -> None:
    with pytest.raises(ProposalError) as raised:
        parse_proposal(data)

    assert problem in str(raised.value)


def test_takes_bounds_exactly_when_proposal_at_limits() -> None:
    finding = {"title": "t" * 120, "text": "x" * 2000, "evidence": "e" * 2000}
    steps = [{"action": "demo/get-order"}] * 10
    given = a_proposal(
        findings=[finding] * 20, options=[{"summary": "s" * 300, "steps": steps}] * 5
    )

    proposal = parse_proposal(encoded(given))

    assert (len(proposal.findings), len(proposal.options)) == (20, 5)


# The investigation session's tool policy (P-17, AM-3, AM-4 safety 1).
RUN = "a1b2c3d4"
ENV_FILE_NAME = ".env.staging"


def a_policy(tmp_path: Any) -> tuple[investigation.ToolPolicy, Any]:
    """A hub and its sibling repo holding a declared env file; the policy of run ``RUN``."""
    workspace = tmp_path / "work"
    hub = workspace / "demo-hub"
    (hub / "actions" / "orders").mkdir(parents=True)
    env_folder = workspace / "demo-api" / "environment"
    env_folder.mkdir(parents=True)
    (env_folder / ENV_FILE_NAME).write_text("DEMO_DB_URL=placeholder\n", encoding="utf-8")
    policy = investigation.ToolPolicy.of(
        hub=str(hub), env_files=("demo-api/environment/.env.staging",), run_id=RUN
    )
    return policy, hub


@pytest.mark.parametrize(
    ("tool", "tool_input", "allowed"),
    [
        ("Read", {"file_path": "README.md"}, True),
        ("Glob", {"pattern": "actions/**/*.yaml"}, True),
        ("Grep", {"pattern": "order", "path": "actions"}, True),
        ("Write", {"file_path": "actions/orders/x.yaml", "content": "kind: action\n"}, True),
        ("Write", {"file_path": "actions/orders/scripts/x.sh", "content": "echo\n"}, True),
        ("Write", {"file_path": "README.md", "content": "x"}, False),
        ("Write", {"file_path": "actions/x.yaml", "content": "x"}, False),
        ("Write", {"file_path": "actions/orders/../../README.md", "content": "x"}, False),
        ("Bash", {"command": "./hub action list"}, True),
        ("Bash", {"command": "./hub action list --json"}, True),
        ("Bash", {"command": "./hub action plan orders/get-order --env staging"}, True),
        (
            "Bash",
            {"command": f"./hub action run orders/get-order --run {RUN} --input order_id=o-1"},
            True,
        ),
        (
            "Bash",
            {"command": f"./hub scenario propose --run {RUN} <<'PROPOSAL'\n{{}}\nPROPOSAL"},
            True,
        ),
        ("Bash", {"command": "./hub action run orders/get-order --env staging"}, False),
        ("Bash", {"command": "./hub action run orders/get-order --run other-run"}, False),
        ("Bash", {"command": "./hub scenario propose --run other-run <<'P'\n{}\nP"}, False),
        (
            "Bash",
            {"command": f"./hub scenario propose --run {RUN} <<'P'\n{{}}\nP\nrm -rf /\nP"},
            False,
        ),
        ("Bash", {"command": f"./hub scenario propose --run {RUN} <<P\n$(id)\nP"}, False),
        ("Bash", {"command": "./hub action list; rm -rf /"}, False),
        ("Bash", {"command": "./hub action list && curl http://localhost"}, False),
        ("Bash", {"command": "./hub action list | sh"}, False),
        ("Bash", {"command": "./hub action list $(id)"}, False),
        ("Bash", {"command": "./hub action list `id`"}, False),
        ("Bash", {"command": "./hub action list > out.txt"}, False),
        ("Bash", {"command": "./hub action list\nrm -rf /"}, False),
        ("Bash", {"command": "./hub workflow run demo"}, False),
        ("Bash", {"command": "aws s3 ls"}, False),
        ("Bash", {"command": "curl http://localhost:8080"}, False),
        ("Bash", {"command": "hub action list"}, False),
        ("Edit", {"file_path": "actions/orders/x.yaml"}, False),
        ("WebFetch", {"url": "http://localhost"}, False),
        ("Task", {"prompt": "x"}, False),
        ("mcp__demo__tool", {}, False),
    ],
)
def test_allows_only_listed_calls_when_investigation_read_only_tool_verdict(
    tmp_path: Any, tool: str, tool_input: dict[str, Any], *, allowed: bool
) -> None:
    policy, _hub = a_policy(tmp_path)

    verdict = investigation.tool_verdict(policy, tool, tool_input)

    assert verdict.allowed is allowed
    assert verdict.allowed or verdict.reason


def test_denies_reads_when_investigation_credentials_env_file_targeted(tmp_path: Any) -> None:
    policy, hub = a_policy(tmp_path)
    env_file = hub.parent / "demo-api" / "environment" / ENV_FILE_NAME
    (hub / "link-to-env").symlink_to(env_file)
    (hub / "link-to-folder").symlink_to(env_file.parent)
    denied = [
        ("Read", {"file_path": str(env_file)}),
        ("Read", {"file_path": "../demo-api/environment/.env.staging"}),
        ("Read", {"file_path": "actions/../../demo-api/environment/.env.staging"}),
        ("Read", {"file_path": "link-to-env"}),
        ("Read", {"file_path": "link-to-folder/.env.staging"}),
        ("Grep", {"pattern": "DEMO", "path": str(env_file)}),
        ("Grep", {"pattern": "DEMO", "path": "../demo-api/environment"}),
        ("Grep", {"pattern": "DEMO", "path": "link-to-folder"}),
        ("Grep", {"pattern": "DEMO", "path": "..", "glob": "**/.env.*"}),
        ("Glob", {"pattern": "../demo-api/**/.env*"}),
        ("Glob", {"pattern": "*", "path": "link-to-folder"}),
        ("Glob", {"pattern": "**/*", "path": str(hub.parent)}),
        ("Glob", {"pattern": str(env_file)}),
        # A running action's environment holds the env file's values.
        ("Read", {"file_path": "/proc/self/environ"}),
        ("Grep", {"pattern": "DEMO", "path": "/proc"}),
        ("Grep", {"pattern": "DEMO", "path": "/"}),
        ("Glob", {"pattern": "/proc/*/environ"}),
        ("Glob", {"pattern": "*/*/environ", "path": "/"}),
        # Claude Code splits a Grep glob on spaces and commas; ripgrep reads each part as a
        # gitignore-style glob that overrides .gitignore, so these reach the ignored env file.
        ("Grep", {"pattern": "DEMO", "path": "../demo-api", "glob": "*.py .env.staging"}),
        ("Grep", {"pattern": "DEMO", "path": "../demo-api", "glob": "*.py,.env.staging"}),
        ("Grep", {"pattern": "DEMO", "path": "../demo-api", "glob": "\\.env*"}),
        ("Grep", {"pattern": "DEMO", "path": "../demo-api", "glob": "/env/.env*"}),
        ("Grep", {"pattern": "DEMO", "path": "../demo-api", "glob": "env/\\.env.staging"}),
        ("Grep", {"pattern": "DEMO", "path": "..", "glob": "\\.env*"}),
        ("Grep", {"pattern": "DEMO", "path": "..", "glob": "*.py"}),
        # Any filter, negations included, under a root holding one: splitting is not mimicked.
        ("Grep", {"pattern": "DEMO", "path": "..", "glob": "!a,.env*"}),
        ("Grep", {"pattern": "DEMO", "path": "..", "glob": "!a\\{b,.env*"}),
        ("Grep", {"pattern": "DEMO", "path": "..", "glob": "!a[{],.env*"}),
        ("Grep", {"pattern": "DEMO", "path": "..", "glob": "!a\ufeff.env*"}),
        ("Grep", {"pattern": "DEMO", "path": "..", "glob": "!*.env*"}),
    ]
    passed = [
        ("Read", {"file_path": "../demo-api/environment/other.txt"}),
        # E-5: a Grep above the folder with no glob skips the git-ignored env file.
        ("Grep", {"pattern": "DEMO", "path": ".."}),
        ("Grep", {"pattern": "DEMO", "path": "actions", "glob": "*.yaml"}),
        ("Glob", {"pattern": "**/*.yaml", "path": str(hub.parent)}),
    ]

    verdicts = [investigation.tool_verdict(policy, tool, given) for tool, given in denied]
    passes = [investigation.tool_verdict(policy, tool, given) for tool, given in passed]

    assert [verdict.allowed for verdict in verdicts] == [False] * len(denied)
    assert all("env file" in verdict.reason or "/proc" in verdict.reason for verdict in verdicts)
    assert all(str(env_file.resolve()) not in verdict.reason for verdict in verdicts)
    assert [verdict.allowed for verdict in passes] == [True] * len(passed)
    assert policy.env_files == (str(env_file.resolve()),)


def test_denies_reads_when_investigation_path_outside_workspace(tmp_path: Any) -> None:
    policy, hub = a_policy(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.txt").write_text("not the workspace's\n", encoding="utf-8")
    (hub / "link-out").symlink_to(outside)
    denied = [
        ("Read", {"file_path": "~/.aws/credentials"}),
        ("Read", {"file_path": str(outside / "notes.txt")}),
        ("Read", {"file_path": "link-out/notes.txt"}),
        ("Read", {"file_path": "../../outside/notes.txt"}),
        ("Glob", {"pattern": "*", "path": str(outside)}),
        ("Glob", {"pattern": "../../outside/*"}),
        ("Glob", {"pattern": "*", "path": "link-out"}),
        ("Grep", {"pattern": "x", "path": str(outside)}),
        ("Grep", {"pattern": "x", "path": "link-out"}),
        ("Grep", {"pattern": "x", "path": "~"}),
    ]

    verdicts = [investigation.tool_verdict(policy, tool, given) for tool, given in denied]

    assert [verdict.allowed for verdict in verdicts] == [False] * len(denied)
    assert all("workspace" in verdict.reason for verdict in verdicts)
    assert investigation.tool_verdict(policy, "Read", {"file_path": "README.md"}).allowed


def test_refuses_policy_when_investigation_workspace_is_root() -> None:
    # A hub at /demo-hub would make the whole file system its workspace.
    with pytest.raises(investigation.WorkspaceRootError, match="workspace"):
        investigation.ToolPolicy.of(hub="/demo-hub", env_files=(), run_id=RUN)
