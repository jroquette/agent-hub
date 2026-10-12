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
