import { appendFileSync } from "node:fs";

import { test, type Page, type Request } from "@playwright/test";

// `make perf` (scripts/perf/pages.py): opens each page of PERF_PAGES PERF_RUNS times and appends
// one JSON line per run, {path, run, ready_ms, api_calls, dom_nodes, api_kb}, to PERF_PAGES_OUT.
// Without PERF_PAGES it registers no test, so the smoke's count stays the same. `dom_nodes` (every
// element on the page once it is ready) and `api_kb` (the response bodies of the non-stream
// /api/v1/ requests that finished before the page was ready, in KB of 1,000 bytes) are reported
// fields only: no budget reads them.
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
const BYTES_PER_KB = 1000;

type Sizes = Awaited<ReturnType<Request["sizes"]>>;

const apiPath = (request: Request): string | null => {
  const { pathname } = new URL(request.url());
  return pathname.startsWith("/api/v1/") ? pathname : null;
};
// The SSE streams never end: they are counted, never awaited.
const isStream = (request: Request, pathname: string): boolean =>
  request.resourceType() === "eventsource" || pathname.endsWith("/stream");

/** Opens `path` and returns when it is ready (ms from navigation start), its API calls, and the
 * sizes of the API answers that finished before then (still to be awaited). */
async function measure(
  page: Page,
  path: string,
): Promise<{ readyMs: number; apiCalls: number; sizes: Promise<Sizes>[] }> {
  const inFlight = new Set<Request>();
  // Kept in this call, not on the page: an earlier measure's listeners stay on the page.
  const sizes: Promise<Sizes>[] = [];
  let ready = false;
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
  page.on("requestfinished", (request) => {
    // `sizes()` answers asynchronously: its promise is kept now, else the size is lost.
    if (!ready && inFlight.has(request)) sizes.push(request.sizes());
    settle(request);
  });
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
  ready = true;
  return { readyMs: Math.max(loaded, lastEnd) - start, apiCalls, sizes };
}

/** The response bodies of `sizes`, summed, in KB of 1,000 bytes. */
async function kilobytes(sizes: Promise<Sizes>[]): Promise<number> {
  const answered = await Promise.all(sizes);
  return answered.reduce((total, size) => total + size.responseBodySize, 0) / BYTES_PER_KB;
}

test.describe("make perf pages", () => {
  // Playwright's 30 s default would end a test before READY_LIMIT_MS does.
  test.setTimeout(READY_LIMIT_MS + 30_000);
  // Every page is opened as the owner opens hub web: once through the token URL (the cookie).
  // It waits for the same quiet period as a measured page, so the measured page does not share
  // the server with the first page's requests.
  test.beforeEach(async ({ page }) => {
    await measure(page, `/?token=${process.env.PERF_TOKEN ?? ""}`);
  });

  for (const path of pages) {
    for (let run = 0; run < runs; run += 1) {
      test(`measures ${path} run ${String(run)}`, async ({ page }) => {
        const { readyMs, apiCalls, sizes } = await measure(page, path);
        const domNodes = await page.evaluate(() => document.querySelectorAll("*").length);
        const apiKb = await kilobytes(sizes);
        const line = {
          path,
          run,
          ready_ms: readyMs,
          api_calls: apiCalls,
          dom_nodes: domNodes,
          api_kb: apiKb,
        };
        appendFileSync(out, `${JSON.stringify(line)}\n`, "utf-8");
      });
    }
  }
});
