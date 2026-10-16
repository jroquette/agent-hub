import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Markdown } from "./Markdown";

// Counts the lazy chunk's highlight calls while keeping its real output.
const calls = vi.hoisted(() => [] as string[]);
vi.mock("./highlight", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./highlight")>();
  return {
    ...actual,
    highlight: (code: string, language: string) => {
      calls.push(code);
      return actual.highlight(code, language);
    },
  };
});

describe("Markdown highlight cost (AC-234.31)", () => {
  it("highlight: a closed block is highlighted once while later text keeps streaming", async () => {
    const closed = ["```ts", "const done = 1;", "```"].join("\n");
    const source = (tail: string) => `${closed}\n\nStill ${tail}`;
    const { container, rerender } = render(<Markdown source={source("w")} streaming />);
    await waitFor(() => {
      expect(container.querySelector("pre code.hljs")).not.toBeNull();
    });

    for (const tail of ["wr", "wri", "writ", "writing"]) {
      rerender(<Markdown source={source(tail)} streaming />);
    }

    expect(container.querySelector("pre code.hljs span")).not.toBeNull();
    expect(container).toHaveTextContent("Still writing");
    expect(calls.filter((code) => code === "const done = 1;")).toHaveLength(1);
  });
});
