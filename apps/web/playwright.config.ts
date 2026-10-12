import { defineConfig, devices } from "@playwright/test";

// The smoke test runs against a `hub web` the Python e2e test starts; it passes the URL, and
// the Chromium to launch when Playwright's own download is missing (AGENT_HUB_CHROMIUM).
const executablePath = process.env.AGENT_HUB_CHROMIUM;

export default defineConfig({
  testDir: "./e2e",
  forbidOnly: Boolean(process.env.CI),
  reporter: "line",
  workers: 1,
  use: {
    baseURL: process.env.AGENT_HUB_WEB_URL ?? "http://127.0.0.1:7420",
    trace: "off",
    ...(executablePath ? { launchOptions: { executablePath } } : {}),
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
