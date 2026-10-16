import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { rememberScreenshot, screenshotFor } from "../../lib/screenshotCopy";
import {
  aCapabilities,
  aWorkdir,
  anAgentSession,
  anId,
  renderWithApi,
} from "../../testing/builders";
import { StartSessionDialog } from "./StartSessionDialog";

const AGENT = "/api/v1/agent-sessions";
const SHOT = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==";

function start(withScreenshot = true) {
  const created = anAgentSession({ id: anId(8, "0192a5e5"), status: "running" });
  const onClose = vi.fn();
  const view = renderWithApi(
    <StartSessionDialog
      project="agent-hub"
      workdirs={[aWorkdir()]}
      capabilities={aCapabilities()}
      {...(withScreenshot ? { screenshot: { dataUrl: SHOT } } : {})}
      onClose={onClose}
    />,
    { routes: { [`POST ${AGENT}`]: created }, path: "/sessions" },
  );
  return { created, onClose, view, dialog: screen.getByRole("dialog", { name: "New session" }) };
}

async function bodyOf(request: Request | undefined): Promise<unknown> {
  if (!request) throw new Error("no request");
  return JSON.parse(await request.clone().text()) as unknown;
}

describe("StartSessionDialog (shake to start a session)", () => {
  beforeEach(() => {
    rememberScreenshot("someone-else", "data:image/png;base64,AAAA");
  });

  it("navigates to the chat view and remembers the copy", async () => {
    const { created, onClose, view, dialog } = start();

    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "First prompt (optional)" }),
      "What is on this screen?",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));

    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe(`/agent-sessions/${created.id}`);
    });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screenshotFor(created.id)).toBe(SHOT);
    const post = view.requests.find(
      (r) => r.method === "POST" && new URL(r.url).pathname === AGENT,
    );
    expect(await bodyOf(post)).toMatchObject({
      prompt: "What is on this screen?",
      screenshot: { media_type: "image/png", data: "iVBORw0KGgoAAAANSUhEUg==" },
    });
  });

  it("releases the sent screenshot from the mutation cache once the dialog closes", async () => {
    const created = anAgentSession({ id: anId(8, "0192a5e5"), status: "running" });
    function Host() {
      const [open, setOpen] = useState(true);
      return open ? (
        <StartSessionDialog
          project="agent-hub"
          workdirs={[aWorkdir()]}
          capabilities={aCapabilities()}
          screenshot={{ dataUrl: SHOT }}
          onClose={() => {
            setOpen(false);
          }}
        />
      ) : null;
    }
    const view = renderWithApi(<Host />, {
      routes: { [`POST ${AGENT}`]: created },
      path: "/sessions",
    });

    await userEvent.type(
      screen.getByRole("textbox", { name: "First prompt (optional)" }),
      "What is on this screen?",
    );
    await userEvent.click(screen.getByRole("button", { name: "Start session" }));

    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe(`/agent-sessions/${created.id}`);
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => {
      expect(view.queryClient.getMutationCache().getAll()).toEqual([]);
    });
  });

  it("does not remember the copy when unchecked", async () => {
    const { created, view, dialog } = start();

    await userEvent.click(
      within(dialog).getByRole("checkbox", { name: "Attach a screenshot of the current screen" }),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));

    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe(`/agent-sessions/${created.id}`);
    });
    expect(screenshotFor(created.id)).toBeUndefined();
    const post = view.requests.find(
      (r) => r.method === "POST" && new URL(r.url).pathname === AGENT,
    );
    expect(await bodyOf(post)).not.toHaveProperty("screenshot");
  });

  it("closes on Cancel without a request", async () => {
    const { onClose, view, dialog } = start(false);

    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(view.requests.some((r) => r.method === "POST")).toBe(false);
  });
});
