import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ToolCallCard, resultText } from "./ToolCallCard";
import type { ToolView } from "./transcript";

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

describe("resultText", () => {
  it("joins the text blocks of a content list and gives up on other shapes", () => {
    expect(
      resultText([{ type: "text", text: "a" }, { type: "image" }, { type: "text", text: "b" }]),
    ).toBe("a\nb");
    expect(resultText([{ type: "image" }])).toBeNull();
    expect(resultText(3)).toBeNull();
  });
});
