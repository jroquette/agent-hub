import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// Read as a file (Vitest runs from apps/web): it does not process CSS imports, so `?raw` is empty.
const css = readFileSync(join(process.cwd(), "src/styles/bundle.css"), "utf8");

/** The declarations of the first block whose selector is exactly `selector`. */
function ruleOf(selector: string, from = css): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const rule = new RegExp(`(?:^|\\n)\\s*${escaped} \\{([^}]*)\\}`).exec(from);
  if (!rule?.[1]) throw new Error(`no rule ${selector}`);
  return rule[1];
}

describe("select.ah-input", () => {
  // AC-596.5.14: the native arrow gives way to a chevron drawn from tokens, with room for it.
  it("draws its own chevron from tokens and keeps the text clear of it", () => {
    const rule = ruleOf("select.ah-input");

    expect(rule).toMatch(/\n {2}appearance: none;/);
    expect(rule).toContain("-webkit-appearance: none;");
    expect(rule).toContain("background-color: var(--surface);");
    // Four small triangles, every one in the theme's muted text colour, none in a literal colour.
    const gradients = rule.match(/linear-gradient\([^)]*\)/g) ?? [];
    expect(gradients).toHaveLength(4);
    for (const gradient of gradients) expect(gradient).toContain("var(--text-muted)");
    expect(rule).not.toMatch(/#[0-9a-f]{3,8}\b|rgb\(/i);
    expect(rule).toContain("background-repeat: no-repeat;");
    // The chevron sits 12-20px from the edge; the text stops before it.
    expect(rule).toContain("padding-right: calc(var(--space-3) + 20px);");
    expect(rule).toMatch(/right 12px top/);
    expect(rule).toMatch(/right 16px top/);
  });

  // AC-596.5.15: hover, keyboard focus and disabled read the same on every select.
  it("shows hover, focus and disabled the same everywhere, and keeps still under reduced motion", () => {
    const hover = ruleOf("select.ah-input:hover:not(:disabled)");
    expect(hover).toContain("background-color: var(--surface-hover);");
    expect(hover).toContain("border-color: var(--text-subtle);");

    expect(ruleOf("select.ah-input:focus-visible")).toContain(
      "outline: 2px solid var(--focus-ring);",
    );

    const disabled = ruleOf("select.ah-input:disabled");
    expect(disabled).toContain("opacity: 0.6;");
    expect(disabled).toContain("cursor: default;");

    expect(ruleOf("select.ah-input")).toMatch(/transition:[^;]*var\(--dur-fast\)/);
    const reduced =
      /@media \(prefers-reduced-motion: reduce\) \{\s*select\.ah-input \{([^}]*)\}/.exec(css);
    expect(reduced?.[1]).toContain("transition: none;");
  });
});
