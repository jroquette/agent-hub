import { screen } from "./screen";

// The demo's ended chat, opened by its fixed id (scripts/seed_demo.py's CHAT_SESSION, which the
// runner passes): header, transcript and Steps (AC-PG-14.*, AC-PG-24.*, AC-PG-32.*).
screen("agent-session", "chat", `/agent-sessions/${process.env.AH_VISUAL_CHAT_SESSION ?? ""}`);
