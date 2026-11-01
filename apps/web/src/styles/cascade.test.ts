// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// Read as files: Vitest does not process CSS imports. The module URL goes through a constant, as
// Vite rewrites a literal `new URL("…", import.meta.url)` to a served URL.
const here = import.meta.url;
const STYLES = dirname(fileURLToPath(here));
const SRC = resolve(STYLES, "..");
const SIDE_EFFECT_IMPORT = /^import\s+["']([^"']+)["'];$/gm;

/** The stylesheets `cascade.ts` imports, as paths under `src/`, in its order. */
function cascade(): string[] {
  const source = readFileSync(join(STYLES, "cascade.ts"), "utf8");
  return [...source.matchAll(SIDE_EFFECT_IMPORT)].map(([, specifier = ""]) =>
    relative(SRC, resolve(STYLES, specifier)),
  );
}

/** Every stylesheet under `folder`, as paths under `src/`. */
function stylesheets(folder = SRC): string[] {
  return readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
    const path = join(folder, entry.name);
    if (entry.isDirectory()) return stylesheets(path);
    return entry.name.endsWith(".css") ? [relative(SRC, path)] : [];
  });
}

describe("the stylesheet order", () => {
  it("lists every stylesheet of the app once", () => {
    const listed = cascade();

    expect(listed).toEqual([...new Set(listed)]);
    expect([...listed].sort()).toEqual(stylesheets().sort());
  });

  it("ends with the design tokens, the fonts and the base styles, as the one-bundle build did", () => {
    expect(cascade().slice(-3)).toEqual([
      "styles/tokens.css",
      "styles/fonts.css",
      "styles/bundle.css",
    ]);
  });

  it("is the first module the entry imports, so no other import sets the order", () => {
    const entry = readFileSync(join(SRC, "main.tsx"), "utf8");
    const first = /^import\s[^;]*?["']([^"']+)["'];$/m.exec(entry);

    expect(first?.[1]).toBe("./styles/cascade");
  });
});
