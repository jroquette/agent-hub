import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

// The checks every smoke page passes: smoke.spec.ts and routes.spec.ts share them.

/** A variable tests/e2e/test_web_smoke.py sets for the run (the scenario's ids, the token). */
export const env = (name: string): string => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set: run the smoke through test_web_smoke.py`);
  return value;
};

/** Fails the test on any console error, page error, or request to another host (AC-200.56). */
export function watch(page: Page, baseURL: string): string[] {
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
export async function expectAccessible(page: Page): Promise<void> {
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
