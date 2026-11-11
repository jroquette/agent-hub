import { fileURLToPath } from "node:url";

import type { Page } from "@playwright/test";

import { screen } from "./screen";

// The demo feature's page: golden path, Waiting on you banner, tabs (AC-PG-31.*).
screen("feature-detail", "feature", "/features", "/features/");
// The ticket flow full window: cards, trunks and the zoom toolbar on the canvas (AC-521.10.5–10).
screen("feature-detail", "tickets-flow", "/features/demo/export-button?doc=tickets&flow=full");

// A large flow (AGH-817): the demo's ledger-sync feature, 44 tickets with 16 done and 1 canceled, so
// it still shows 27 once those are folded and stays large. The demo has no Linear key, so its
// tickets route is served as hub web answers once Linear is read (fixtures/ledger-sync-tickets.json,
// written by scripts/visual_fixtures.py).
const LARGE = "/features/demo/ledger-sync?doc=tickets&flow=full";
const FIXTURE = fileURLToPath(new URL("./fixtures/ledger-sync-tickets.json", import.meta.url));

async function serveLinear(page: Page): Promise<void> {
  await page.route("**/api/v1/features/demo/ledger-sync/tickets", (route) =>
    route.fulfill({ path: FIXTURE, contentType: "application/json" }),
  );
}

// At rest: compact cards, done tickets folded ("Show 6 done"), only open next-group lines (AC-817.1, .7).
screen("feature-detail", "large-flow", LARGE, { before: serveLinear });
// A card in view pointed at: AGH-212's line to AGH-229, which skips two groups, lights up; no card
// moves (AC-817.2).
screen("feature-detail", "large-flow-focus", LARGE, {
  before: serveLinear,
  act: async (page) => {
    await page.locator("#ticket-AGH-212").hover();
  },
});
// Show all: the done tickets back in their groups, the lines at rest unchanged (AC-817.5).
screen("feature-detail", "large-flow-all", LARGE, {
  before: serveLinear,
  act: async (page) => {
    await page.getByRole("button", { name: "Show all" }).click();
  },
});
// Full cards: every fact of each card, and "Blocks N" (AC-817.4, .5).
screen("feature-detail", "large-flow-full", LARGE, {
  before: serveLinear,
  act: async (page) => {
    await page
      .getByRole("group", { name: "Cards" })
      .getByRole("button", { name: "Full", exact: true })
      .click();
  },
});
