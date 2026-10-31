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
      "Show / hide steps: Ctrl Alt .",
      "Recall last prompt: ↑",
      "Stop (empty box): Esc",
    ]);
    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("ShortcutSheet (steps)", () => {
  it("AC-PG-32.2: lists the Steps drawer's shortcut in the Chat group", () => {
    render(<ShortcutSheet onClose={vi.fn()} />);

    expect(group("Chat")).toContain("Show / hide steps: Ctrl Alt .");
  });
});

// AGH-330 UX F7: Feature detail's Tickets tab keys.
describe("ShortcutSheet (tickets)", () => {
  it("lists the Tickets tab's keys in a Tickets group", () => {
    render(<ShortcutSheet onClose={vi.fn()} />);

    expect(group("Tickets")).toEqual([
      "Flow / table: v",
      "Flow full window: f",
      "Next / previous row: j k ↓ ↑",
      "Open the ticket panel: ↵ o",
      "Close the ticket panel: Esc",
    ]);
  });
});

// The Brain tree's own keys: on a row of the tree, and ↓ from its empty search field.
describe("ShortcutSheet (brain-tree)", () => {
  it("lists the Brain tree keys", () => {
    render(<ShortcutSheet onClose={vi.fn()} />);

    const keys = group("Brain tree").flatMap((row) => row.slice(row.indexOf(": ") + 2).split(" "));
    expect(new Set(keys)).toEqual(
      new Set(["↓", "↑", "j", "k", "Home", "End", "→", "←", "↵", "o", "Space"]),
    );
  });
});
