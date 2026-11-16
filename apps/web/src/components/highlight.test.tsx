import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { highlightLines } from "./highlight";
import { languageOfPath } from "./useHighlight";

// AC-424.4: highlighted code split into the rows of a diff.
describe("highlightLines", () => {
  it("returns one list of nodes per line", () => {
    const lines = highlightLines("def f():\n    return 1", "python");

    expect(lines).toHaveLength(2);
    const { container } = render(<code>{lines?.[0]}</code>);
    expect(container).toHaveTextContent("def f():");
    expect(container.querySelector(".hljs-keyword")).toHaveTextContent("def");
  });

  it("opens a span that crosses a line break again on the next line", () => {
    const lines = highlightLines('x = """a\nb"""', "python");

    const second = render(<code>{lines?.[1]}</code>).container;
    expect(second.querySelector(".hljs-string")).toHaveTextContent('b"""');
  });

  it("keeps an empty line as an empty list", () => {
    expect(highlightLines("a = 1\n\nb = 2", "python")?.[1]).toEqual([]);
  });

  it("returns null for a language it does not know", () => {
    expect(highlightLines("x", "cobol")).toBeNull();
  });
});

describe("languageOfPath", () => {
  it.each([
    ["src/app.py", "py"],
    ["a/b/View.TSX", "tsx"],
    ["scripts/gen.mjs", "javascript"],
    ["Makefile", ""],
    [".gitignore", ""],
  ])("%s reads as %s", (path, language) => {
    expect(languageOfPath(path)).toBe(language);
  });
});
