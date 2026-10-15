import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ToolCallCard, resultText } from "./ToolCallCard";
import type { PermissionView, ToolResultView, ToolView } from "./transcript";

function aTool(overrides: Partial<ToolView> = {}): ToolView {
  return {
    id: "toolu_01",
    name: "Bash",
    input: { command: "make check" },
    parentId: null,
    diff: null,
    result: null,
    ...overrides,
  };
}

async function expand(tool: ToolView) {
  render(<ToolCallCard tool={tool} tools={{ [tool.id]: tool }} calls={{}} />);
  await userEvent.click(screen.getByRole("button"));
}

describe("ToolCallCard (transcript)", () => {
  it("shows a running Bash call with its command when expanded", async () => {
    await expand(aTool());

    expect(screen.getByRole("button", { name: "Bash make check (Running)" })).toBeInTheDocument();
    expect(screen.getAllByText("make check").map((node) => node.tagName)).toContain("PRE");
  });

  it("shows an error result, its truncation and the stored-copy label", async () => {
    await expand(
      aTool({
        result: {
          content: "fatal [redacted: github-token]",
          isError: true,
          truncated: true,
          originalBytes: 70000,
        },
      }),
    );

    expect(screen.getByRole("button", { name: /\(Error\)/ })).toBeInTheDocument();
    expect(screen.getAllByText("Error")).toHaveLength(2);
    expect(screen.getByText("stored copy, redacted")).toBeInTheDocument();
    expect(screen.getByText(/Stored truncated: 70,000 bytes in full/)).toBeInTheDocument();
  });

  it("shows JSON when the input has no command and the result no text", async () => {
    await expand(
      aTool({
        name: "mcp__linear__get_issue",
        input: { id: 7 },
        result: { content: { ok: true }, isError: false, truncated: false, originalBytes: null },
      }),
    );

    expect(
      screen.getByRole("button", { name: "mcp__linear__get_issue (Done)" }),
    ).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("true")).toBeInTheDocument();
  });

  it("shows a MultiEdit as one diff per edit", async () => {
    await expand(
      aTool({
        name: "MultiEdit",
        input: {
          file_path: "a.py",
          edits: [
            { old_string: "x", new_string: "y" },
            { old_string: "p", new_string: "q" },
          ],
        },
      }),
    );

    const diff = screen.getByLabelText("Diff of a.py");
    expect(within(diff).getByText("+y")).toBeInTheDocument();
    expect(within(diff).getByText("+q")).toBeInTheDocument();
  });
});

function aRequest(overrides: Partial<PermissionView> = {}): PermissionView {
  return {
    requestId: "toolu_01",
    tool: "Bash",
    requestKind: "tool",
    summary: "make check",
    input: null,
    suggestions: [],
    askedAt: "2026-01-01T00:00:00Z",
    deadlineAt: null,
    decision: null,
    redacted: false,
    ...overrides,
  };
}
const decided = (decision: "allow" | "deny") => ({
  decision,
  by: null,
  message: null,
  at: "2026-01-01T00:00:01Z",
});
const ok: ToolResultView = { content: "ok", isError: false, truncated: false, originalBytes: null };
const failed: ToolResultView = { ...ok, content: "no", isError: true };

describe("ToolCallCard (tool-cards) states", () => {
  it.each([
    ["running", {}, undefined, "Running", "loader"],
    ["waiting for you", {}, aRequest(), "Waiting for you", "hand"],
    ["done", { result: ok }, aRequest({ decision: decided("allow") }), "Done", "circle-check"],
    ["error", { result: failed }, undefined, "Error", "circle-x"],
    ["denied", { result: failed }, aRequest({ decision: decided("deny") }), "Denied", "shield-x"],
  ] as const)("reads %s with an icon and text", (_, tool, request, text, icon) => {
    render(<ToolCallCard tool={aTool(tool)} tools={{}} calls={{}} request={request} />);

    const head = screen.getByRole("button", { name: `Bash make check (${text})` });
    const state = within(head).getByText(text);
    expect(state.closest(".as-tool-state")?.querySelector(`[data-icon="${icon}"]`)).not.toBeNull();
  });

  it("reads Waiting for you only while the permission is open", () => {
    const { rerender } = render(
      <ToolCallCard tool={aTool()} tools={{}} calls={{}} request={aRequest()} />,
    );
    expect(screen.getByText("Waiting for you")).toBeInTheDocument();

    rerender(
      <ToolCallCard
        tool={aTool()}
        tools={{}}
        calls={{}}
        request={aRequest({ decision: decided("allow") })}
      />,
    );
    expect(screen.getByText("Running")).toBeInTheDocument();
  });
});

describe("resultText", () => {
  it("joins the text blocks of a content list and gives up on other shapes", () => {
    expect(
      resultText([{ type: "text", text: "a" }, { type: "image" }, { type: "text", text: "b" }]),
    ).toBe("a\nb");
    expect(resultText([{ type: "image" }])).toBeNull();
    expect(resultText(3)).toBeNull();
  });
});
