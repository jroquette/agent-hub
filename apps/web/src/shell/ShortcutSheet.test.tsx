import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import { ShortcutSheet } from "./ShortcutSheet";

/** The rows of the sheet's group `title`, as "label: keys". */
function group(title: string): string[] {
  const heading = screen.getByText(title);
  const column = heading.parentElement;
  if (!column) throw new Error(`no group ${title}`);
  return Array.from(column.querySelectorAll(".ah-sheet-row")).map((row) => {
    const [label, keys] = Array.from(row.children);
    const kbds = keys ? within(keys as HTMLElement).queryAllByText(/./) : [];
    return `${label?.textContent ?? ""}: ${kbds.map((k) => k.textContent).join(" ")}`;
  });
}

describe("ShortcutSheet (one-tab)", () => {
  it("lists Sessions and no Live sessions under Go to", () => {
    render(<ShortcutSheet onClose={vi.fn()} />);

    expect(group("Go to")).toEqual([
      "Portfolio: g p",
      "Sessions: g s",
      "Workflow runs: g r",
      "Command palette: Ctrl K",
    ]);
  });
});

describe("ShortcutSheet (chat-shortcuts)", () => {
  it("lists the chat's keys in a Chat group", async () => {
    const { container } = render(<ShortcutSheet onClose={vi.fn()} />);

    expect(group("Chat")).toEqual([
      "Commands: /",
      "Allow oldest: Ctrl Alt ↵",
      "Deny oldest: Ctrl Alt ⌫",
      "Allow / deny focused: a d",
      "Focus message: Shift Esc",
      "Recall last prompt: ↑",
      "Stop (empty box): Esc",
    ]);
    expect(await seriousViolations(container)).toEqual([]);
  });
});
