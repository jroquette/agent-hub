import { defineConfig, devices } from "@playwright/test";

// The smoke test runs against a `hub web` the Python e2e test starts; it passes the URL.
export default defineConfig({
  testDir: "./e2e",
  forbidOnly: Boolean(process.env.CI),
  reporter: "line",
  use: {
    baseURL: process.env.AGENT_HUB_WEB_URL ?? "http://127.0.0.1:7420",
    trace: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
