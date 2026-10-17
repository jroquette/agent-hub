import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";

import { expect, test } from "@playwright/test";

// `make playground-export` (docs/design/playground-export.md): renders each route it lists, from the
// exported commit's build on synthetic data, into a PNG the delivery uses as its visual baseline. It
// runs only when the export passes AH_CAPTURE; the smoke never does.
interface CaptureRoute {
  /** The PNG's path under AH_CAPTURE_DIR, without the extension (`<area>/<route slug>`). */
  file: string;
  path: string;
  /** Open the first link whose href starts with this, from `path` (a detail screen of the demo data). */
  follow?: string;
}

const routes: CaptureRoute[] = process.env.AH_CAPTURE
  ? (JSON.parse(process.env.AH_CAPTURE) as CaptureRoute[])
  : [];
const outDir = process.env.AH_CAPTURE_DIR ?? "";
// One fixed instant, so the clock-driven parts of a screen are the same in every export.
const FROZEN = new Date("2026-01-01T12:00:00Z");

test.use({ viewport: { width: 1440, height: 900 }, colorScheme: "dark" });

test.describe("playground export capture", () => {
  test.skip(routes.length === 0 || !outDir, "run by make playground-export only");

  for (const route of routes) {
    test(`captures ${route.file}`, async ({ page }) => {
      await page.clock.setFixedTime(FROZEN);
      await page.addInitScript(() => {
        window.localStorage.setItem("ah.theme", "dark");
      });
      await page.goto(route.path);
      if (route.follow) {
        const link = page.locator(`a[href^="${route.follow}"]`).first();
        await expect(link).toBeVisible();
        await link.click();
      }
      await page.waitForLoadState("networkidle");
      const file = join(outDir, `${route.file}.png`);
      mkdirSync(dirname(file), { recursive: true });
      await page.screenshot({ path: file, mask: [page.locator("time")], animations: "disabled" });
    });
  }
});
