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

// Stops the build when the entry chunk or the vendor chunk is over its size limit. It checks the
// files once they are written: Vite empties the output folder before the build renders, so a check
// that stopped the build any sooner would leave the committed web_dist empty, and hub web run from
// the checkout with no app. Listed before compressPlugin, it also spares a failed build the Brotli
// pass.
export function budgetPlugin(): Plugin {
  return {
    name: "ah-bundle-budget",
    apply: "build",
    writeBundle(_options, bundle) {
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
  };
}
