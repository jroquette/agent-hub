// @vitest-environment node
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { brotliCompressSync, brotliDecompressSync, constants } from "node:zlib";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { compressAssets } from "./compressAssets";

// A text file of exactly `size` bytes, so the 1 KB threshold (1,024 B) is tested on its edge.
function text(size: number): Buffer {
  return Buffer.from(
    "const answer = 42; /* agent-hub */\n".repeat(Math.ceil(size / 35)).slice(0, size),
  );
}

let outDir: string;

beforeEach(async () => {
  outDir = await mkdtemp(join(tmpdir(), "ah-compress-"));
  await mkdir(join(outDir, "assets"));
});

afterEach(async () => {
  await rm(outDir, { recursive: true, force: true });
});

async function build(files: Record<string, Buffer>): Promise<void> {
  for (const [name, bytes] of Object.entries(files)) {
    await writeFile(join(outDir, name), bytes);
  }
  // The arrange step holds what the test needs: every file is on disk, and no variant exists yet.
  const assets = await readdir(join(outDir, "assets"));
  expect(assets.filter((name) => name.endsWith(".br"))).toEqual([]);
  expect(assets.length).toBe(
    Object.keys(files).filter((name) => name.startsWith("assets/")).length,
  );
}

async function listing(): Promise<string[]> {
  return (await readdir(join(outDir, "assets"))).sort();
}

describe("compressAssets", () => {
  it("writes a .br file next to each .js, .css and .svg of 1 KB or more under assets", async () => {
    await build({
      "assets/app-AbCd1234.js": text(4096),
      "assets/style-AbCd1234.css": text(1024),
      "assets/icon-AbCd1234.svg": text(1500),
    });

    const written = await compressAssets(outDir);

    expect(await listing()).toEqual([
      "app-AbCd1234.js",
      "app-AbCd1234.js.br",
      "icon-AbCd1234.svg",
      "icon-AbCd1234.svg.br",
      "style-AbCd1234.css",
      "style-AbCd1234.css.br",
    ]);
    expect(written).toHaveLength(3);
  });

  it("writes no variant for files under 1 KB, fonts or index.html", async () => {
    await build({
      "index.html": text(4096),
      "assets/app-AbCd1234.js": text(4096),
      "assets/small-AbCd1234.js": text(1023),
      "assets/font-AbCd1234.woff2": text(4096),
      "assets/photo-AbCd1234.png": text(4096),
    });

    const written = await compressAssets(outDir);

    expect(await listing()).toEqual([
      "app-AbCd1234.js",
      "app-AbCd1234.js.br",
      "font-AbCd1234.woff2",
      "photo-AbCd1234.png",
      "small-AbCd1234.js",
    ]);
    expect((await readdir(outDir)).sort()).toEqual(["assets", "index.html"]);
    expect(written).toHaveLength(1);
  });

  it("decodes each .br file to the original file's exact bytes", async () => {
    const script = text(5000);
    const style = Buffer.concat([text(2000), Buffer.from("/* é ü ✓ */\n", "utf8")]);
    await build({ "assets/app-AbCd1234.js": script, "assets/style-AbCd1234.css": style });

    await compressAssets(outDir);

    const variants = (await listing()).filter((name) => name.endsWith(".br"));
    expect(variants).toHaveLength(2);
    const decoded = async (name: string) =>
      brotliDecompressSync(await readFile(join(outDir, "assets", name)));
    expect((await decoded("app-AbCd1234.js.br")).equals(script)).toBe(true);
    expect((await decoded("style-AbCd1234.css.br")).equals(style)).toBe(true);
  });

  it("writes the same bytes when run twice on the same files", async () => {
    const script = text(6000);
    await build({ "assets/app-AbCd1234.js": script });
    // Other settings write other bytes, and the committed variants would then differ from a build.
    const expected = brotliCompressSync(script, {
      params: {
        [constants.BROTLI_PARAM_QUALITY]: 11,
        [constants.BROTLI_PARAM_MODE]: constants.BROTLI_MODE_TEXT,
        [constants.BROTLI_PARAM_SIZE_HINT]: script.length,
      },
    });

    await compressAssets(outDir);
    const first = await readFile(join(outDir, "assets", "app-AbCd1234.js.br"));
    await compressAssets(outDir);
    const second = await readFile(join(outDir, "assets", "app-AbCd1234.js.br"));

    expect(await listing()).toEqual(["app-AbCd1234.js", "app-AbCd1234.js.br"]);
    expect(first.equals(expected)).toBe(true);
    expect(second.equals(expected)).toBe(true);
  });

  it("leaves no variant behind for a file that was removed", async () => {
    await build({ "assets/app-AbCd1234.js": text(4096), "assets/old-EfGh5678.js": text(4096) });
    await compressAssets(outDir);
    expect(await listing()).toContain("old-EfGh5678.js.br");
    await rm(join(outDir, "assets", "old-EfGh5678.js"));

    await compressAssets(outDir);

    expect(await listing()).toEqual(["app-AbCd1234.js", "app-AbCd1234.js.br"]);
  });
});
