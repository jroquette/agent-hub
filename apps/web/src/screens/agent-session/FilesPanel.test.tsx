import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FilesPanel, reviewedKey } from "./FilesPanel";
import { changedFiles, type ToolView } from "./model";

const tool = (id: string, name: string, input: Record<string, unknown>): ToolView => ({
  id,
  name,
  input,
  parentId: null,
  diff: null,
  result: { content: "ok", isError: false, truncated: false, originalBytes: null },
});

function filesOf(tools: ToolView[]) {
  return changedFiles({
    tools: Object.fromEntries(tools.map((one) => [one.id, one])),
    permissions: {},
  });
}

const TWO_FILES = [
  tool("t1", "Write", { file_path: "/repo/src/new.ts", content: "export const a = 1;" }),
  tool("t2", "Edit", { file_path: "/repo/src/ui/app.ts", old_string: "a", new_string: "b" }),
];

afterEach(() => {
  window.localStorage.clear();
});

describe("FilesPanel (review)", () => {
  it("lists each changed file with its lines, kind and diffs, and takes focus", () => {
    render(<FilesPanel files={filesOf(TWO_FILES)} sessionId="s1" onClose={vi.fn()} />);

    const panel = screen.getByRole("complementary", { name: "Changed files" });
    expect(screen.getByRole("heading", { name: "Changed files" })).toHaveFocus();
    expect(within(panel).getByText("0 of 2 viewed")).toBeInTheDocument();
    const nav = within(panel).getByRole("navigation", { name: "Files" });
    expect(
      within(nav)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["new.ts+1−0", "app.ts+1−1"]);
    const app = within(panel).getByRole("region", { name: "ui/app.ts" });
    expect(within(app).getByTitle("Modified")).toHaveTextContent("M");
    expect(within(app).getByLabelText("Change 1 to ui/app.ts")).toHaveTextContent("+b");
    expect(within(panel).getByRole("region", { name: "new.ts" })).toBeInTheDocument();
  });

  it("folds a file marked viewed, keeps the mark, and unfolds it after a newer change", async () => {
    const { rerender } = render(
      <FilesPanel files={filesOf(TWO_FILES)} sessionId="s1" onClose={vi.fn()} />,
    );
    const app = screen.getByRole("region", { name: "ui/app.ts" });

    await userEvent.click(within(app).getByRole("checkbox", { name: "Viewed" }));

    expect(within(app).queryByLabelText("Change 1 to ui/app.ts")).toBeNull();
    expect(screen.getByText("1 of 2 viewed")).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem(reviewedKey("s1")) ?? "{}")).toEqual({
      "/repo/src/ui/app.ts": "t2",
    });

    const later = [
      ...TWO_FILES,
      tool("t3", "Edit", { file_path: "/repo/src/ui/app.ts", old_string: "b", new_string: "c" }),
    ];
    rerender(<FilesPanel files={filesOf(later)} sessionId="s1" onClose={vi.fn()} />);

    const again = screen.getByRole("region", { name: "ui/app.ts" });
    expect(within(again).getByRole("checkbox", { name: "Changed since viewed" })).not.toBeChecked();
    expect(within(again).getByLabelText("Change 2 to ui/app.ts")).toBeInTheDocument();
  });

  it("closes on Esc and says when nothing changed yet", async () => {
    const onClose = vi.fn();
    render(<FilesPanel files={[]} sessionId="s1" onClose={onClose} />);

    expect(screen.getByText("Claude has not changed any file yet.")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledOnce();
  });
});
