import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// Read as a file (Vitest runs from apps/web): it does not process CSS imports, so `?raw` is empty.
const css = readFileSync(join(process.cwd(), "src/styles/tokens.css"), "utf8");

describe("tokens.css", () => {
  it("emits light and dark theme variables", () => {
    expect(css).toContain(':root, [data-theme="light"] {\n  --gray-50: #f1ede4;');
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

describe("diff syntax colours (AC-424.5)", () => {
  // A diff coloured in its file's language shows the code on the added and removed lines' grounds.
  const used = ["text", "syntax-key", "syntax-string", "syntax-number", "syntax-keyword"];
  used.push("syntax-title", "syntax-comment", "diff-add", "diff-del");

  it.each(["light", "dark"])(
    "every token colour reads at 4.5:1 on the added and removed grounds (%s)",
    (theme) => {
      for (const ground of ["diff-add-bg", "diff-del-bg"]) {
        for (const name of used) {
          const ok = contrast(value(name, theme), value(ground, theme)) >= 4.5;
          expect({ name, ground, ok }).toEqual({ name, ground, ok: true });
        }
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
    // The step states two-level-flows S2 adds (AGH-405): `waiting` (hand, filled segment) and
    // `stale` (clock, an idle-soft segment edged in idle), on the page and the panel.
    ["waiting", "surface"],
    ["waiting", "surface-overlay"],
    ["idle", "surface"],
    ["idle", "idle-soft"],
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

// AGH-428: the light theme's grounds are warm sand off-whites, not bright white; dark is unchanged.
describe("Warm sand light theme (AC-428.*)", () => {
  const grounds = ["bg", "surface", "surface-sunken", "surface-hover", "surface-overlay"];

  /** The `#rrggbb` channels as numbers. */
  function channels(hex: string): [number, number, number] {
    return [1, 3, 5].map((at) => Number.parseInt(hex.slice(at, at + 2), 16)) as [
      number,
      number,
      number,
    ];
  }

  it("AC-428.1: every light ground is a warm off-white, the panels lighter than the app ground", () => {
    for (const ground of grounds) {
      const hex = value(ground, "light");
      const [r, g, b] = channels(hex);
      expect({ ground, hex, warm: r >= g && g >= b && r > b, white: hex === "#ffffff" }).toEqual({
        ground,
        hex,
        warm: true,
        white: false,
      });
    }
    expect(luminance(value("surface", "light"))).toBeGreaterThan(luminance(value("bg", "light")));
  });

  it("AC-428.2: light text reads at 4.5:1 and control outlines at 3:1 on every ground", () => {
    for (const ground of grounds) {
      for (const text of ["text", "text-muted", "text-subtle", "accent"]) {
        const ok = contrast(value(text, "light"), value(ground, "light")) >= 4.5;
        expect({ text, ground, ok }).toEqual({ text, ground, ok: true });
      }
    }
    for (const ground of ["bg", "surface"]) {
      const ok = contrast(value("border-control", "light"), value(ground, "light")) >= 3;
      expect({ ground, ok }).toEqual({ ground, ok: true });
    }
  });

  it("AC-428.3: the dark theme keeps its grounds and lines", () => {
    const dark = Object.fromEntries(
      [...grounds, "border", "border-strong", "border-control", "text-subtle", "code-bg"].map(
        (name) => [name, value(name, "dark")],
      ),
    );
    expect(dark).toEqual({
      bg: "#0b0d10",
      surface: "#121519",
      "surface-sunken": "#0e1014",
      "surface-hover": "#191d23",
      "surface-overlay": "#171a20",
      border: "#232830",
      "border-strong": "#2f353f",
      "border-control": "#666e7e",
      "text-subtle": "#8b93a3",
      "code-bg": "#0e1014",
    });
  });
});

// AGH-422: the chat's reading ground and the owner's turn card (surface-turn), in both themes.
describe("Chat colour pairs (AGH-422)", () => {
  it.each(["light", "dark"])(
    "AC-422.8 text reads at 4.5:1 on the owner's turn card (%s)",
    (theme) => {
      for (const text of ["text", "text-muted", "text-subtle", "accent"]) {
        expect({
          text,
          ok: contrast(value(text, theme), value("surface-turn", theme)) >= 4.5,
        }).toEqual({
          text,
          ok: true,
        });
      }
    },
  );
});
