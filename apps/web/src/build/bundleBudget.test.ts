// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { checkBundle } from "./bundleBudget";
import { budgetPlugin } from "./bundlePlugins";

// The limits the owner set, in bytes: 400,000 B for the entry chunk alone and 350,000 B for the
// vendor chunk.
const LIMITS = { entry: 400_000, vendor: 350_000 };

const ENTRY = "assets/index-AbCd1234.js";
const VENDOR = "assets/vendor-EfGh5678.js";
const SESSIONS = "assets/sessions-list-IjKl9012.js";

function entry(size: number) {
  return { fileName: ENTRY, name: "index", isEntry: true, size };
}

function vendor(size: number) {
  return { fileName: VENDOR, name: "vendor", isEntry: false, size };
}

// A route's own chunk (Rolldown names it after the screen's folder) and the highlighter's chunk.
const OTHER_CHUNKS = [
  { fileName: SESSIONS, name: "sessions-list", isEntry: false, size: 41_233 },
  { fileName: "assets/highlight-MnOp3456.js", name: "highlight", isEntry: false, size: 72_196 },
];

// A size in bytes as a line may print it, 400001 or 400,001, and never inside a longer number.
function bytes(size: number): string {
  return `(?<![\\d,])${String(size).replace(/\B(?=(\d{3})+$)/g, ",?")}(?!,?\\d)`;
}

// Matches text with a line that names every part: a file name as written, or a size in bytes.
function lineNaming(...parts: (string | number)[]): RegExp {
  const lookaheads = parts.map((part) =>
    typeof part === "number"
      ? `(?=.*${bytes(part)})`
      : `(?=.*${part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`,
  );
  return new RegExp(`^${lookaheads.join("")}`, "m");
}

describe("checkBundle", () => {
  it("passes and prints the entry's and the vendor chunk's size in bytes when both are under their limits", () => {
    // 1 B under each limit. Together they are 749,998 B: only each chunk measured alone passes.
    const result = checkBundle([entry(399_999), vendor(349_999), ...OTHER_CHUNKS], LIMITS);

    expect(result.ok).toBe(true);
    const printed = result.lines.join("\n");
    expect(printed).toMatch(lineNaming(ENTRY, 399_999));
    expect(printed).toMatch(lineNaming(VENDOR, 349_999));
  });

  it.each([
    { example: "a fixture entry 1 B over the 400,000 B limit", size: 400_001, limit: 400_000 },
    // The entry of the plan's shell-only build (238,832 B), against a limit set 1 B under it.
    { example: "a limit set 1 B under the entry's real size", size: 238_832, limit: 238_831 },
  ])(
    "fails naming the entry file, its size in bytes and the limit when it is 1 B over ($example)",
    ({ size, limit }) => {
      const result = checkBundle([entry(size), vendor(277_418), ...OTHER_CHUNKS], {
        ...LIMITS,
        entry: limit,
      });

      expect(result.ok).toBe(false);
      expect(result.lines.join("\n")).toMatch(lineNaming(ENTRY, size, limit));
    },
  );

  it("fails naming the vendor chunk when it is over its limit", () => {
    const result = checkBundle([entry(238_832), vendor(350_001), ...OTHER_CHUNKS], LIMITS);

    expect(result.ok).toBe(false);
    expect(result.lines.join("\n")).toMatch(lineNaming(VENDOR, 350_001, 350_000));
  });

  it("fails when the bundle has no entry chunk", () => {
    const result = checkBundle([vendor(277_418), ...OTHER_CHUNKS], LIMITS);

    expect(result.ok).toBe(false);
    expect(result.lines.join("\n")).toMatch(/entry/i);
  });
});

// Chunk code of exactly `size` bytes in UTF-8. It starts with a "…" (3 bytes, 1 character), as the
// app's copy does, so a size taken from the string's length comes out 2 short.
function code(size: number): string {
  return "…" + ";".repeat(size - 3);
}

// What `this.error` throws in a Rolldown plugin, which stops the build.
class BuildStopped extends Error {}

// The plugin's `this` in generateBundle: `error` throws, as Rolldown's does; the log calls print.
const bundler = {
  error(cause: string | { message: string }): never {
    throw new BuildStopped(typeof cause === "string" ? cause : cause.message);
  },
  info: () => undefined,
  warn: () => undefined,
  debug: () => undefined,
};

// The output bundle Vite hands to generateBundle: the entry, the vendor chunk, a route chunk and the
// entry's styles.
function outputBundle(sizes: { entry: number; vendor: number }) {
  const items = [
    { type: "chunk", fileName: ENTRY, name: "index", isEntry: true, code: code(sizes.entry) },
    { type: "chunk", fileName: VENDOR, name: "vendor", isEntry: false, code: code(sizes.vendor) },
    {
      type: "chunk",
      fileName: SESSIONS,
      name: "sessions-list",
      isEntry: false,
      code: code(41_233),
    },
    { type: "asset", fileName: "assets/index-QrSt3456.css", names: ["index.css"], source: "p{}\n" },
  ];
  return Object.fromEntries(items.map((item) => [item.fileName, item]));
}

// Runs the plugin's generateBundle hook as Vite does before it writes the build, with `log` as
// the bundler's `this`.
async function generateBundle(bundle: object, log: object = bundler): Promise<void> {
  const hook = budgetPlugin().generateBundle;
  const handler = typeof hook === "object" ? hook.handler : hook;
  if (handler === undefined) throw new Error("the plugin has no generateBundle hook");
  const context = log as unknown as ThisParameterType<typeof handler>;
  const options = { dir: "web_dist" } as unknown as Parameters<typeof handler>[0];
  await handler.call(context, options, bundle as unknown as Parameters<typeof handler>[1], true);
}

describe("budgetPlugin", () => {
  it("lets the build go on and prints the entry's and the vendor chunk's size when both are under their limits", async () => {
    const info = vi.fn<(line: string) => void>();

    await generateBundle(outputBundle({ entry: 399_999, vendor: 349_999 }), { ...bundler, info });

    const printed = info.mock.calls.map(([line]) => line).join("\n");
    expect(printed).toMatch(lineNaming(ENTRY, 399_999));
    expect(printed).toMatch(lineNaming(VENDOR, 349_999));
  });

  it.each([
    {
      culprit: "the entry",
      file: ENTRY,
      size: 400_001,
      limit: 400_000,
      sizes: { entry: 400_001, vendor: 349_999 },
    },
    {
      culprit: "the vendor chunk",
      file: VENDOR,
      size: 350_001,
      limit: 350_000,
      sizes: { entry: 399_999, vendor: 350_001 },
    },
  ])(
    "stops the build with this.error when the check fails ($culprit 1 B over its limit)",
    async ({ file, size, limit, sizes }) => {
      // Bytes, not characters: a size taken from the string's length would be under the limit.
      expect([Buffer.byteLength(code(size)), code(size).length]).toEqual([size, size - 2]);

      const stopped = generateBundle(outputBundle(sizes));

      await expect(stopped).rejects.toThrow(BuildStopped);
      await expect(stopped).rejects.toThrow(lineNaming(file, size, limit));
    },
  );
});
