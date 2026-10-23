import { render, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useDiffSyntax } from "./diffSyntax";
import { diffLines } from "./ToolCallCard";

const DIFF = [
  "@@ -1,3 +1,3 @@",
  " def f():",
  "-    return 1",
  "+    return 2",
  "... diff truncated",
].join("\n");

describe("useDiffSyntax", () => {
  it("colours each code line in the file's language, and no other row (AC-424.4)", async () => {
    const lines = diffLines(DIFF);
    const { result } = renderHook(() => useDiffSyntax(lines, "src/app.py"));

    await waitFor(() => {
      expect(result.current).not.toBeNull();
    });
    const rows = result.current ?? [];
    expect(rows).toHaveLength(5);
    expect(rows[0]).toBeNull();
    expect(rows[1]).not.toBeNull();
    expect(rows[2]).not.toBeNull();
    expect(rows[3]).not.toBeNull();
    expect(rows[4]).toBeNull();
  });

  it("leaves a file of an unknown language plain (AC-424.4)", () => {
    const lines = diffLines(DIFF);
    const { result } = renderHook(() => useDiffSyntax(lines, "notes.txt"));

    expect(result.current).toBeNull();
  });

  it("leaves a diff without a path plain (AC-424.4)", () => {
    const lines = diffLines(DIFF);
    const { result } = renderHook(() => useDiffSyntax(lines, undefined));

    expect(result.current).toBeNull();
  });

  it("starts each hunk afresh, so a string left open in one does not colour the next", async () => {
    const lines = diffLines(
      [
        "@@ -1,2 +1,2 @@",
        " def f():",
        '+    """Opens a docstring the hunk never closes.',
        "@@ -40,1 +40,1 @@",
        "+return value",
      ].join("\n"),
    );
    const { result } = renderHook(() => useDiffSyntax(lines, "src/app.py"));

    await waitFor(() => {
      expect(result.current).not.toBeNull();
    });
    const { container } = render(<>{result.current?.[4]}</>);
    expect(container.querySelector(".hljs-keyword")?.textContent).toBe("return");
    expect(container.querySelector(".hljs-string")).toBeNull();
  });
});
