import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// Read as a file (Vitest runs from apps/web): it does not process CSS imports, so `?raw` is empty.
const css = readFileSync(join(process.cwd(), "src/styles/tokens.css"), "utf8");

describe("tokens.css", () => {
  it("emits light and dark theme variables", () => {
    expect(css).toContain(':root, [data-theme="light"] {\n  --gray-50: #f7f8fa;');
    expect(css).toContain('[data-theme="dark"] {\n  --gray-50: #0b0d10;');
  });

  it("emits scalar tokens and font families once at the root", () => {
    expect(css).toContain("  --space-1: 4px;");
    expect(css).toContain("  --font-sans: Geist,");
    expect(css).toContain('  --font-mono: "Geist Mono",');
  });

  it("refers to other tokens through var()", () => {
    expect(css).not.toMatch(/: \{[a-z0-9.-]+\};/);
  });
});

/** WCAG relative luminance of `#rrggbb`. */
function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((at) => {
    const v = Number.parseInt(hex.slice(at, at + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

describe("highlight token colours (AC-234.31)", () => {
  interface Token {
    name: string;
    value: string | Record<string, string>;
  }
  const tokens = (
    JSON.parse(readFileSync(join(process.cwd(), "design/tokens.json"), "utf8")) as {
      color: { tokens: Token[] };
    }
  ).color.tokens;
  const value = (name: string, theme: string) => {
    const token = tokens.find((t) => t.name === name);
    return typeof token?.value === "string" ? token.value : (token?.value[theme] ?? "");
  };
  // The colours Markdown.css gives highlighted code, on the code block's ground.
  const used = ["text", "syntax-key", "syntax-string", "syntax-number", "syntax-keyword"];
  used.push("syntax-title", "syntax-comment", "diff-add", "diff-del");

  it.each(["light", "dark"])(
    "highlight: every token colour reads at 4.5:1 on code-bg (%s)",
    (theme) => {
      for (const name of used) {
        expect({ name, ok: contrast(value(name, theme), value("code-bg", theme)) >= 4.5 }).toEqual({
          name,
          ok: true,
        });
      }
    },
  );
});
