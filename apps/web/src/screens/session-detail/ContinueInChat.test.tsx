import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  aCapabilities,
  aSession,
  aWorkdir,
  anAgentSession,
  anId,
  renderWithApi,
  type ApiRoutes,
  type Session,
} from "../../testing/builders";
import { ContinueInChat, candidates } from "./ContinueInChat";

const CLAUDE_ID = anId(1, "7207667c");
const CHAT_ID = anId(2, "0192a5e5");
const HUB = aWorkdir({ workdir_id: "hub0000000000001", kind: "hub", repo: null });
const REPO = aWorkdir({ workdir_id: "repo000000000001", kind: "repo", repo: "agent-hub" });

function routes(overrides: ApiRoutes = {}): ApiRoutes {
  return {
    "/api/v1/agent-sessions/capabilities": aCapabilities(),
    "/api/v1/agent-sessions/workdirs": { items: [HUB, REPO], warnings: [] },
    "/api/v1/agent-sessions/resumable": (request: Request) => {
      const workdir = new URL(request.url).searchParams.get("workdir_id");
      const items =
        workdir === REPO.workdir_id
          ? [{ session_id: CLAUDE_ID, cwd: "/w/agent-hub", last_activity: "2026-10-17T23:54:00Z" }]
          : [];
      return { items };
    },
    "POST /api/v1/agent-sessions": anAgentSession({ id: CHAT_ID, claude_session_id: CLAUDE_ID }),
    ...overrides,
  };
}

function renderButton(session: Session, overrides: ApiRoutes = {}) {
  return renderWithApi(<ContinueInChat session={session} />, { routes: routes(overrides) });
}

describe("ContinueInChat", () => {
  it("resumes an ended terminal session in the folder that holds it and opens its chat", async () => {
    const view = renderButton(
      aSession({ id: CLAUDE_ID, status: "ended", repo: "agent-hub", label: null }),
    );

    await userEvent.click(await screen.findByRole("button", { name: "Continue in chat" }));

    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe(`/agent-sessions/${CHAT_ID}`);
    });
    const post = view.requests.find((r) => r.method === "POST");
    expect(JSON.parse((await post?.clone().text()) ?? "null")).toEqual({
      project: "agent-hub",
      workdir_id: REPO.workdir_id,
      resume_session_id: CLAUDE_ID,
      mode: "default",
      fork: false,
    });
  });

  it("says so when no registered folder holds the session", async () => {
    const view = renderButton(aSession({ id: anId(9, "deadbeef"), status: "ended" }));

    await userEvent.click(await screen.findByRole("button", { name: "Continue in chat" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/no resumable copy/);
    expect(view.requests.some((r) => r.method === "POST")).toBe(false);
  });

  it("waits while the session is still open in the terminal", async () => {
    renderButton(aSession({ id: CLAUDE_ID, status: "idle" }));

    expect(await screen.findByText("Running in a terminal")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue in chat" })).toBeNull();
  });

  it("shows nothing when this machine cannot drive sessions", async () => {
    const view = renderButton(aSession({ status: "ended" }), {
      "/api/v1/agent-sessions/capabilities": aCapabilities({ available: false }),
    });

    await waitFor(() => {
      expect(view.requests.length).toBeGreaterThan(0);
    });
    expect(screen.queryByRole("button", { name: "Continue in chat" })).toBeNull();
  });

  it("looks in the session's own repo first", () => {
    expect(candidates([HUB, REPO], "agent-hub").map((w) => w.workdir_id)).toEqual([
      REPO.workdir_id,
      HUB.workdir_id,
    ]);
  });
});
