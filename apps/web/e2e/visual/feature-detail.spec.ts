import { screen } from "./screen";

// The demo feature's page: golden path, Waiting on you banner, tabs (AC-PG-31.*).
screen("feature-detail", "feature", "/features", "/features/");
// The ticket flow full window: cards, trunks and the zoom toolbar on the canvas (AC-521.10.5–10).
screen("feature-detail", "tickets-flow", "/features/demo/export-button?doc=tickets&flow=full");
