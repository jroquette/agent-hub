/// <reference types="vitest/config" />
import { realpathSync } from "node:fs";
import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { DEV_SERVER, apiProxy } from "./src/lib/devProxy";

// The production build goes into the API package, which serves it and ships it (D26).
const OUT_DIR = "../../packages/api/src/agent_hub/api/web_dist";

export default defineConfig(({ command }) => ({
  plugins: [react()],
  // The checkout `make dev` serves, so a shake can preselect its workdir (O8); null in a build, so
  // web_dist holds no absolute path (AC-260.18).
  define: {
    __AH_DEV_CHECKOUT__: JSON.stringify(
      command === "serve" ? realpathSync(resolve(import.meta.dirname, "../..")) : null,
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
