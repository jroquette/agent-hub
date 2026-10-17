import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ScreenshotThumbProps } from "../../components/ScreenshotLightbox";
import { screenshotFor } from "../../lib/screenshotCopy";
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
const MARKED = "data:image/png;base64,TUFSS0VE";

// The markup editor draws on a canvas jsdom lacks; its own tests cover it. Here it saves at once.
vi.mock("../../components/ScreenshotLightbox", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../components/ScreenshotLightbox")>();
  return {
    ...actual,
    ScreenshotThumb: ({ src, alt, onSave }: ScreenshotThumbProps) => (
      <button
        type="button"
        aria-label={`Open and mark up: ${alt}`}
        onClick={() => onSave?.(MARKED)}
      >
        <img src={src} alt={alt} />
      </button>
    ),
  };
});

describe("StartSessionDialog (marked-up screenshot, AC-266.3)", () => {
  it("sends the marked-up screenshot and remembers it for the chat", async () => {
    const created = anAgentSession({ id: anId(8, "0192a5e6"), status: "running" });
    const view = renderWithApi(
      <StartSessionDialog
        project="agent-hub"
        workdirs={[aWorkdir()]}
        capabilities={aCapabilities()}
        screenshot={{ dataUrl: SHOT }}
        onClose={vi.fn()}
      />,
      { routes: { [`POST ${AGENT}`]: created }, path: "/sessions" },
    );
    const dialog = screen.getByRole("dialog", { name: "New session" });

    await userEvent.click(
      within(dialog).getByRole("checkbox", { name: "Attach a screenshot of the current screen" }),
    );
    await userEvent.click(
      within(dialog).getByRole("button", {
        name: "Open and mark up: Screenshot of the screen you shook",
      }),
    );
    expect(
      within(dialog).getByRole("checkbox", { name: "Attach a screenshot of the current screen" }),
    ).toBeChecked();
    expect(
      within(dialog).getByText(/Click it to view it larger and mark it up/),
    ).toBeInTheDocument();
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Prompt" }), "Look here");
    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));

    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe(`/agent-sessions/${created.id}`);
    });
    const post = view.requests.find(
      (r) => r.method === "POST" && new URL(r.url).pathname === AGENT,
    );
    if (!post) throw new Error("no POST");
    expect(JSON.parse(await post.clone().text())).toMatchObject({
      screenshot: { media_type: "image/png", data: "TUFSS0VE" },
    });
    expect(screenshotFor(created.id)).toBe(MARKED);
  });
});
