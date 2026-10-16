import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DiffText, ToolCallCard, diffLines, resultText } from "./ToolCallCard";
import type { PermissionView, ToolResultView, ToolView } from "./model";

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

describe("ToolCallCard (tool-cards) long output", () => {
  const output = (length: number) => aTool({ result: { ...ok, content: "x".repeat(length) } });

  it("shows 10,000 characters whole", async () => {
    await expand(output(10_000));

    expect(screen.getAllByText("x".repeat(10_000))).toHaveLength(1);
    expect(screen.queryByRole("button", { name: /Show all/ })).toBeNull();
  });

  it("cuts 10,001 characters to 10,000 and Show all brings the rest, focus on the output", async () => {
    await expand(output(10_001));

    const pre = screen.getByText("x".repeat(10_000));
    expect(pre.tagName).toBe("PRE");
    await userEvent.click(screen.getByRole("button", { name: "Show all (10,001 characters)" }));

    expect(pre).toHaveTextContent(/^x{10001}$/);
    expect(screen.queryByRole("button", { name: /Show all/ })).toBeNull();
    expect(pre).toHaveFocus();
  });

  it("counts an emoji as one character and never cuts it in half", async () => {
    const smile = "\u{1F600}";
    await expand(aTool({ result: { ...ok, content: `${"x".repeat(9_999)}${smile}` } }));

    expect(screen.getByText(`${"x".repeat(9_999)}${smile}`).tagName).toBe("PRE");
    expect(screen.queryByRole("button", { name: /Show all/ })).toBeNull();
  });

  it("cuts after a whole emoji and counts the rest in characters", async () => {
    const smile = "\u{1F600}";
    await expand(aTool({ result: { ...ok, content: `${"x".repeat(9_999)}${smile}y` } }));

    expect(screen.getByText(`${"x".repeat(9_999)}${smile}`).tagName).toBe("PRE");
    expect(
      screen.getByRole("button", { name: "Show all (10,001 characters)" }),
    ).toBeInTheDocument();
  });

  /** A structured result whose JSON text is `length` characters. */
  const structured = (length: number) => {
    const pad = JSON.stringify({ data: "" }, null, 2).length;
    return aTool({ result: { ...ok, content: { data: "x".repeat(length - pad) } } });
  };

  it("shows a structured result of 10,000 characters whole as JSON", async () => {
    await expand(structured(10_000));

    expect(screen.queryByRole("button", { name: /Show all/ })).toBeNull();
    expect(screen.getByText(/^"?x{100}/)).toBeInTheDocument();
  });

  it("cuts a structured result over 10,000 characters as text and Show all brings the rest", async () => {
    await expand(structured(10_001));

    const pre = screen.getByText(/^\{\s+"data": "x+"$/);
    expect(pre.tagName).toBe("PRE");
    expect(pre.textContent).toHaveLength(10_000);
    await userEvent.click(screen.getByRole("button", { name: "Show all (10,001 characters)" }));

    expect(pre.textContent).toHaveLength(10_001);
    expect(pre).toHaveFocus();
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

describe("DiffText (line-numbers)", () => {
  const REPORTED = "--- a/x.py\n+++ b/x.py\n@@ -12,3 +12,4 @@\n a\n-b\n+c\n+d\n e\n";

  it("numbers each line in the old and the new file from its hunk header (AC-265.15)", () => {
    expect(diffLines(REPORTED).map((line) => [line.kind, line.oldNo, line.newNo])).toEqual([
      ["head", null, null],
      ["head", null, null],
      ["hunk", null, null],
      ["ctx", 12, 12],
      ["del", 13, null],
      ["add", null, 13],
      ["add", null, 14],
      ["ctx", 14, 15],
    ]);
  });

  it("shows git's two gutters and no file headers when numbered (AC-265.15)", () => {
    const { container } = render(<DiffText diff={REPORTED} label="Change" numbered />);

    const rows = Array.from(container.querySelectorAll(".as-diff-line"), (row) =>
      Array.from(row.children, (cell) => cell.textContent.trimEnd()),
    );
    expect(rows).toEqual([
      ["", "", "@@ -12,3 +12,4 @@"],
      ["12", "12", " a"],
      ["13", "", "-b"],
      ["", "13", "+c"],
      ["", "14", "+d"],
      ["14", "15", " e"],
    ]);
    expect(screen.getByLabelText("Change")).not.toHaveTextContent("+++ b/x.py");
  });

  it("uses Claude's reported diff, with line numbers, once the edit ran (AC-265.15)", async () => {
    render(
      <ToolCallCard
        tool={aTool({
          name: "Edit",
          input: { file_path: "x.py", old_string: "b", new_string: "c\nd" },
          result: {
            content: "ok",
            isError: false,
            truncated: false,
            originalBytes: null,
            diff: REPORTED,
          },
        })}
        tools={{}}
        calls={{}}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /Edit/ }));

    const diff = screen.getByLabelText("Diff of x.py");
    expect(diff).toHaveClass("as-diff-numbered");
    expect(diff).toHaveTextContent("@@ -12,3 +12,4 @@");
  });
});
