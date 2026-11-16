import { screen } from "./screen";

// The demo's stuck session (seed_demo's STUCK_SESSION, its id suffixed with the seed's time): the
// detail and its header actions (AC-PG-24.3, AC-PG-24.4). The baseline shows that session; the
// first session link can be another one, depending on the seed's timing.
screen("session-detail", "session", "/sessions", "/sessions/demo-stuck-");
