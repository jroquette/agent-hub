import { act, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

import { ConfirmDialog } from "../components/feedback";
import { captureScreen } from "../lib/screenCapture";
import { matchingWorkdir, servedCheckout } from "../lib/devCheckout";
import {
  aCapabilities,
  aPage,
  aProblem,
  aProjectSummary,
  aWorkdir,
  renderWithApi,
  type ApiRoutes,
} from "../testing/builders";
import { AppShell } from "./AppShell";
import { LIVE_RELOAD_NOTE, ShakeToSession } from "./ShakeToSession";

vi.mock("../lib/screenCapture", () => ({ captureScreen: vi.fn() }));
vi.mock("../lib/devCheckout", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/devCheckout")>();
  return {
    ...actual,
    servedCheckout: vi.fn(() => null),
    matchingWorkdir: vi.fn(actual.matchingWorkdir),
  };
});

const AGENT = "/api/v1/agent-sessions";
const SHOT = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==";
// The same vector as devCheckout.test.ts and core's test_workdirs.py (E6).
const ROOT = "/srv/demo/agent-hub";
const REPO_ID = "5703fef9dd5a3894";

let clock = 1_000;

/** Synthetic `pointermove` events: six reversals of 80 px, 50 ms apart (a shake). */
function shake() {
  for (const x of [100, 180, 100, 180, 100, 180, 100, 180]) {
    const event = new PointerEvent("pointermove", { clientX: x, pointerType: "mouse" });
    Object.defineProperty(event, "timeStamp", { value: (clock += 50) });
    act(() => {
      window.dispatchEvent(event);
    });
  }
  clock += 5_000;
}

function routes(overrides: ApiRoutes = {}): ApiRoutes {
  return {
    "/api/v1/projects": aPage([aProjectSummary()]),
    [`${AGENT}/capabilities`]: aCapabilities(),
    [`${AGENT}/workdirs`]: {
      items: [aWorkdir(), aWorkdir({ kind: "repo", label: "agent-hub", workdir_id: REPO_ID })],
      warnings: [],
    },
    ...overrides,
  };
}

function mount(path = "/sessions?scope=agent-hub", overrides: ApiRoutes = {}) {
  return renderWithApi(<ShakeToSession />, { routes: routes(overrides), path });
}

/** Waits until the workdirs answered, so a shake can act. */
async function ready(view: ReturnType<typeof mount>) {
  await waitFor(() => {
    expect(view.requests.some((r) => new URL(r.url).pathname === `${AGENT}/workdirs`)).toBe(true);
  });
  await act(async () => {
    await Promise.resolve();
  });
}

