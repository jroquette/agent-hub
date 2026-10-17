import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { ChangedFilesChip, FilesPanel, reviewedKey } from "./FilesPanel";
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
  it("lists the changed files by folder, like source control, and takes focus (AC-265.7)", () => {
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

  it("opens one file with its changes, steps to the next and goes back to all files (AC-265.8)", async () => {
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

  it("keeps a viewed mark per session until a newer change to the file (AC-265.9)", async () => {
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

  it("goes back to the list on Esc, then closes, and says when nothing changed yet (AC-265.8)", async () => {
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

describe("ChangedFilesChip (review)", () => {
  it("counts the files and lines, says how many wait for review, then shows a check (AC-265.10)", async () => {
    const files = filesOf(TWO_FILES);
    const onToggle = vi.fn();
    const { rerender } = render(
      <ChangedFilesChip
        files={files}
        review={{ reviewed: {}, toggle: vi.fn() }}
        open={false}
        onToggle={onToggle}
      />,
    );

    const chip = screen.getByRole("button", {
      name: "Changed files: 2 files, 2 lines added, 1 removed, 2 to review",
    });
    expect(chip).toHaveClass("as-files-chip-due");
    await userEvent.click(chip);
    expect(onToggle).toHaveBeenCalledTimes(1);

    const reviewed = Object.fromEntries(files.map((file) => [file.path, file.lastChangeId]));
    rerender(
      <ChangedFilesChip
        files={files}
        review={{ reviewed, toggle: vi.fn() }}
        open
        onToggle={onToggle}
      />,
    );
    const done = screen.getByRole("button", {
      name: "Changed files: 2 files, 2 lines added, 1 removed, all reviewed",
    });
    expect(done).not.toHaveClass("as-files-chip-due");
    expect(done).toHaveAttribute("aria-expanded", "true");
  });
});

describe("FilesPanel (long-files)", () => {
  it("numbers a change Claude reported and keeps every change whole for the body to scroll (AC-265.15)", async () => {
    const reported = "--- a/a.ts\n+++ b/a.ts\n@@ -40,1 +40,2 @@\n-x\n+y\n+z\n";
    const edited: ToolView = {
      ...tool("t1", "Edit", { file_path: "/r/a.ts", old_string: "x", new_string: "y\nz" }),
      result: {
        content: "ok",
        isError: false,
        truncated: false,
        originalBytes: null,
        diff: reported,
      },
    };
    render(
      <FilesPanel
        files={filesOf([
          edited,
          tool("t2", "Edit", { file_path: "/r/a.ts", old_string: "q", new_string: "r" }),
        ])}
        sessionId="s1"
        onClose={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /a\.ts/ }));

    expect(screen.getByLabelText("Change 1 to r/a.ts")).toHaveClass("as-diff-numbered");
    expect(screen.getByLabelText("Change 2 to r/a.ts")).not.toHaveClass("as-diff-numbered");
    const css = readFileSync(
      join(process.cwd(), "src/screens/agent-session/agent-session.css"),
      "utf8",
    );
    expect(/\.as-files-change \{[^}]*\bflex: none;/.exec(css)).not.toBeNull();
  });
});

describe("FilesPanel (comments)", () => {
  it("counts a file's open review threads in the list, leaving out the resolved ones (AC-265.17)", () => {
    const thread = (key: string, path: string) => ({
      key,
      anchor: { path, change: 1, side: "new" as const, start: 1, end: 1 },
      messages: [],
      waiting: false,
    });
    render(
      <FilesPanel
        files={filesOf(TWO_FILES)}
        sessionId="s1"
        onClose={vi.fn()}
        comments={{
          threads: [
            thread("c1", "/repo/src/ui/app.ts"),
            thread("c2", "/repo/src/ui/app.ts"),
            thread("c3", "/repo/src/new.ts"),
          ],
          resolved: { resolved: new Set(["c3"]), toggle: vi.fn() },
        }}
      />,
    );

    expect(screen.getByTitle("2 open review comments")).toHaveTextContent("2");
    expect(screen.queryByTitle(/1 open review comment/)).toBeNull();
  });
});
