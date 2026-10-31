import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page, type Request } from "@playwright/test";
import type { Manifest } from "vite";

import { env, expectAccessible, watch } from "./pageChecks";

// Each routed screen loads on demand, from its own chunk of the committed build that hub web
// serves. Run alone by test_loads_route_chunks_on_demand_when_built_app_served: every title starts
// with "Route chunks".

// The committed build hub web serves, and its Vite manifest: the chunk of each module, and the
// chunks each one imports.
const WEB_DIST = join(import.meta.dirname, "../../../packages/api/src/agent_hub/api/web_dist");
const MANIFEST = join(WEB_DIST, ".vite", "manifest.json");
// The screen module the /sessions route loads (routes.tsx).
const SESSIONS_SCREEN = "src/screens/sessions-list/index.tsx";
const LIVE_SESSION = env("SMOKE_LIVE_SESSION");
// As smoke.spec.ts: the live session is named by its ticket, DEM-7 (AGH-380).
const LIVE_HEADING = /^DEM-7: (export-button|Add the export route)$/;

// The shell's nav in its order (AC-521.4.1, Sidebar.test.tsx), each link with the level-1
// heading of the page it opens with no project in scope (App.test.tsx's routes, the pickers').
const NAV_DESTINATIONS: { link: RegExp; heading: string }[] = [
  { link: /^Portfolio/, heading: "Portfolio" },
  { link: /^Features/, heading: "Features" },
  { link: /^Tickets/, heading: "Tickets" },
  { link: /^Scenarios/, heading: "Scenarios" },
  { link: /^Sessions/, heading: "Sessions" },
  { link: /^Workflow runs/, heading: "Workflow runs" },
  { link: /^Environments/, heading: "Environments" },
  { link: /^Brain/, heading: "Brain" },
  { link: /^Learnings/, heading: "Knowledge" },
  { link: /^Toolkit/, heading: "Toolkit" },
  { link: /^Health/, heading: "Health" },
  { link: /^Hub config/, heading: "Hub configuration" },
  { link: /^Settings/, heading: "Settings" },
];

// Deep links: a Brain note, a session and a settings section of the smoke's scenario.
const DEEP_LINKS: { path: string; heading: string | RegExp; shows: string }[] = [
  {
    path: "/projects/demo/brain/now.md",
    heading: "Brain",
    shows: "Ship the CSV export button (DEM-7).",
  },
  { path: `/sessions/${LIVE_SESSION}`, heading: LIVE_HEADING, shows: "Guard blocked" },
  { path: "/settings/appearance", heading: "Settings", shows: "Shake to start a session" },
];

/** The committed build's manifest: a build without one has no route chunk to check. */
function readManifest(): Manifest {
  expect(existsSync(MANIFEST), `${MANIFEST} is missing: the build has no route chunks`).toBe(true);
  return JSON.parse(readFileSync(MANIFEST, "utf-8")) as Manifest;
}

/** The file of `key`'s own route chunk: the chunk the manifest marks as its dynamic entry. */
function routeFile(manifest: Manifest, key: string): string {
  const chunk = manifest[key];
  expect(chunk?.isDynamicEntry, `${key} has no route chunk of its own`).toBe(true);
  return chunk?.file ?? "";
}

/** The files `key`'s chunk needs before it runs: its own and every chunk it imports statically. */
function staticFiles(manifest: Manifest, key: string): Set<string> {
  const files = new Set<string>();
  const pending = [key];
  for (let next = pending.pop(); next !== undefined; next = pending.pop()) {
    const chunk = manifest[next];
    if (chunk === undefined || files.has(chunk.file)) continue;
    files.add(chunk.file);
    pending.push(...(chunk.imports ?? []));
  }
  return files;
}

/**
 * Waits until no transition or finite animation runs, so axe reads each colour at rest: a button
 * whose background is still fading (`.ah-btn`'s transition) has no stable contrast.
 */
async function settle(page: Page): Promise<void> {
  await page.waitForFunction(() =>
    document
      .getAnimations()
      .every(
        (animation) =>
          animation.playState !== "running" ||
          animation.effect?.getComputedTiming().endTime === Infinity,
      ),
  );
}

/** A request's file under the build's root (`assets/<name>`), as the manifest names it. */
const builtFile = (request: Request): string => new URL(request.url()).pathname.slice(1);

// The token visit (AGH-165, P6) as a request, not a page: hub web answers it with the session
// cookie and a redirect, and the browser's cache stays empty for the page each test opens.
test.beforeEach(async ({ page }) => {
  const exchange = await page.request.get(`/?token=${env("SMOKE_TOKEN")}`, { maxRedirects: 0 });

  expect(exchange.status()).toBe(303);
  const cookies = await page.context().cookies();
  expect(cookies.some((cookie) => cookie.name.startsWith("agent_hub_"))).toBe(true);
});

