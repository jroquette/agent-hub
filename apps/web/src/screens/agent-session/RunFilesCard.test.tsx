import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RUN_FILES_SHOWN, RunFilesCard, runFilesOf } from "./RunFilesCard";
import { changedFiles, type ToolView } from "./model";

const edit = (id: string, path: string, isError = false): ToolView => ({
  id,
  name: "Edit",
  input: { file_path: path, old_string: "a", new_string: "b\nc" },
  parentId: null,
  diff: null,
  result: { content: "ok", isError, truncated: false, originalBytes: null },
});

function filesOf(tools: ToolView[]) {
  return changedFiles({
    tools: Object.fromEntries(tools.map((tool) => [tool.id, tool])),
    permissions: {},
  });
}

describe("RunFilesCard (review)", () => {
  it("keeps the files of the run's calls only, counting the lines of its applied changes", () => {
    const files = filesOf([
      edit("t1", "/r/a.ts"),
      edit("t2", "/r/b.ts"),
      edit("t3", "/r/a.ts"),
      edit("t4", "/r/a.ts", true),
    ]);

    const run = runFilesOf(files, new Set(["t3", "t4"]));

    expect(run.map((one) => [one.file.path, one.added, one.removed])).toEqual([["/r/a.ts", 2, 1]]);
  });

  it("lists the first files with their lines, opens one or the whole review", async () => {
    const paths = Array.from({ length: RUN_FILES_SHOWN + 2 }, (_, i) => `/r/f${String(i)}.ts`);
    const files = filesOf(paths.map((path, i) => edit(`t${String(i)}`, path)));
    const onOpenFile = vi.fn();
    render(
      <RunFilesCard
        files={runFilesOf(files, new Set(files.map((file) => file.lastChangeId)))}
        reviewed={{ "/r/f0.ts": "t0" }}
        onOpenFile={onOpenFile}
      />,
    );

    const card = screen.getByRole("region", { name: "Files edited in this turn" });
    expect(within(card).getByText(`Edited ${String(paths.length)} files`)).toBeInTheDocument();
    expect(within(card).getAllByRole("listitem")).toHaveLength(RUN_FILES_SHOWN);

    await userEvent.click(
      within(card).getByRole("button", { name: "Open /r/f0.ts, modified, +2 −1, viewed" }),
    );
    await userEvent.click(within(card).getByRole("button", { name: "+2 more files" }));

    expect(onOpenFile.mock.calls).toEqual([["/r/f0.ts"], [null]]);
  });
});
