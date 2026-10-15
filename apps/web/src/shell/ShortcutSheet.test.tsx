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

describe("ShortcutSheet (chat-shortcuts)", () => {
  it("lists the chat's keys in a Chat group", async () => {
    const { container } = render(<ShortcutSheet onClose={vi.fn()} />);

    expect(group("Chat")).toEqual([
      "Commands (at the start of the message): /",
      "Allow the oldest request: Ctrl Alt ↵",
      "Deny the oldest request: Ctrl Alt ⌫",
      "Allow / deny the focused request: a d",
      "Focus the message box: Shift Esc",
      "Recall the last prompt: ↑",
      "Stop the turn (empty message box): Esc",
    ]);
    expect(await seriousViolations(container)).toEqual([]);
  });
});
