import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RUN_FILES_SHOWN, RunFilesCard, runFilesOf, type RunFile } from "./RunFilesCard";
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
  it("keeps the files of the run's calls only, counting the lines of its applied changes (AC-265.11)", () => {
    const files = filesOf([
      edit("t1", "/r/a.ts"),
      edit("t2", "/r/b.ts"),
      edit("t3", "/r/a.ts"),
      edit("t4", "/r/a.ts", true),
    ]);

    const run = runFilesOf(files, new Set(["t3", "t4"]));

    expect(run.map((one) => [one.file.path, one.added, one.removed])).toEqual([["/r/a.ts", 2, 1]]);
  });

  it("lists the first files with their lines, opens one or the whole review (AC-265.11)", async () => {
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

describe("RunFilesCard (kinds of file)", () => {
  it("says Edited for a turn that only edits files an earlier turn created", () => {
    const files = filesOf([
      { ...edit("w1", "/r/a.md"), name: "Write", input: { file_path: "/r/a.md", content: "a" } },
      edit("e1", "/r/a.md"),
    ]);
    render(
      <RunFilesCard
        files={runFilesOf(files, new Set(["e1"]))}
        reviewed={{}}
        onOpenFile={vi.fn()}
      />,
    );
    expect(screen.getByText("Edited 1 file")).toBeInTheDocument();
  });

  const changed = (path: string, created: boolean): RunFile => ({
    file: {
      path,
      created,
      changes: [],
      added: 1,
      removed: 0,
      lastChangeId: `c-${path}`,
      net: null,
    },
    created,
    added: 1,
    removed: 0,
  });

  it("groups the code apart from Claude's plan and scratch, the scratch not waiting for review", () => {
    render(
      <RunFilesCard
        files={[
          changed("/tmp/notes.md", true),
          changed("/Users/me/.claude/plans/p.md", true),
          changed("/repo/src/a.ts", true),
        ]}
        reviewed={{}}
        onOpenFile={vi.fn()}
      />,
    );
    const card = screen.getByRole("region", { name: "Files edited in this turn" });
    expect(
      within(card)
        .getAllByRole("button", { name: /^Open / })
        .map((b) => b.title),
    ).toEqual(["/repo/src/a.ts", "/Users/me/.claude/plans/p.md", "/tmp/notes.md"]);
    expect(
      within(card).getByText("goes in the pull request", { exact: false }),
    ).toBeInTheDocument();
    expect(
      within(card).getByRole("button", {
        name: "Open /tmp/notes.md, Claude's notes, nothing to review, new, +1 −0, not for review",
      }),
    ).toBeInTheDocument();
  });
});
