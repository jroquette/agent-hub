import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { rememberMessageScreenshots, rememberScreenshot } from "../lib/screenshotCopy";
import { aCapabilities, aWorkdir, anAgentSession, anId, renderWithApi } from "../testing/builders";
import type { DiscussTarget } from "./discuss";
import {
  readDiscussSession,
  rememberDiscussSession,
  useStartDiscussion,
  type StartDiscussionRequest,
} from "./discussSession";

vi.mock("../lib/screenshotCopy", () => ({
  rememberScreenshot: vi.fn(),
  rememberMessageScreenshots: vi.fn(),
}));

const ID = anId(3, "0192a5e5");
const target: DiscussTarget = {
  key: "feature:demo:virtual-iban",
  project: "demo",
  kind: "Feature spec",
  title: "virtual-iban",
};
const CAPTURE = "data:image/png;base64,Q0FQ";
const PASTED = "data:image/png;base64,UEFT";

function Starter({ request }: { request: StartDiscussionRequest }) {
  const discussion = useStartDiscussion("demo");
  return (
    <>
      <p>{discussion.reason ?? "ready"}</p>
      <button
        type="button"
        onClick={() => {
          void discussion.start(request).then((id) => {
            if (id) rememberDiscussSession(request.target, id);
          });
        }}
      >
        start
      </button>
    </>
  );
}

afterEach(() => {
  window.localStorage.clear();
  vi.clearAllMocks();
});

describe("useStartDiscussion (AC-419.15, AC-419.13)", () => {
  it("starts in the hub folder with the capture, the first message's images and files", async () => {
    const view = renderWithApi(
      <Starter
        request={{
          target,
          prompt: "Look at these.",
          images: [PASTED],
          files: [{ name: "brief.md", mediaType: "text/plain", data: "IyBC", bytes: 3 }],
          capture: { dataUrl: CAPTURE, body: { media_type: "image/png", data: "Q0FQ" } },
        }}
      />,
      {
        routes: {
          "/api/v1/agent-sessions/capabilities": aCapabilities(),
          "/api/v1/agent-sessions/workdirs": { items: [aWorkdir()], warnings: [] },
          "POST /api/v1/agent-sessions": anAgentSession({ id: ID, status: "running" }),
        },
      },
    );
    expect(await screen.findByText("ready")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "start" }));

    const created = await waitFor(() => {
      const found = view.requests.find(
        (r) => r.method === "POST" && new URL(r.url).pathname === "/api/v1/agent-sessions",
      );
      expect(found).toBeDefined();
      return found;
    });
    const body = JSON.parse((await created?.clone().text()) ?? "{}") as Record<string, unknown>;
    expect(body).toMatchObject({
      project: "demo",
      workdir_id: aWorkdir().workdir_id,
      prompt: "Look at these.",
      screenshot: { media_type: "image/png", data: "Q0FQ" },
      screenshots: [{ media_type: "image/png", data: "UEFT" }],
      files: [{ name: "brief.md", media_type: "text/plain", data: "IyBC" }],
    });
    await waitFor(() => {
      expect(readDiscussSession(target)).toBe(ID);
    });
    expect(rememberScreenshot).toHaveBeenCalledWith(ID, CAPTURE);
    // The first bubble shows the capture, then the images.
    expect(rememberMessageScreenshots).toHaveBeenCalledWith(ID, 1, [CAPTURE, PASTED]);
  });

  it("says why nothing can start when the project has no hub folder", async () => {
    renderWithApi(<Starter request={{ target, prompt: "Hi." }} />, {
      routes: {
        "/api/v1/agent-sessions/capabilities": aCapabilities(),
        "/api/v1/agent-sessions/workdirs": {
          items: [aWorkdir({ kind: "repo" })],
          warnings: [],
        },
      },
    });

    expect(
      await screen.findByText("Project demo has no hub folder to work in."),
    ).toBeInTheDocument();
  });

  it("forgets a target's conversation", () => {
    rememberDiscussSession(target, ID);
    expect(readDiscussSession(target)).toBe(ID);

    rememberDiscussSession(target, null);
    expect(readDiscussSession(target)).toBeNull();
  });
});
