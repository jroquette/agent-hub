import { readFile, readdir, rm, writeFile } from "node:fs/promises";
import { extname, join } from "node:path";
import { brotliCompressSync, constants } from "node:zlib";

// Only these shrink: fonts and images are compressed already, and `index.html` is not in `assets/`.
const COMPRESSIBLE = new Set([".js", ".css", ".svg"]);
const MIN_BYTES = 1024;
const VARIANT = ".br";

// Writes a Brotli variant (`<name>.br`) beside each script, style and SVG of 1 KB or more under
// `<outDir>/assets`, and returns the names it wrote. The settings never change, so the same files
// and the same Brotli encoder (the one Node bundles) always give the same bytes. A variant whose
// file is gone is removed, so the folder never holds a stale one.
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
