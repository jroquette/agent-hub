import { expect, test, type Page } from "@playwright/test";

// The visual tests (tests/e2e/test_web_visual.py, AGH-314): each screen the owner validated in the
// playground, rendered on the demo data (seed_demo) and compared with its baseline in baselines/,
// the PNG the playground export captured. Same viewport, theme, clock and masks as the capture
// (capture.spec.ts), so a baseline can be re-exported as is.

// hub web's address with its launch token: the agent-session routes need the cookie it is traded for.
const login = process.env.AH_VISUAL_LOGIN;
// The capture's fixed instant, so the clock-driven parts of a screen match their baseline.
const FROZEN = new Date("2026-01-01T12:00:00Z");

/** Opens `path` as the capture did: frozen clock, dark theme, logged in, then `follow`'s first link. */
async function open(page: Page, path: string, follow?: string): Promise<void> {
  await page.clock.setFixedTime(FROZEN);
  await page.addInitScript(() => {
    window.localStorage.setItem("ah.theme", "dark");
  });
  if (login) {
    // The 303 sets the cookie; it is the loopback's, so the preview's proxied calls carry it.
    await page.request.get(login, { maxRedirects: 0 });
  }
  await page.goto(path);
  if (follow) {
    const link = page.locator(`a[href^="${follow}"]`).first();
    await expect(link).toBeVisible();
    await link.click();
  }
  await page.waitForLoadState("networkidle");
}

/** What a visual test checks beyond its baseline. */
export interface ScreenOptions {
  /** After opening, follow the first link whose href starts with this. */
  follow?: string;
  /**
   * Only the main area scrolls (AC-PG-7.1): the document is no taller than the viewport-high
   * shell. jsdom has no layout, so this is only checked here.
   */
  fitsViewport?: boolean;
  /** After opening, what to do before the screenshot (open a step, switch a view). */
  act?: (page: Page) => Promise<void>;
}

const VIEWPORT = { width: 1440, height: 900 };

/**
 * One visual test: the screen at `path` (then `follow`'s first link) matches
 * `baselines/<area>/<route>.png`. Relative times (`<time>`) are masked, as in the capture.
 * The last argument is `follow` as a string, or the options.
 */
export function screen(
  area: string,
  route: string,
  path: string,
  followOrOptions?: string | ScreenOptions,
): void {
  const options: ScreenOptions =
    typeof followOrOptions === "string" ? { follow: followOrOptions } : (followOrOptions ?? {});
  // In its own block: a test.use at this module's top level would reach only the first spec
  // file that imports it.
  test.describe(area, () => {
    test.use({ viewport: VIEWPORT, colorScheme: "dark" });

    test(`${area}/${route} matches its baseline`, async ({ page }) => {
      await open(page, path, options.follow);
      if (options.act) {
        await options.act(page);
        await page.waitForLoadState("networkidle");
      }
      if (options.fitsViewport) {
        expect(
          await page.evaluate(
            () => (document.scrollingElement ?? document.documentElement).scrollHeight,
          ),
        ).toBeLessThanOrEqual(VIEWPORT.height);
      }
      await expect(page).toHaveScreenshot([area, `${route}.png`], {
        mask: [page.locator("time")],
        animations: "disabled",
      });
    });
  });
}
