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

interface Token {
  name: string;
  value: string | Record<string, string>;
}
const tokens = (
  JSON.parse(readFileSync(join(process.cwd(), "design/tokens.json"), "utf8")) as {
    color: { tokens: Token[] };
  }
).color.tokens;

/** A colour token's `#rrggbb` in `theme`, following `{other}` references. */
function value(name: string, theme: string): string {
  const token = tokens.find((t) => t.name === name);
  const found = typeof token?.value === "string" ? token.value : (token?.value[theme] ?? "");
  const ref = /^\{(.+)\}$/.exec(found)?.[1];
  return ref ? value(ref, theme) : found;
}

describe("highlight token colours (AC-234.31)", () => {
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

// two-level-flows AC-1.14 as amended by A16: jsdom computes no colours, so each theme's contrast is
// checked here, on the token pairs the ticket panel, the owner-wait callouts and banner use.
describe("Feature detail colour pairs (AC-1.14, A16)", () => {
  // The panel's ground, the boxed banners' (warning: waiting-soft, info: live-soft) and the page's.
  const grounds = ["surface-overlay", "surface", "waiting-soft", "live-soft"];
  // Their words: body, muted and subtle text, and links.
  const texts = ["text", "text-muted", "text-subtle", "accent"];
  // Marks that carry a state: step dots and bars, the banners' icons.
  const marks: [string, string][] = [
    ...["done", "live", "blocked", "failed", "idle"].map((m): [string, string] => [
      m,
      "surface-overlay",
    ]),
    ["waiting", "waiting-soft"],
    ["live", "live-soft"],
  ];

  it.each(["light", "dark"])("text reads at 4.5:1 on each ground (%s)", (theme) => {
    for (const ground of grounds) {
      for (const text of texts) {
        expect({
          text,
          ground,
          ok: contrast(value(text, theme), value(ground, theme)) >= 4.5,
        }).toEqual({ text, ground, ok: true });
      }
    }
  });

  it.each(["light", "dark"])("state marks read at 3:1 on their ground (%s)", (theme) => {
    for (const [mark, ground] of marks) {
      expect({ mark, ground, ok: contrast(value(mark, theme), value(ground, theme)) >= 3 }).toEqual(
        {
          mark,
          ground,
          ok: true,
        },
      );
    }
  });
});
