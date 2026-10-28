import { appendFileSync } from "node:fs";

import { test, type Page, type Request } from "@playwright/test";

// `make perf` (scripts/perf/pages.py): opens each page of PERF_PAGES PERF_RUNS times and appends
// one JSON line per run, {path, run, ready_ms, api_calls}, to PERF_PAGES_OUT. Without PERF_PAGES
// it registers no test, so the smoke's count stays the same.
const pages: string[] = process.env.PERF_PAGES
  ? (JSON.parse(process.env.PERF_PAGES) as string[])
  : [];
const runs = Number(process.env.PERF_RUNS ?? "1");
const out = process.env.PERF_PAGES_OUT ?? "";
// Ready = no /api/v1/ request in flight for this long after `load`.
const QUIET_MS = 500;
const POLL_MS = 25;
// Generous, so a slow page is reported as over its budget instead of failing the suite.
const READY_LIMIT_MS = 60_000;

const apiPath = (request: Request): string | null => {
  const { pathname } = new URL(request.url());
  return pathname.startsWith("/api/v1/") ? pathname : null;
};
// The SSE streams never end: they are counted, never awaited.
const isStream = (request: Request, pathname: string): boolean =>
  request.resourceType() === "eventsource" || pathname.endsWith("/stream");

/** Opens `path` and returns when it is ready (ms from navigation start) and its API calls. */
async function measure(page: Page, path: string): Promise<{ readyMs: number; apiCalls: number }> {
  const inFlight = new Set<Request>();
  let apiCalls = 0;
  let lastEnd = 0;
  page.on("request", (request) => {
    const pathname = apiPath(request);
    if (pathname === null) return;
    apiCalls += 1;
    if (!isStream(request, pathname)) inFlight.add(request);
  });
  const settle = (request: Request) => {
    if (inFlight.delete(request)) lastEnd = performance.now();
  };
  page.on("requestfinished", settle);
  page.on("requestfailed", settle);

  const start = performance.now();
  await page.goto(path, { waitUntil: "load" });
  const loaded = performance.now();
  for (;;) {
    const now = performance.now();
    if (inFlight.size === 0 && now - Math.max(loaded, lastEnd) >= QUIET_MS) break;
    if (now - start > READY_LIMIT_MS) {
      throw new Error(`${path}: not ready in ${String(READY_LIMIT_MS)} ms`);
    }
    await page.waitForTimeout(POLL_MS);
  }
  return { readyMs: Math.max(loaded, lastEnd) - start, apiCalls };
}

test.describe("make perf pages", () => {
  // Playwright's 30 s default would end a test before READY_LIMIT_MS does.
  test.setTimeout(READY_LIMIT_MS + 30_000);
  // Every page is opened as the owner opens hub web: once through the token URL (the cookie).
  test.beforeEach(async ({ page }) => {
    await page.goto(`/?token=${process.env.PERF_TOKEN ?? ""}`);
  });

  for (const path of pages) {
    for (let run = 0; run < runs; run += 1) {
      test(`measures ${path} run ${String(run)}`, async ({ page }) => {
        const { readyMs, apiCalls } = await measure(page, path);
        const line = { path, run, ready_ms: readyMs, api_calls: apiCalls };
        appendFileSync(out, `${JSON.stringify(line)}\n`, "utf-8");
      });
    }
  }
});