/** Lets a shake's awaits (capture, workdir match) run to the end. */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("ShakeToSession (shake to start a session)", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(captureScreen).mockResolvedValue({ ok: true, dataUrl: SHOT, bytes: 16 });
    vi.mocked(servedCheckout).mockReturnValue(null);
  });
  afterEach(() => {
    localStorage.clear();
  });

  it("shake-off: no listener while the toggle is off", async () => {
    const view = renderWithApi(<AppShell />, {
      routes: routes(),
      path: "/sessions?scope=agent-hub",
    });
    await act(async () => {
      await Promise.resolve();
    });

    shake();

    expect(captureScreen).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "New session" })).toBeNull();
    expect(view.requests.some((r) => new URL(r.url).pathname === `${AGENT}/capabilities`)).toBe(
      false,
    );
  });

  it("shake-opens: capture once, before the dialog mounts", async () => {
    localStorage.setItem("ah.shakeToSession", "on");
    const order: string[] = [];
    vi.mocked(captureScreen).mockImplementation(() => {
      order.push(
        document.querySelector('[role="dialog"]')
          ? "capture after dialog"
          : "capture before dialog",
      );
      return Promise.resolve({ ok: true, dataUrl: SHOT, bytes: 16 });
    });
    const view = renderWithApi(<AppShell />, {
      routes: routes(),
      path: "/sessions?scope=agent-hub",
    });
    await ready(view);

    shake();

    const dialog = await screen.findByRole("dialog", { name: "New session" });
    expect(order).toEqual(["capture before dialog"]);
    expect(captureScreen).toHaveBeenCalledTimes(1);
    expect(
      within(dialog).getByRole("checkbox", { name: "Attach a screenshot of the current screen" }),
    ).toBeChecked();
    expect(
      within(dialog).getByRole("img", { name: "Screenshot of the screen you shook" }),
    ).toHaveAttribute("src", SHOT);

    shake();
    expect(captureScreen).toHaveBeenCalledTimes(1);
  });

  it("shake-opens: the project comes from a project route", async () => {
    const view = mount("/projects/agent-hub/skills");
    await ready(view);

    shake();

    await screen.findByRole("dialog", { name: "New session" });
    const workdirs = view.requests.find((r) => new URL(r.url).pathname === `${AGENT}/workdirs`);
    expect(new URL(workdirs?.url ?? "").searchParams.get("project")).toBe("agent-hub");
  });

  it.each([
    ["unavailable", { [`${AGENT}/capabilities`]: aCapabilities({ available: false }) }],
    ["401", { [`${AGENT}/capabilities`]: aProblem({ status: 401, title: "Unauthorized" }) }],
    [
      "404 off",
      {
        [`${AGENT}/capabilities`]: aProblem({
          status: 404,
          title: "Not found",
          type: "urn:agent-hub:problem:agent-sessions-off",
        }),
      },
    ],
  ])("shake-inert: %s", async (_name, overrides) => {
    const view = mount("/sessions?scope=agent-hub", overrides);
    await waitFor(() => {
      expect(view.requests.some((r) => new URL(r.url).pathname === `${AGENT}/capabilities`)).toBe(
        true,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });

    shake();

    expect(captureScreen).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shake-inert: a dialog already open", async () => {
    const view = renderWithApi(
      <>
        <div role="dialog" aria-label="Command palette" />
        <ShakeToSession />
      </>,
      { routes: routes(), path: "/sessions?scope=agent-hub" },
    );
    await ready(view);

    shake();

    expect(captureScreen).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "New session" })).toBeNull();
  });

  it("shake-inert: a confirmation (alertdialog) already open", async () => {
    const view = renderWithApi(
      <>
        <ConfirmDialog title="Stop the session?" confirmLabel="Stop" />
        <ShakeToSession />
      </>,
      { routes: routes(), path: "/sessions?scope=agent-hub" },
    );
    await ready(view);
    expect(screen.getByRole("alertdialog", { name: "Stop the session?" })).toBeInTheDocument();

    shake();
    await settle();

    expect(captureScreen).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "New session" })).toBeNull();
  });

  it("shake-inert: a dialog that opens during the capture keeps New session closed", async () => {
    const palette = document.createElement("div");
    palette.setAttribute("role", "dialog");
    palette.setAttribute("aria-label", "Command palette");
    onTestFinished(() => {
      palette.remove();
    });
    vi.mocked(captureScreen).mockImplementationOnce(() => {
      document.body.append(palette);
      return Promise.resolve({ ok: true, dataUrl: SHOT, bytes: 16 });
    });
    const view = mount();
    await ready(view);

    shake();
    await settle();

    expect(captureScreen).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog", { name: "New session" })).toBeNull();

    palette.remove();
    shake();
    await screen.findByRole("dialog", { name: "New session" });
    expect(captureScreen).toHaveBeenCalledTimes(2);
  });

  it("live-edit-fallback: a throwing workdir match still opens, and the next shake works", async () => {
    vi.mocked(servedCheckout).mockReturnValue(ROOT);
    vi.mocked(matchingWorkdir).mockRejectedValueOnce(new TypeError("crypto.subtle is undefined"));
    const view = mount();
    await ready(view);

    shake();

    const dialog = await screen.findByRole("dialog", { name: "New session" });
    expect(within(dialog).getByRole("note")).toHaveTextContent(LIVE_RELOAD_NOTE);
    act(() => {
      within(dialog).getByRole("button", { name: "Cancel" }).click();
    });

    shake();
    const again = await screen.findByRole("dialog", { name: "New session" });
    expect(within(again).getByRole("combobox", { name: "Working folder" })).toHaveValue(REPO_ID);
  });

  it("a shake that fails before opening leaves the gesture alive", async () => {
    vi.mocked(captureScreen).mockRejectedValueOnce(new Error("boom"));
    const view = mount();
    await ready(view);

    shake();
    await settle();
    expect(screen.queryByRole("dialog", { name: "New session" })).toBeNull();

    shake();
    await screen.findByRole("dialog", { name: "New session" });
    expect(captureScreen).toHaveBeenCalledTimes(2);
  });

  it.each([["/sessions"], ["/settings/appearance"]])(
    "shake-opens: with no project in %s, the first registered project",
    async (path) => {
      const view = mount(path, {
        "/api/v1/projects": aPage([
          aProjectSummary({ name: "tipple" }),
          aProjectSummary({ name: "agent-hub" }),
        ]),
      });
      await ready(view);

      shake();

      await screen.findByRole("dialog", { name: "New session" });
      const workdirs = view.requests.find((r) => new URL(r.url).pathname === `${AGENT}/workdirs`);
      expect(new URL(workdirs?.url ?? "").searchParams.get("project")).toBe("tipple");
    },
  );

  it("shake-inert: no project registered", async () => {
    const view = mount("/sessions", { "/api/v1/projects": aPage([]) });
    await waitFor(() => {
      const paths = view.requests.map((r) => new URL(r.url).pathname);
      expect(paths).toContain(`${AGENT}/capabilities`);
      expect(paths).toContain("/api/v1/projects");
    });
    await act(async () => {
      await Promise.resolve();
    });

    shake();

    expect(captureScreen).not.toHaveBeenCalled();
    expect(view.requests.some((r) => new URL(r.url).pathname === `${AGENT}/workdirs`)).toBe(false);
  });

  it("capture-failed: the dialog opens without a screenshot", async () => {
    vi.mocked(captureScreen).mockResolvedValue({ ok: false, reason: "timeout" });
    const view = mount();
    await ready(view);

    shake();

    const dialog = await screen.findByRole("dialog", { name: "New session" });
    const attach = within(dialog).getByRole("checkbox", {
      name: "Attach a screenshot of the current screen",
    });
    expect(attach).not.toBeChecked();
    expect(attach).toBeDisabled();
    expect(within(dialog).getByText("No screenshot was taken")).toBeInTheDocument();
    expect(within(dialog).queryByRole("img")).toBeNull();
  });

  it("live-edit: the served checkout's workdir and acceptEdits, no note", async () => {
    vi.mocked(servedCheckout).mockReturnValue(ROOT);
    const view = mount();
    await ready(view);

    shake();

    const dialog = await screen.findByRole("dialog", { name: "New session" });
    expect(within(dialog).getByRole("combobox", { name: "Working folder" })).toHaveValue(REPO_ID);
    expect(within(dialog).getByRole("radio", { name: /Accept edits/ })).toBeChecked();
    expect(within(dialog).queryByRole("note")).toBeNull();
  });

  it("live-edit-fallback: no served checkout keeps the defaults and shows the note", async () => {
    const view = mount();
    await ready(view);

    shake();

    const dialog = await screen.findByRole("dialog", { name: "New session" });
    expect(within(dialog).getByRole("combobox", { name: "Working folder" })).toHaveValue(
      aWorkdir().workdir_id,
    );
    expect(within(dialog).getByRole("radio", { name: /Ask/ })).toBeChecked();
    expect(within(dialog).getByRole("note")).toHaveTextContent(LIVE_RELOAD_NOTE);
    expect(LIVE_RELOAD_NOTE).toBe("Live reload needs make dev in a listed folder");
  });

  it("live-edit-fallback: a served checkout that is not listed shows the note", async () => {
    vi.mocked(servedCheckout).mockReturnValue("/srv/elsewhere");
    const view = mount();
    await ready(view);

    shake();

    const dialog = await screen.findByRole("dialog", { name: "New session" });
    expect(within(dialog).getByRole("note")).toHaveTextContent(LIVE_RELOAD_NOTE);
  });

  it("closes on Cancel and opens again on the next shake", async () => {
    const view = mount();
    await ready(view);

    shake();
    const dialog = await screen.findByRole("dialog", { name: "New session" });
    act(() => {
      within(dialog).getByRole("button", { name: "Cancel" }).click();
    });
    expect(screen.queryByRole("dialog")).toBeNull();

    shake();
    await screen.findByRole("dialog", { name: "New session" });
    expect(captureScreen).toHaveBeenCalledTimes(2);
  });
});
