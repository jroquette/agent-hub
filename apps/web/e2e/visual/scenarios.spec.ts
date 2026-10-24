import { screen } from "./screen";

// The Scenarios list with New scenario, on the demo's scenarios and runs (AC-521.12.1).
screen("scenarios", "scenarios", "/scenarios");
// New scenario: the guided form that hands the request to Claude (AC-521.12.2).
screen("scenarios", "new", "/scenarios/new");
// The builder: Blocks tab, step list and the environment bar (AC-521.13.1–3, AC-521.13.8).
screen("scenarios", "builder", "/scenarios/demo/demo-order-roundtrip");
// The run view: the storyline beside the run panel, following the running scenario run (AC-521.11.2–4).
screen("scenarios", "run-view", "/scenarios/demo/demo-order-roundtrip?mode=run");
