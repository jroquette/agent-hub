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
