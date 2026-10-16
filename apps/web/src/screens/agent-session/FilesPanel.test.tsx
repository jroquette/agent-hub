import { render, screen, waitFor, within } from "@testing-library/react";
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
  it("lists the changed files by folder, like source control, and takes focus", () => {
    render(<FilesPanel files={filesOf(TWO_FILES)} sessionId="s1" onClose={vi.fn()} />);

    const panel = screen.getByRole("complementary", { name: "Changed files" });
    expect(screen.getByRole("heading", { name: "Changed files" })).toHaveFocus();
    expect(within(panel).getByText("0 of 2 viewed")).toBeInTheDocument();
    const list = within(panel).getByRole("navigation", { name: "Files" });
    expect(within(list).getByText("ui")).toBeInTheDocument();
    expect(
      within(list)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Anew.ts+1−0", "Mapp.ts+1−1"]);
    // Narrow, no file is open until you pick one: the list is all there is.
    expect(within(panel).queryByRole("region")).toBeNull();
  });

  it("opens one file with its changes, steps to the next and goes back to all files", async () => {
    render(<FilesPanel files={filesOf(TWO_FILES)} sessionId="s1" onClose={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /new\.ts/ }));

    const file = screen.getByRole("region", { name: "new.ts" });
    expect(within(file).getByText("1 change in this session")).toBeInTheDocument();
    expect(within(file).getByLabelText("Change 1 to new.ts")).toHaveTextContent("+export const");
    expect(screen.queryByRole("navigation", { name: "Files" })).toBeNull();

    await userEvent.click(within(file).getByRole("button", { name: "Next file" }));
    const next = screen.getByRole("region", { name: "ui/app.ts" });
    expect(within(next).getByText("2/2")).toBeInTheDocument();
    expect(within(next).getByRole("button", { name: "Next file" })).toBeDisabled();

    await userEvent.click(within(next).getByRole("button", { name: "All files" }));
    expect(screen.getByRole("navigation", { name: "Files" })).toBeInTheDocument();
  });

  it("keeps a viewed mark per session until a newer change to the file", async () => {
    const { rerender } = render(
      <FilesPanel files={filesOf(TWO_FILES)} sessionId="s1" onClose={vi.fn()} />,
    );
    const list = screen.getByRole("navigation", { name: "Files" });

    const [, appViewed] = within(list).getAllByRole("checkbox", { name: "Viewed" });
    if (!appViewed) throw new Error("no Viewed checkbox for app.ts");
    await userEvent.click(appViewed);

    expect(screen.getByText("1 of 2 viewed")).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem(reviewedKey("s1")) ?? "{}")).toEqual({
      "/repo/src/ui/app.ts": "t2",
    });

    const later = [
      ...TWO_FILES,
      tool("t3", "Edit", { file_path: "/repo/src/ui/app.ts", old_string: "b", new_string: "c" }),
    ];
    rerender(<FilesPanel files={filesOf(later)} sessionId="s1" onClose={vi.fn()} />);

    expect(screen.getByRole("checkbox", { name: "Changed since viewed" })).not.toBeChecked();
    expect(screen.getByText("0 of 2 viewed")).toBeInTheDocument();
  });

  it("goes back to the list on Esc, then closes, and says when nothing changed yet", async () => {
    const onClose = vi.fn();
    const { rerender } = render(
      <FilesPanel files={filesOf(TWO_FILES)} sessionId="s1" onClose={onClose} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /new\.ts/ }));

    await userEvent.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("navigation", { name: "Files" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /new\.ts/ })).toHaveFocus();
    });
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledOnce();

    rerender(<FilesPanel files={[]} sessionId="s1" onClose={onClose} />);
    expect(screen.getByText("Claude has not changed any file yet.")).toBeInTheDocument();
  });
});
