import { readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { extname, join } from "node:path";
import { brotliCompressSync, constants } from "node:zlib";

// Only these shrink: fonts and images are compressed already, and `index.html` sits outside `assets/` (Q11).
const COMPRESSIBLE = new Set([".js", ".css", ".svg"]);
const MIN_BYTES = 1024;
const VARIANT = ".br";

// Writes a Brotli variant (`<name>.br`) next to each built script, style and SVG under `<outDir>/assets`,
// and returns the names it wrote (AGH-615, AC-8, AC-17). The settings are fixed (quality 11, text mode,
// the file's length as the size hint), so two builds of the same files write the same bytes. A variant
// whose source is gone is removed, so the folder never serves a stale one.
export async function compressAssets(outDir: string): Promise<string[]> {
  const assets = join(outDir, "assets");
  const names = (await readdir(assets)).sort();
  const sources = new Set(names.filter((name) => !name.endsWith(VARIANT)));
  for (const name of names) {
    if (name.endsWith(VARIANT) && !sources.has(name.slice(0, -VARIANT.length))) {
      await rm(join(assets, name), { force: true });
    }
  }
  const written: string[] = [];
  for (const name of sources) {
    if (!COMPRESSIBLE.has(extname(name))) continue;
    const path = join(assets, name);
    if (!(await stat(path)).isFile()) continue;
    const bytes = await readFile(path);
    if (bytes.length < MIN_BYTES) continue;
    const encoded = brotliCompressSync(bytes, {
      params: {
        [constants.BROTLI_PARAM_QUALITY]: 11,
        [constants.BROTLI_PARAM_MODE]: constants.BROTLI_MODE_TEXT,
        [constants.BROTLI_PARAM_SIZE_HINT]: bytes.length,
      },
    });
    await writeFile(`${path}${VARIANT}`, encoded);
    written.push(`${name}${VARIANT}`);
  }
  return written;
}
