/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { DEV_SERVER, apiProxy } from "./src/lib/devProxy";

// The production build goes into the API package, which serves it and ships it (D26).
const OUT_DIR = "../../packages/api/src/agent_hub/api/web_dist";

export default defineConfig({
  plugins: [react()],
  // `make dev` (vite) only; the production app is served by `hub web` itself.
  server: { ...DEV_SERVER, proxy: apiProxy() },
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
});
