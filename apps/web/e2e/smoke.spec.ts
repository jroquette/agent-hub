import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// Ids of the synthetic scenario tests/e2e/test_web_smoke.py stored (AC-200.63).
const env = (name: string): string => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set: run the smoke through test_web_smoke.py`);
  return value;
};
const LIVE_SESSION = env("SMOKE_LIVE_SESSION");
const LONG_SESSION = env("SMOKE_LONG_SESSION");
const RUN = env("SMOKE_RUN");
// Session detail with 5,000 events is complete in under 2 s (NFR "Performance").
const LONG_SESSION_BUDGET_MS = 2_000;

/** Fails the test on any console error, page error, or request to another host (AC-200.56). */
function watch(page: Page, baseURL: string): string[] {
  const problems: string[] = [];
  const origin = new URL(baseURL).origin;
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => problems.push(`page error: ${error.message}`));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.protocol !== "data:" && url.origin !== origin) {
      problems.push(`request to another host: ${request.url()}`);
    }
  });
  return problems;
}

/** AC-200.57: no axe violation of impact serious or critical. */
async function expectAccessible(page: Page): Promise<void> {
  // @axe-core/playwright types a slightly older Page; the runtime object is the same.
  const options = { page } as unknown as ConstructorParameters<typeof AxeBuilder>[0];
  const results = await new AxeBuilder(options).analyze();
  const blocking = results.violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => `${violation.id}: ${violation.help}`);
  expect(blocking).toEqual([]);
}

interface SmokePage {
  name: string;
  path: string;
  heading: string;
  shows: string | RegExp;
}

// The app shows ids in their short form: hyphens dropped, first 8 characters.
const short = (id: string) => id.replace(/-/g, "").slice(0, 8);

const PAGES: SmokePage[] = [
  { name: "Portfolio", path: "/", heading: "Portfolio", shows: /Failed runs · 7 d/ },
  { name: "Live sessions", path: "/live", heading: "Live sessions", shows: /Waiting · Guard ask/ },
  { name: "Sessions", path: "/sessions", heading: "Sessions", shows: "Showing all 3" },
  {
    name: "Session detail",
    path: `/sessions/${LIVE_SESSION}`,
    heading: "Session detail",
    shows: "Denied by guard",
  },
  { name: "Workflow runs", path: "/runs", heading: "Workflow runs", shows: short(RUN) },
  {
    name: "Run detail",
    path: `/runs/${RUN}`,
    heading: `Run ${short(RUN)}`,
    shows: /Failed at Verifying · attempt 2 of 2/,
  },
  { name: "Approvals", path: "/approvals", heading: "Approvals", shows: "How to decide" },
  { name: "Features", path: "/features", heading: "Features", shows: "export-button" },
  { name: "Health", path: "/health", heading: "Health", shows: /Checked on request/ },
];

for (const smoke of PAGES) {
  test(`${smoke.name} loads without console error or axe violation`, async ({ page, baseURL }) => {
    const problems = watch(page, baseURL ?? "");
    await page.goto(smoke.path);

    await expect(page.getByRole("heading", { level: 1, name: smoke.heading })).toBeAttached();
    await expect(page.getByText(smoke.shows).first()).toBeVisible();
    await expectAccessible(page);
    expect(problems).toEqual([]);
  });
}

test("Session detail of a 5,000-event session is complete in under 2 s", async ({
  page,
  baseURL,
}) => {
  const problems = watch(page, baseURL ?? "");
  const started = Date.now();
  await page.goto(`/sessions/${LONG_SESSION}`);

  await expect(page.getByText(/Long session · 5,000 events/)).toBeVisible();
  const elapsed = Date.now() - started;
  console.log(`Session detail with 5,000 events complete in ${String(elapsed)} ms`);
  expect(elapsed).toBeLessThan(LONG_SESSION_BUDGET_MS);
  expect(problems).toEqual([]);
});
