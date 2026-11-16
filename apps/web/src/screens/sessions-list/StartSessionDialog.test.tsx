import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  rememberMessageScreenshots,
  rememberScreenshot,
  screenshotFor,
} from "../../lib/screenshotCopy";
import {
  aCapabilities,
  aWorkdir,
  anAgentSession,
  anId,
  renderWithApi,
} from "../../testing/builders";
import { StartSessionDialog } from "./StartSessionDialog";

vi.mock("../../lib/pastedImage", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/pastedImage")>();
  return {
    ...actual,
    imageToPng: vi.fn((file: File) => Promise.resolve(`data:image/png;base64,${file.name}`)),
  };
});

vi.mock("../../lib/screenshotCopy", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/screenshotCopy")>();
  return { ...actual, rememberMessageScreenshots: vi.fn(actual.rememberMessageScreenshots) };
});

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
      within(dialog).getByRole("textbox", { name: "Prompt" }),
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
      screen.getByRole("textbox", { name: "Prompt" }),
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

  it("does not remember the copy once removed", async () => {
    const { created, view, dialog } = start();

    await userEvent.click(
      within(dialog).getByRole("button", { name: "Remove Screenshot of the screen you shook" }),
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

  it("AC-421.7 keeps the capture and the images of the first prompt for the chat's first bubble", async () => {
    const { created, view, dialog } = start();
    const prompt = within(dialog).getByRole("textbox", { name: "Prompt" });

    fireEvent.paste(prompt, {
      clipboardData: { files: [new File(["png"], "UEFTVEVE", { type: "image/png" })] },
    });
    const attached = within(dialog).getByRole("list", { name: "Attached to the first prompt" });
    expect(await within(attached).findByRole("img", { name: "Image 2" })).toBeInTheDocument();
    await userEvent.type(prompt, "Compare these");
    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));

    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe(`/agent-sessions/${created.id}`);
    });
    expect(vi.mocked(rememberMessageScreenshots)).toHaveBeenCalledWith(created.id, 1, [
      SHOT,
      "data:image/png;base64,UEFTVEVE",
    ]);
    const post = view.requests.find(
      (r) => r.method === "POST" && new URL(r.url).pathname === AGENT,
    );
    expect(await bodyOf(post)).toMatchObject({
      prompt: "Compare these",
      screenshots: [{ media_type: "image/png", data: "UEFTVEVE" }],
    });
  });

  it("closes on Cancel without a request", async () => {
    const { onClose, view, dialog } = start(false);

    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(view.requests.some((r) => r.method === "POST")).toBe(false);
  });
});
