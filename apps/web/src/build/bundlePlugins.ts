import type { Plugin } from "vite";
import { compressAssets } from "./compressAssets";

// Writes the Brotli variants once the built files are in the real `outDir` (`make web-build`,
// `make web-dist-check` and the image all pass their own), so `hub web` can serve them (AGH-615, Q8).
export function compressPlugin(): Plugin {
  return {
    name: "ah-compress-assets",
    apply: "build",
    async writeBundle(options) {
      if (options.dir) await compressAssets(options.dir);
    },
  };
}
