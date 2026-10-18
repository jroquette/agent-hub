import { defineConfig, devices } from "@playwright/test";

// The smoke test runs against a `hub web` the Python e2e test starts; it passes the URL, and
// the Chromium to launch when Playwright's own download is missing (AGENT_HUB_CHROMIUM).
const executablePath = process.env.AGENT_HUB_CHROMIUM;
// The visual tests run only when tests/e2e/test_web_visual.py asks for them (AH_VISUAL): they
// need the demo data, which the smoke's hub web does not hold.
const visual = Boolean(process.env.AH_VISUAL);

export default defineConfig({
  testDir: "./e2e",
  testIgnore: visual ? [] : ["visual/**"],
  // A visual test's baseline is e2e/visual/baselines/<area>/<route>.png, the export's PNG as is.
  snapshotPathTemplate: "{testDir}/visual/baselines/{arg}{ext}",
  expect: {
    // The baselines come from the owner's machine: font anti-aliasing differs a little from one
    // machine to another (up to 0.3% of the pixels by more than a quarter of the range, measured
    // on the same commit), a layout or copy change much more.
    toHaveScreenshot: { maxDiffPixelRatio: 0.01 },
  },
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
