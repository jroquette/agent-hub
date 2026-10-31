/// <reference types="vitest/config" />
import { realpathSync } from "node:fs";
import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VENDOR_CHUNK_NAME } from "./src/build/bundleBudget";
import { budgetPlugin, compressPlugin } from "./src/build/bundlePlugins";
import { DEV_SERVER, apiProxy } from "./src/lib/devProxy";

// The production build goes into the API package, which serves it and ships it (D26).
const OUT_DIR = "../../packages/api/src/agent_hub/api/web_dist";

export default defineConfig(({ command, mode }) => ({
  plugins: [react(), budgetPlugin(), compressPlugin()],
  // The checkout `make dev` serves, so a shake can preselect its workdir (O8); null in a build, so
  // web_dist holds no absolute path (AC-260.18), and under Vitest (mode "test"), so no test reads
  // where the checkout lives (tests that need one mock servedCheckout).
  define: {
    __AH_DEV_CHECKOUT__: JSON.stringify(
      command === "serve" && mode !== "test"
        ? realpathSync(resolve(import.meta.dirname, "../.."))
        : null,
    ),
  },
  // `make dev` and `make live` (vite) only; the production app is served by `hub web` itself.
  // `make live` sets both targets (devProxy.ts); unset, everything goes to 7420 as before.
  server: {
    ...DEV_SERVER,
    proxy: apiProxy(process.env.AH_API_TARGET, process.env.AH_SESSIONS_TARGET),
  },
  build: {
    outDir: OUT_DIR,
    emptyOutDir: true,
    sourcemap: false,
    // `.vite/manifest.json` names the chunk file of the entry and of each module loaded on demand;
    // the route chunk tests read it.
    manifest: true,
    // One stylesheet, which index.html links: screens use classes from each other's stylesheets,
    // so a stylesheet per route chunk would leave a deep-linked screen unstyled, and a page's look
    // would hang on the screens opened before it.
    cssCodeSplit: false,
    rolldownOptions: {
      output: {
        codeSplitting: {
          // The libraries the screens share go into one chunk, checked against the vendor limit.
          groups: [
            {
              name: VENDOR_CHUNK_NAME,
              test: /node_modules[\\/](react|react-dom|scheduler|react-router|@tanstack|openapi-fetch)[\\/]/,
            },
          ],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/testing/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.test.{ts,tsx}",
        "src/api/schema.d.ts",
        "src/main.tsx",
        "src/testing/**",
        "scripts/**",
        "e2e/**",
      ],
      thresholds: { lines: 80, branches: 80 },
    },
  },
}));
