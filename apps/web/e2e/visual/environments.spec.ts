import { screen } from "./screen";

// The Environments page on the demo data, which declares no environment: its empty state
// (AC-417.3). The pages of one environment need declared ones the demo data does not have.
screen("environments", "environments", "/projects/demo/environments");
