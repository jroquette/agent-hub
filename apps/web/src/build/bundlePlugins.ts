import { Buffer } from "node:buffer";
import type { Plugin } from "vite";
import { ENTRY_LIMIT_BYTES, VENDOR_LIMIT_BYTES, checkBundle } from "./bundleBudget";
import { compressAssets } from "./compressAssets";

// Writes the Brotli variants once the built files are in the real output folder: `make web-build`,
// `make web-dist-check` and the image each pass their own, and `hub web` serves the variants.
export function compressPlugin(): Plugin {
  return {
    name: "ah-compress-assets",
    apply: "build",
    async writeBundle({ dir }) {
      // Skipping would let the build pass with no variant, and `hub web` would then send every
      // file uncompressed.
      if (dir === undefined) {
        this.error("Vite named no output folder, so no Brotli variant was written.");
      }
      await compressAssets(dir);
    },
  };
}

// Stops the build when the entry chunk or the vendor chunk is over its size limit.
export function budgetPlugin(): Plugin {
  return {
    name: "ah-bundle-budget",
    apply: "build",
    generateBundle: {
      // Last, because Vite's own generateBundle hooks still change chunk code (the lists of files
      // to preload), so the sizes checked are those of the files written.
      order: "post",
      handler(_options, bundle) {
        const chunks = Object.values(bundle)
          .filter((output) => output.type === "chunk")
          .map((chunk) => ({
            fileName: chunk.fileName,
            name: chunk.name,
            isEntry: chunk.isEntry,
            size: Buffer.byteLength(chunk.code),
          }));
        const check = checkBundle(chunks, { entry: ENTRY_LIMIT_BYTES, vendor: VENDOR_LIMIT_BYTES });
        if (!check.ok) {
          this.error(check.lines.join("\n"));
        }
        for (const line of check.lines) {
          this.info(line);
        }
      },
    },
  };
}
