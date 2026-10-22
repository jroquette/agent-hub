import { screen } from "./screen";

// The Environments page on the demo data, which declares no environment: its empty state
// (AC-417.3). The pages of one environment need declared ones the demo data does not have.
screen("environments", "environments", "/projects/demo/environments");

// The first step of Add environment: one column of choices in the flow's fixed frame (AC-417.17).
screen("environments", "add-environment", "/projects/demo/environments/new");
