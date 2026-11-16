import { screen } from "./screen";

// The Scenarios list with New scenario, on the demo's scenarios and runs (AC-521.12.1).
screen("scenarios", "scenarios", "/scenarios");
// New scenario: the guided form that hands the request to Claude (AC-521.12.2).
screen("scenarios", "new", "/scenarios/new");
// The scenario page as one screen that builds and runs: the run bar, the run strip, the blocks and the
// run panel (AC-521.13.1–3, AC-521.13.8, AC-596.2.1–2.41).
screen("scenarios", "builder", "/scenarios/demo/demo-order-roundtrip");
// A selected step opened in place, in its row (AC-596.3.16–3.28): the run bar's environment and
// the running scenario run on the blocks stay in view. The first tree item is the start, not a step.
screen("scenarios", "step-open", "/scenarios/demo/demo-order-roundtrip", {
  act: async (page) => {
    await page.getByRole("treeitem", { name: /^Step 1,/ }).click();
  },
});
// The Graph view: each card reads as its Blocks row (AC-596.5.1–5.6).
screen("scenarios", "graph", "/scenarios/demo/demo-order-roundtrip", {
  act: async (page) => {
    await page
      .getByRole("group", { name: "View" })
      .getByRole("button", { name: "Graph", exact: true })
      .click();
  },
});