test("Route chunks: a first visit to /sessions requests only the entry, vendor, shared and Sessions chunks", async ({
  page,
}) => {
  const manifest = readManifest();
  const entries = Object.keys(manifest).filter((key) => manifest[key]?.isEntry === true);
  expect(entries).toHaveLength(1);
  const sessionsFile = routeFile(manifest, SESSIONS_SCREEN);
  // The entry with the vendor and shared chunks it imports, and the same for /sessions.
  const allowed = new Set([
    ...staticFiles(manifest, entries[0] ?? ""),
    ...staticFiles(manifest, SESSIONS_SCREEN),
  ]);
  const otherRoutes = new Set(
    Object.entries(manifest)
      .filter(([key, chunk]) => key.startsWith("src/screens/") && chunk.isDynamicEntry === true)
      .filter(([key]) => key !== SESSIONS_SCREEN)
      .map(([, chunk]) => chunk.file),
  );
  expect(otherRoutes.size).toBeGreaterThan(0);
  const assets: Request[] = [];
  page.on("request", (request) => {
    if (/^assets\/.+\.(js|css)$/.test(builtFile(request))) assets.push(request);
  });

  await page.goto("/sessions");
  await expect(
    page.getByRole("heading", { level: 1, name: "Sessions", exact: true }),
  ).toBeVisible();

  // The request log: each script and style with its bytes on the wire (headers and body).
  const log: string[] = [];
  let total = 0;
  for (const request of assets) {
    const sizes = await request.sizes();
    const bytes = sizes.responseHeadersSize + sizes.responseBodySize;
    total += bytes;
    log.push(`  ${builtFile(request)} ${String(bytes)} B`);
  }
  const files = `${String(assets.length)} scripts and styles`;
  console.log(`First /sessions visit: ${files}, ${String(total)} B on the wire\n${log.join("\n")}`);
  const scripts = assets.map(builtFile).filter((file) => file.endsWith(".js"));
  expect(scripts).toContain(sessionsFile);
  expect(scripts.filter((file) => !allowed.has(file))).toEqual([]);
  expect(scripts.filter((file) => otherRoutes.has(file))).toEqual([]);
});

test("Route chunks: every nav destination opens by in-app navigation, with its heading and no error", async ({
  page,
  baseURL,
}) => {
  // Thirteen pages, each with an axe scan: more than the default 30 s.
  test.setTimeout(120_000);
  const problems = watch(page, baseURL ?? "");
  await page.goto("/");
  await expect(
    page.getByRole("heading", { level: 1, name: "Portfolio", exact: true }),
  ).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link")).toHaveCount(NAV_DESTINATIONS.length);
  // A full page load would drop this mark, so it shows every step below stayed in the app.
  await page.evaluate(() => Object.assign(window, { routeChunksTour: true }));

  for (const { link, heading } of [...NAV_DESTINATIONS.slice(1), ...NAV_DESTINATIONS.slice(0, 1)]) {
    await nav.getByRole("link", { name: link }).click();
    await expect(page.getByRole("heading", { level: 1, name: heading, exact: true })).toBeVisible();
    await settle(page);
    await expectAccessible(page);
  }

  expect(await page.evaluate(() => "routeChunksTour" in window)).toBe(true);
  expect(problems).toEqual([]);
});

test("Route chunks: a Brain note, a session and a settings section open from a full page load", async ({
  page,
  baseURL,
}) => {
  // Three pages, each with an axe scan.
  test.setTimeout(60_000);
  const problems = watch(page, baseURL ?? "");

  for (const { path, heading, shows } of DEEP_LINKS) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading, exact: true })).toBeVisible();
    await expect(page.getByText(shows).first()).toBeVisible();
    await expect(page).toHaveURL((url) => url.pathname === path);
    await settle(page);
    await expectAccessible(page);
  }

  expect(problems).toEqual([]);
});

test("Route chunks: a failed chunk shows This page could not load in the shell, and other routes still open", async ({
  page,
}) => {
  const sessionsFile = routeFile(readManifest(), SESSIONS_SCREEN);
  const aborted: string[] = [];
  await page.route(
    (url) => url.pathname === `/${sessionsFile}`,
    async (route) => {
      aborted.push(builtFile(route.request()));
      await route.abort();
    },
  );
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { level: 1, name: "Portfolio", exact: true }),
  ).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Main" });

  await nav.getByRole("link", { name: /^Sessions/ }).click();

  const main = page.locator("main#main");
  await expect(
    main.getByRole("heading", { level: 1, name: "This page could not load" }),
  ).toBeVisible();
  expect(aborted.length).toBeGreaterThan(0);
  await expect(main.getByRole("button", { name: "Reload page" })).toBeVisible();
  await expect(main.getByRole("link", { name: "Go to Portfolio" })).toBeVisible();
  await expect(main.getByText(`Requested: /sessions · file ${sessionsFile}`)).toBeVisible();
  await settle(page);
  await expectAccessible(page);
  await expect(nav).toBeVisible();
  await nav.getByRole("link", { name: /^Features/ }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Features", exact: true }),
  ).toBeVisible();
  await expect(main.getByRole("heading", { name: "This page could not load" })).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});
