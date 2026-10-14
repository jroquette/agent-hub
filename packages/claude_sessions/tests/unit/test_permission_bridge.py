"""``can_use_tool`` parked until the browser answers (D.4)."""

import asyncio
from typing import Any

import pytest
from claude_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionUpdate,
    ToolPermissionContext,
)
from claude_agent_sdk.types import PermissionRuleValue

from agent_hub.claude_sessions.permission_bridge import CLOSED, INTERRUPTED, PermissionBridge
from agent_hub.core.agent_sessions.driver import (
    Allow,
    Deny,
    DriverEvent,
    PermissionRequest,
    PermissionSuggestion,
)
from agent_hub.core.agent_sessions.errors import PermissionAnsweredError, UnknownPermissionError

pytestmark = pytest.mark.anyio

RULE = PermissionUpdate(
    type="addRules",
    rules=[PermissionRuleValue(tool_name="Bash", rule_content="npm run *")],
    behavior="allow",
    destination="localSettings",
)


def _context(
    tool_use_id: str | None = "toolu_1", *suggestions: PermissionUpdate
) -> ToolPermissionContext:
    return ToolPermissionContext(suggestions=list(suggestions), tool_use_id=tool_use_id)


class Bridge:
    """A bridge and what it emitted."""

    def __init__(self) -> None:
        self.events: list[DriverEvent] = []
        self.bridge = PermissionBridge(self.events.append)

    def ask(
        self, tool: str, data: dict[str, Any], context: ToolPermissionContext
    ) -> asyncio.Task[Any]:
        return asyncio.ensure_future(self.bridge.can_use_tool(tool, data, context))

    async def request(self) -> PermissionRequest:
        while not self.events:
            await asyncio.sleep(0)
        event = self.events[-1]
        assert isinstance(event, PermissionRequest)
        return event


async def test_resolves_allow_when_answered() -> None:
    probe = Bridge()
    asked = probe.ask("Bash", {"command": "npm run build"}, _context("toolu_1", RULE))
    request = await probe.request()

    assert request == PermissionRequest(
        request_id="toolu_1",
        tool="Bash",
        input={"command": "npm run build"},
        suggestions=(
            PermissionSuggestion(index=0, destination="localSettings", rule=RULE.to_dict()),
        ),
        request_kind="tool",
    )
    await asyncio.sleep(0.05)
    assert not asked.done()
    probe.bridge.answer("toolu_1", Allow(updated_permissions=request.suggestions))
    result = await asked

    assert isinstance(result, PermissionResultAllow)
    assert result.updated_input is None
    assert result.updated_permissions is not None
    assert [p.to_dict() for p in result.updated_permissions] == [RULE.to_dict()]


async def test_passes_answers_when_ask_user_question_allowed() -> None:
    probe = Bridge()
    asked = probe.ask(
        "AskUserQuestion", {"questions": [{"question": "Which?"}]}, _context("toolu_q")
    )
    request = await probe.request()
    probe.bridge.answer(request.request_id, Allow(updated_input={"answers": {"Which?": "A"}}))
    result = await asked

    assert request.request_kind == "ask_user_question"
    assert isinstance(result, PermissionResultAllow)
    assert result.updated_input == {"answers": {"Which?": "A"}}
    assert result.updated_permissions is None


async def test_marks_plan_approval_when_exit_plan_mode_asks() -> None:
    probe = Bridge()
    asked = probe.ask("ExitPlanMode", {}, _context("toolu_p"))
    request = await probe.request()
    probe.bridge.answer(request.request_id, Deny(message="Keep planning"))
    result = await asked

    assert request.request_kind == "plan_approval"
    assert result == PermissionResultDeny(message="Keep planning")


async def test_mints_request_id_when_tool_use_id_missing_or_unsafe() -> None:
    probe = Bridge()
    first = probe.ask("Bash", {}, _context(None))
    one = await probe.request()
    second = probe.ask("Bash", {}, _context("not safe/../id"))
    while len(probe.events) < 2:
        await asyncio.sleep(0)
    two = probe.events[-1]
    assert isinstance(two, PermissionRequest)

    assert one.request_id != two.request_id
    assert one.request_id.startswith("permission-")
    assert two.request_id.startswith("permission-")
    probe.bridge.deny_all(CLOSED)
    await asyncio.gather(first, second)


async def test_refuses_answer_when_unknown_or_answered_twice() -> None:
    probe = Bridge()
    asked = probe.ask("Bash", {}, _context("toolu_1"))
    await probe.request()
    probe.bridge.answer("toolu_1", Allow())
    await asked

    with pytest.raises(PermissionAnsweredError):
        probe.bridge.answer("toolu_1", Allow())
    with pytest.raises(UnknownPermissionError):
        probe.bridge.answer("toolu_9", Allow())


async def test_denies_all_when_closed() -> None:
    probe = Bridge()
    first = probe.ask("Bash", {}, _context("toolu_1"))
    second = probe.ask("Write", {}, _context("toolu_2"))
    while len(probe.events) < 2:
        await asyncio.sleep(0)

    assert probe.bridge.pending() == ("toolu_1", "toolu_2")
    probe.bridge.close()
    results = await asyncio.gather(first, second)
    late = await probe.bridge.can_use_tool("Bash", {}, _context("toolu_3"))

    assert results == [PermissionResultDeny(message=CLOSED)] * 2
    assert late == PermissionResultDeny(message=CLOSED)
    assert probe.bridge.pending() == ()
    assert len(probe.events) == 2


async def test_denies_parked_when_interrupted() -> None:
    probe = Bridge()
    asked = probe.ask("Bash", {}, _context("toolu_1"))
    await probe.request()

    probe.bridge.deny_all(INTERRUPTED)

    assert await asked == PermissionResultDeny(message=INTERRUPTED)
    with pytest.raises(PermissionAnsweredError):
        probe.bridge.answer("toolu_1", Allow())


async def test_forgets_request_when_cli_cancels_it() -> None:
    probe = Bridge()
    asked = probe.ask("Bash", {}, _context("toolu_1"))
    await probe.request()

    asked.cancel()
    await asyncio.gather(asked, return_exceptions=True)

    assert probe.bridge.pending() == ()
    with pytest.raises(UnknownPermissionError):
        probe.bridge.answer("toolu_1", Allow())


BYPASS = PermissionUpdate(type="setMode", mode="bypassPermissions", destination="localSettings")
ROOT = PermissionUpdate(type="addDirectories", directories=["/"], destination="localSettings")


async def test_emits_only_local_allow_rules_when_cli_suggests_mode_or_directories() -> None:
    probe = Bridge()
    asked = probe.ask("Bash", {"command": "rm -rf build"}, _context("toolu_1", BYPASS, RULE, ROOT))
    request = await probe.request()
    probe.bridge.answer("toolu_1", Deny(message="no"))
    await asked

    assert request.suggestions == (
        PermissionSuggestion(index=1, destination="localSettings", rule=RULE.to_dict()),
    )


async def test_passes_no_update_when_answer_carries_mode_or_directories() -> None:
    probe = Bridge()
    asked = probe.ask("Bash", {"command": "ls"}, _context("toolu_1", BYPASS, ROOT))
    await probe.request()
    smuggled = tuple(
        PermissionSuggestion(index=index, destination="localSettings", rule=update.to_dict())
        for index, update in enumerate((BYPASS, ROOT))
    )
    probe.bridge.answer("toolu_1", Allow(updated_permissions=smuggled))
    result = await asked

    assert isinstance(result, PermissionResultAllow)
    assert result.updated_permissions is None
