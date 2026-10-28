import { render, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { highlight } from "./highlight";
import { HighlightedCode, languageName } from "./HighlightedCode";
import { languageOfPath } from "./useHighlight";

describe("HighlightedCode", () => {
  // AC-596.5.18: code is coloured by its language once the highlighter has loaded.
  it("colours the code in its language", async () => {
    const { container } = render(<HighlightedCode text={"def f():\n    return 1"} lang="python" />);

    const code = container.querySelector("code");
    await waitFor(() => {
      expect(code).toHaveClass("hljs");
    });
    expect(code?.querySelector(".hljs-keyword")).toHaveTextContent("def");
    expect(code).toHaveTextContent("def f(): return 1");
  });

  // AC-596.5.18: with no language, or one the highlighter does not hold, the text stays plain.
  it.each(["", "cobol"])("leaves the text plain for the language %j", async (lang) => {
    const { container } = render(<HighlightedCode text="PERFORM x" lang={lang} />);

    const code = container.querySelector("code");
    // Let the lazy chunk load first, so plain is not just "not loaded yet".
    render(<HighlightedCode text="x = 1" lang="python" />);
    await waitFor(() => {
      expect(document.querySelector("code.hljs")).not.toBeNull();
    });
    expect(code).not.toHaveClass("hljs");
    expect(code?.querySelector("span")).toBeNull();
    expect(code).toHaveTextContent("PERFORM x");
  });
});

describe("the language of a file", () => {
  // AC-596.5.18: one path-to-language map; every extension the app colours still maps to a
  // language the highlighter holds, and its badge names it.
  it.each([
    ["scripts/run.py", "Python"],
    ["types/stub.pyi", "Python"],
    ["deploy.sh", "Bash"],
    ["rc.zsh", "Bash"],
    ["hooks/check.bash", "Bash"],
    ["scenarios/demo-shop.yaml", "YAML"],
    ["actions/get-order.yml", "YAML"],
    ["data.json", "JSON"],
    ["tsconfig.jsonc", "JSON"],
    ["app.js", "JavaScript"],
    ["build.mjs", "JavaScript"],
    ["config.cjs", "JavaScript"],
    ["View.jsx", "JavaScript"],
    ["main.ts", "TypeScript"],
    ["a/b/View.TSX", "TypeScript"],
    ["lib.mts", "TypeScript"],
    ["lib.cts", "TypeScript"],
    ["schema.sql", "SQL"],
    ["main.go", "Go"],
    ["lib.rs", "Rust"],
    ["SKILL.md", "Markdown"],
    ["docs/page.mdx", "Markdown"],
    ["site.css", "CSS"],
    ["index.html", "HTML"],
    ["page.htm", "HTML"],
    ["feed.xml", "HTML"],
    ["App.vue", "HTML"],
  ])("%s is coloured and reads as %s", (path, words) => {
    const language = languageOfPath(path);

    expect(highlight("x", language)).not.toBeNull();
    expect(languageName(language)).toBe(words);
  });

  // AC-596.5.18: a file with no extension, or one the app does not colour, gets no badge.
  it.each(["Makefile", ".gitignore", "notes.txt"])("%s has no language words", (path) => {
    expect(languageName(languageOfPath(path))).toBe("");
  });

  // AC-596.5.18: the badge words name a language by its highlighter name or by its alias.
  it.each([
    ["python", "Python"],
    ["py", "Python"],
    ["typescript", "TypeScript"],
    ["tsx", "TypeScript"],
    ["yml", "YAML"],
    ["xml", "HTML"],
    ["bash", "Bash"],
    ["", ""],
  ])("%j reads as %j", (language, words) => {
    expect(languageName(language)).toBe(words);
  });
});
