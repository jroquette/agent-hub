import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ToolGroup, groupSummary, type GroupItem } from "./ToolGroup";
import type { PermissionView, ToolResultView, ToolView } from "./transcript";

const ok: ToolResultView = { content: "ok", isError: false, truncated: false, originalBytes: null };

function aTool(id: string, name: string, result: ToolResultView | null = ok): ToolView {
  return { id, name, input: { pattern: id }, parentId: null, diff: null, result };
}

function aRequest(requestId: string): PermissionView {
  return {
    requestId,
    tool: "Bash",
    requestKind: "tool",
    summary: "rm -rf build",
    input: null,
    suggestions: [],
    askedAt: "2026-01-01T00:00:00Z",
    deadlineAt: null,
    decision: null,
    redacted: false,
  };
}

const explored: GroupItem[] = [
  { tool: aTool("r1", "Read") },
  { tool: aTool("g1", "Grep") },
  { tool: aTool("r2", "Read") },
  { tool: aTool("g2", "Grep") },
  { tool: aTool("r3", "Read") },
];

function show(items: GroupItem[], onAnswerPermission = vi.fn()) {
  return render(
    <ToolGroup items={items} tools={{}} calls={{}} onAnswerPermission={onAnswerPermission} />,
  );
}

describe("ToolGroup (tool-cards)", () => {
  it("counts the calls by name, first seen first", () => {
    expect(groupSummary(explored.map((item) => item.tool))).toBe("Explored · 3 Read, 2 Grep");
  });

  it("starts collapsed when every call is done and opens and closes from the keyboard", async () => {
    show(explored);

    const head = screen.getByRole("button", { name: "Explored · 3 Read, 2 Grep" });
    expect(head).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: /^Read r1/ })).toBeNull();

    head.focus();
    await userEvent.keyboard("{Enter}");

    expect(head).toHaveAttribute("aria-expanded", "true");
    const list = document.getElementById(head.getAttribute("aria-controls") ?? "");
    if (!list) throw new Error("no list");
    expect(within(list).getAllByRole("button")).toHaveLength(5);

    await userEvent.keyboard(" ");
    expect(head).toHaveAttribute("aria-expanded", "false");
  });

  it("opens when a call waits for you and shows its permission card under it", () => {
    show([
      { tool: aTool("r1", "Read") },
      { tool: aTool("b1", "Bash", null), request: aRequest("b1") },
    ]);

    expect(screen.getByRole("button", { name: /^Explored/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    const call = screen.getByRole("button", { name: /Bash b1 \(Waiting for you\)/ });
    expect(call.closest(".as-tool")?.nextElementSibling).toHaveAttribute("data-request-id", "b1");
  });

  it("opens when a call failed", () => {
    show([{ tool: aTool("r1", "Read") }, { tool: aTool("r2", "Read", { ...ok, isError: true }) }]);

    expect(screen.getByRole("button", { name: /^Explored/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("stays collapsed while a call only runs", () => {
    show([{ tool: aTool("r1", "Read") }, { tool: aTool("r2", "Read", null) }]);

    expect(screen.getByRole("button", { name: /^Explored/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("opens again when a collapsed group's call starts waiting for you", async () => {
    const items = [{ tool: aTool("r1", "Read") }, { tool: aTool("b1", "Bash", null) }];
    const { rerender } = show(items);
    const head = screen.getByRole("button", { name: /^Explored/ });
    await userEvent.click(head);
    await userEvent.click(head);
    expect(head).toHaveAttribute("aria-expanded", "false");

    rerender(
      <ToolGroup
        items={[
          items[0] as GroupItem,
          { tool: aTool("b1", "Bash", null), request: aRequest("b1") },
        ]}
        tools={{}}
        calls={{}}
        onAnswerPermission={vi.fn()}
      />,
    );

    expect(head).toHaveAttribute("aria-expanded", "true");
  });
});
