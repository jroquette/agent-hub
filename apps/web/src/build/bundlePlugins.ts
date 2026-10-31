import type { Plugin } from "vite";
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

// Stops the build when the entry chunk or the vendor chunk is over its size limit (AGH-614, AC-1, AC-3).
export function budgetPlugin(): Plugin {
  throw new Error("budgetPlugin is not implemented yet");
}
