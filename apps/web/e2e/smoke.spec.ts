import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// Ids of the synthetic scenario tests/e2e/test_web_smoke.py stored (AC-200.63, AC-201.41).
const env = (name: string): string => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set: run the smoke through test_web_smoke.py`);
  return value;
};
const LIVE_SESSION = env("SMOKE_LIVE_SESSION");
const STUCK_SESSION = env("SMOKE_STUCK_SESSION");
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
    .map((violation) => {
      const where = violation.nodes.map((node) => node.target.join(" ")).join(", ");
      return `${violation.id}: ${violation.help} (${where})`;
    });
  expect(blocking).toEqual([]);
}

// Every page is opened as the owner opens hub web: once through the printed token URL, so the
// session cookie is set (AGH-165, P6). Without it the Sessions screen's agent-session reads answer
// 401 (it then says to open that link), which the browser logs as failed loads.
test.beforeEach(async ({ page }) => {
  await page.goto(`/?token=${env("SMOKE_TOKEN")}`);
});

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
  { name: "Sessions", path: "/sessions", heading: "Sessions", shows: "Showing all 4" },
  {
    name: "Session detail",
    path: `/sessions/${LIVE_SESSION}`,
    heading: "DEM-7 · /feature",
    shows: "Guard blocked",
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

// The control-plane clarity screens (AC-201.41). The texts below are the scenario's, written by
// tests/e2e/test_web_smoke.py: the live session is DEM-7's /feature, the idle one failed `make test`.
const NOTE_TITLE = "Rerun a flaky test once before calling it a failure";

/** Loads `path`, then runs `check`; no console error, other host or axe violation on the way. */
async function visit(
  page: Page,
  baseURL: string | undefined,
  path: string,
  check: () => Promise<void>,
): Promise<void> {
  const problems = watch(page, baseURL ?? "");
  await page.goto(path);
  await check();
  await expectAccessible(page);
  expect(problems).toEqual([]);
}

test("Live shows a red edge only on the session that needs you, with its reason", async ({
  page,
  baseURL,
}) => {
  await visit(page, baseURL, "/live", async () => {
    const tiles = page.locator("article.ah-tile");
    const live = tiles.filter({ hasText: "DEM-7" });
    await expect(live).toHaveCount(1);
    await expect(live).not.toHaveAttribute("data-trouble", "true");
    await expect(live.getByText(/handled by the agent/)).toBeVisible();
    const stuck = tiles.filter({ hasText: "make test" });
    await expect(stuck).toHaveAttribute("data-trouble", "true");
    await expect(stuck.getByText(/Needs you/)).toBeVisible();
  });
});

test("Session detail names the actors, says what they did and what went wrong", async ({
  page,
  baseURL,
}) => {
  await visit(page, baseURL, `/sessions/${LIVE_SESSION}`, async () => {
    await expect(page.getByRole("heading", { level: 1, name: "DEM-7 · /feature" })).toBeVisible();
    const timeline = page.getByRole("region", { name: "Session timeline" });
    await expect(timeline.getByText("Ran skill /feature").first()).toBeVisible();
    await expect(
      timeline.getByText(/Started subagent Explore: Find the export code/),
    ).toBeVisible();
    await expect(timeline.getByTitle("Main agent").first()).toBeAttached();
    await expect(timeline.getByTitle(/Explore/).first()).toBeAttached();
    const panel = page.getByRole("region", { name: "What went wrong" });
    await expect(panel.getByText(/2 problems/).first()).toBeVisible();
    await expect(panel.getByText("Handled by the agent").first()).toBeVisible();
    await expect(panel.getByText(/test_csv_header/).first()).toBeVisible();
  });
});

test("Session detail of the idle session shows the problem that needs you", async ({
  page,
  baseURL,
}) => {
  await visit(page, baseURL, `/sessions/${STUCK_SESSION}`, async () => {
    const panel = page.getByRole("region", { name: "What went wrong" });
    await expect(panel.getByText("Needs you").first()).toBeVisible();
    await expect(panel.getByText(/expected 3 rows, got 2/).first()).toBeVisible();
  });
});

test("Knowledge opens a proposal, shows its note and accepts it into a pull request", async ({
  page,
  baseURL,
}) => {
  await visit(page, baseURL, "/knowledge/learnings", async () => {
    await page.getByText(NOTE_TITLE).first().click();
    const proposal = page.getByRole("region", { name: "Proposal" });
    await expect(proposal.getByText(/failed once on a slow runner/)).toBeVisible();
    await proposal.getByRole("button", { name: "Accept" }).click();
    const dialog = page.getByRole("dialog", { name: "Accept this learning?" });
    await expect(dialog.getByText("acme/demo-hub").first()).toBeVisible();
    await dialog.getByRole("button", { name: "Open pull request" }).click();
    await expect(page.getByText("Pull request opened")).toBeVisible({ timeout: 30_000 });
    await expect(
      page.getByRole("link", { name: /github\.com\/acme\/demo-hub\/pull\/1/ }).first(),
    ).toBeVisible();
  });
});

test("Feature detail renders its Spec and Plan tabs", async ({ page, baseURL }) => {
  await visit(page, baseURL, "/features/demo/export-button", async () => {
    await expect(page.getByRole("heading", { level: 1, name: "export-button" })).toBeVisible();
    await page.getByRole("tab", { name: "Spec" }).click();
    await expect(page.getByRole("heading", { name: "Export button" })).toBeVisible();
    await page.getByRole("tab", { name: "Plan" }).click();
    await expect(page.getByText("Add the export route.")).toBeVisible();
  });
});

test("Brain shows the tree and a note, and follows an in-app link", async ({ page, baseURL }) => {
  await visit(page, baseURL, "/projects/demo/brain/index.md", async () => {
    await expect(page.getByRole("heading", { level: 1, name: "Brain", exact: true })).toBeVisible();
    const tree = page.getByRole("navigation", { name: "Brain notes" });
    await expect(tree.getByText("now.md")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Demo brain" })).toBeVisible();
    await page.getByRole("link", { name: "what we focus on now" }).click();
    await expect(page).toHaveURL(/\/projects\/demo\/brain\/now\.md$/);
    await expect(page.getByText("Ship the CSV export button (DEM-7).")).toBeVisible();
  });
});

// AGH-136 (AC-136.35, E4): `hub web` runs without LINEAR_API_KEY, so the Tickets tab shows the
// plan's tickets (T1 is DEM-7; T2, not created yet, waits on it), the planning view and the
// "not connected" notice. Run alone by test_shows_plan_notice_when_feature_tickets_opened.
test("Feature detail Tickets tab shows the plan's tickets, planning and the not-connected notice", async ({
  page,
  baseURL,
}) => {
  await visit(page, baseURL, `/features/demo/export-button`, async () => {
    await expect(page.getByRole("heading", { level: 1, name: "export-button" })).toBeVisible();
    const answered = page.waitForResponse((response) =>
      response.url().endsWith("/api/v1/features/demo/export-button/tickets"),
    );
    await page.getByRole("tab", { name: /Tickets/ }).click();
    const response = await answered;
    expect(response.status()).toBe(200);
    expect(response.headers()["content-security-policy"]).toContain("connect-src 'self'");
    await expect(page).toHaveURL(/[?&]doc=tickets\b/);
    await expect(
      page.getByText(/^From the plan \(features\.json\); Linear is not connected/),
    ).toBeVisible();
    await expect(page.getByText("No status read from Linear yet.")).toBeVisible();
    const table = page.getByRole("table", { name: "Tickets" });
    await expect(table.getByRole("row")).toHaveCount(3);
    await expect(table.getByText("Add the export route")).toBeVisible();
    await expect(table.getByText("Add the button")).toBeVisible();
    await expect(table.getByText("not created")).toBeVisible();
    await expect(page.getByText(/2 tickets · from the plan \(features\.json\)/)).toBeVisible();
    const planning = page.getByRole("region", { name: "Planning" });
    await expect(planning.getByRole("heading", { name: "Parallel groups" })).toBeVisible();
    await expect(planning.getByText("Layer 2")).toBeVisible();
    await expect(planning.getByRole("heading", { name: "Recommended order" })).toBeVisible();
  });
});

// AGH-165 (AC-165.47, E14): the installed `hub web` drives the stub `claude` on its PATH. The
// printed token became the cookie (beforeEach), "New session" starts a session in the demo hub, the
// permission card survives a reload, a message goes through the composer after the answer, and
// the transcript survives a reload. Run alone by
// test_survives_reload_when_session_driven_agent_session (it needs SMOKE_TOKEN).
const AGENT_PROMPT = "Run the build.";
const AGENT_FOLLOW_UP = "Now run the tests.";

test("Agent session started from Sessions survives a reload while waiting and after the answer and a message", async ({
  page,
  baseURL,
}) => {
  const problems = watch(page, baseURL ?? "");
  // beforeEach traded the token for the cookie; the address keeps no token.
  await expect(page).not.toHaveURL(/token=/);
  await page.goto("/sessions");
  const driven = page.getByRole("region", { name: "Driven from hub web" });
  await page.getByLabel("Start sessions in").selectOption("demo");
  await driven.getByRole("button", { name: "New session" }).click();
  const dialog = page.getByRole("dialog", { name: "New session" });
  await dialog.getByLabel("First prompt (optional)").fill(AGENT_PROMPT);
  await dialog.getByRole("button", { name: "Start session" }).click();

  await expect(page).toHaveURL(/\/agent-sessions\/[0-9a-f-]+$/);
  const conversation = page.getByRole("log", { name: "Conversation" });
  await expect(page.getByRole("button", { name: "Allow once" })).toBeVisible();
  await page.reload();
  // AGH-242 (AC-234.29): the chord allows the oldest pending request; the button is still there.
  await expect(page.getByRole("button", { name: "Allow once" })).toBeVisible();
  await page.keyboard.press("Control+Alt+Enter");
  await expect(conversation.getByText("The build ran.")).toBeVisible();
  const composer = page.getByRole("form", { name: "Message composer" });
  const box = composer.getByLabel("Message Claude");
  // AGH-242 (AC-234.28, .30): `/` lists the init record's commands; axe runs with the menu open.
  await box.focus();
  await page.keyboard.type("/");
  await expect(page.getByRole("option", { name: "/compact" })).toBeVisible();
  await expectAccessible(page);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox", { name: "Commands" })).toBeHidden();
  await box.fill(AGENT_FOLLOW_UP);
  await composer.getByRole("button", { name: "Send" }).click();
  await expect(conversation.getByText("The tests ran.")).toBeVisible();
  // AGH-237 (AC-234.16): after the reply the header and the composer are still on screen; the
  // transcript scrolls, the page does not.
  await expect(page.getByRole("heading", { level: 1 })).toBeInViewport();
  await expect(page.getByRole("button", { name: "Close session" })).toBeInViewport();
  await expect(composer).toBeInViewport();
  expect(await page.locator("main").evaluate((main) => main.scrollHeight > main.clientHeight)).toBe(
    false,
  );
  await page.reload();
  await expect(conversation.getByText("The build ran.")).toBeVisible();
  await expect(conversation.getByText(AGENT_PROMPT)).toBeVisible();
  await expect(conversation.getByText(AGENT_FOLLOW_UP)).toBeVisible();
  await expect(conversation.getByText("The tests ran.")).toBeInViewport();
  await expectAccessible(page);
  expect(problems).toEqual([]);
});

// AGH-164 (AC-164.30): the demo hub's Skills catalog (hub init's managed skills plus the
// project's `demo-check`) and the managed `/feature` detail. Run alone by
// test_shows_skills_catalog_and_detail_when_skills_opened.
test("Skills catalog and a skill detail load from the hub's files", async ({ page, baseURL }) => {
  await visit(page, baseURL, "/projects/demo/skills", async () => {
    await expect(page.getByRole("heading", { level: 1, name: "Skills" })).toBeVisible();
    await expect(page.getByRole("article", { name: "demo-check", exact: true })).toBeVisible();
    const feature = page.getByRole("article", { name: "feature", exact: true });
    await expect(feature).toBeVisible();
    await expect(feature.getByText(/1 use in 30 days/)).toBeVisible();
  });
  await visit(page, baseURL, "/projects/demo/skills/skill/hub-workflow/feature", async () => {
    await expect(
      page.getByRole("heading", { level: 1, name: "feature", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Derived from the text")).toBeVisible();
    await expect(page.getByRole("region", { name: /^Text/ })).toBeVisible();
    await page.getByRole("button", { name: "Raw" }).click();
    await expect(page.locator("pre.ah-skill-raw")).toContainText("name: feature");
  });
});
