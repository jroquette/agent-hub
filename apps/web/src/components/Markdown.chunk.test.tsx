import { act, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Markdown } from "./Markdown";

// The lazy chunk fails to load (a stale build, a network error): blocks stay plain, nothing throws.
const load = vi.hoisted(() => ({ attempts: 0 }));
vi.mock("./highlight", () => {
  load.attempts += 1;
  throw new Error("chunk failed to load");
});

describe("Markdown highlight chunk (AC-234.31)", () => {
  // First in the file: the chunk is loaded at most once per page, so later tests would hide this.
  it("highlight: a page with no highlightable block never loads the chunk", async () => {
    const source = [
      ["```", "no language", "```"].join("\n"),
      ["```bash", ...Array.from({ length: 2001 }, () => "# c"), "```"].join("\n"),
      ["```ts", "const open = 1;"].join("\n"),
    ].join("\n\n");
    const { container } = render(<Markdown source={source} streaming />);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    expect(container.querySelectorAll("pre code")).toHaveLength(3);
    expect(load.attempts).toBe(0);
  });

  it("highlight-limits: a failed lazy import leaves the block plain", async () => {
    const { container } = render(<Markdown source={["```ts", "const a = 1;", "```"].join("\n")} />);
    await act(async () => {
      await vi.waitFor(() => {
        expect(load.attempts).toBe(1);
      });
    });

    const code = container.querySelector("pre code");
    expect(code).toHaveTextContent("const a = 1;");
    expect(code?.querySelector("span")).toBeNull();
    expect(code).not.toHaveClass("hljs");
  });
});
