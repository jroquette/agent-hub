import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { captureScreen } from "../lib/screenCapture";
import { screenshotFor } from "../lib/screenshotCopy";

import {
  aCapabilities,
  aPage,
  aProjectSummary,
  aWorkdir,
  anAgentSession,
  anId,
  renderWithApi,
} from "../testing/builders";
import {
  discussPrompt,
  DiscussProvider,
  referencedMessage,
  useDiscuss,
  useDiscussTarget,
} from "./discuss";
import type { DiscussReference, DiscussTarget } from "./discuss";
import { DiscussPanel } from "./DiscussPanel";
import { ScreenDiscussFallback, screenDiscussTarget } from "./screenContext";

vi.mock("../lib/screenCapture", () => ({ captureScreen: vi.fn() }));

const ID = anId(3, "0192a5e5");
const SESSION = `/api/v1/agent-sessions/${ID}`;

const feature: DiscussTarget = {
  key: "feature:demo:virtual-iban",
  project: "demo",
  kind: "Feature spec",
  title: "virtual-iban",
  path: "brain/features/virtual-iban/spec.md",
};
const skill: DiscussTarget = {
  key: "skill:demo:plan",
  project: "demo",
  kind: "Skill",
  title: "plan",
};
const AC: DiscussReference = {
  id: "ac:AC-7",
  label: "AC-7",
  source: "brain/features/virtual-iban/features.json",
  quote: "AC-7: routes multi-parcel",
};

function Screen() {
  const [target, setTarget] = useState(feature);
  useDiscussTarget(target);
  const { addReference } = useDiscuss();
  return (
    <>
      <button
        type="button"
        onClick={() => {
          addReference(AC);
        }}
      >
        point
      </button>
      <button
        type="button"
        onClick={() => {
          setTarget((t) => (t === feature ? skill : feature));
        }}
      >
        switch
      </button>
      <DiscussPanel />
    </>
  );
}

function renderPanel() {
  return renderWithApi(
    <DiscussProvider>
      <Screen />
    </DiscussProvider>,
    {
      routes: {
        "/api/v1/agent-sessions/capabilities": aCapabilities(),
        "/api/v1/agent-sessions/workdirs": { items: [aWorkdir()], warnings: [] },
        "POST /api/v1/agent-sessions": anAgentSession({ id: ID, status: "running" }),
        [SESSION]: anAgentSession({ id: ID, status: "idle", last_seq: 0 }),
        [`${SESSION}/events`]: { items: [], next_after: null },
      },
    },
  );
}

beforeEach(() => {
  window.localStorage.clear();
});
afterEach(() => {
  window.localStorage.clear();
});

describe("DiscussPanel", () => {
  it("starts with the discuss prompt and the references, then keeps that session for its target", async () => {
    const view = renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "point" }));
    const box = await screen.findByRole("textbox", { name: "Message Claude" });
    await waitFor(() => {
      expect(box).toBeEnabled();
    });

    await userEvent.type(box, "Is this still right?{Enter}");

    const created = await waitFor(() => {
      const found = view.requests.filter(
        (r) => r.method === "POST" && new URL(r.url).pathname === "/api/v1/agent-sessions",
      );
      expect(found).toHaveLength(1);
      return found[0];
    });
    const body = JSON.parse((await created?.clone().text()) ?? "{}") as { prompt: string };
    expect(body.prompt).toBe(
      discussPrompt(feature, referencedMessage([AC], "Is this still right?")),
    );
    expect(await screen.findByRole("link", { name: "Full chat" })).toHaveAttribute(
      "href",
      `/agent-sessions/${ID}`,
    );
    expect(window.localStorage.getItem(`ah.discuss.session.${feature.key}`)).toBe(ID);

    await userEvent.click(screen.getByRole("button", { name: "switch" }));
    expect(screen.queryByRole("link", { name: "Full chat" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "switch" }));
    expect(await screen.findByRole("link", { name: "Full chat" })).toHaveAttribute(
      "href",
      `/agent-sessions/${ID}`,
    );
  });

  it("starts the conversation with a starter's message in one click (AC-269.16)", async () => {
    const withStarter: DiscussTarget = {
      ...feature,
      openOnArrive: true,
      starters: [{ label: "Write the human summary of spec", message: "Run /summarize x spec" }],
    };
    function Starter() {
      useDiscussTarget(withStarter);
      return <DiscussPanel />;
    }
    const view = renderWithApi(
      <DiscussProvider>
        <Starter />
      </DiscussProvider>,
      {
        routes: {
          "/api/v1/agent-sessions/capabilities": aCapabilities(),
          "/api/v1/agent-sessions/workdirs": { items: [aWorkdir()], warnings: [] },
          "POST /api/v1/agent-sessions": anAgentSession({ id: ID, status: "running" }),
          [SESSION]: anAgentSession({ id: ID, status: "idle", last_seq: 0 }),
          [`${SESSION}/events`]: { items: [], next_after: null },
        },
      },
    );

    const starter = await screen.findByRole("button", { name: "Write the human summary of spec" });
    await waitFor(() => {
      expect(starter).toBeEnabled();
    });
    await userEvent.click(starter);

    const created = await waitFor(() => {
      const found = view.requests.find(
        (r) => r.method === "POST" && new URL(r.url).pathname === "/api/v1/agent-sessions",
      );
      if (!found) throw new Error("no POST");
      return found;
    });
    const body = JSON.parse(await created.clone().text()) as { prompt: string };
    expect(body.prompt).toBe(discussPrompt(withStarter, "Run /summarize x spec"));
  });
});

const SHOT = "data:image/png;base64,iVBORw0KGgo=";

function ScreenPage({ fallback }: { fallback: DiscussTarget | null }) {
  const { setFallback } = useDiscuss();
  return (
    <>
      <main id="main">
        <h1>Workflow runs</h1>
        <p>3 runs failed in verify</p>
      </main>
      <button
        type="button"
        onClick={() => {
          setFallback(fallback);
        }}
      >
        name screen
      </button>
      <DiscussPanel />
    </>
  );
}

function renderScreen(fallback: DiscussTarget | null, workdirs = [aWorkdir()]) {
  window.localStorage.setItem("ah.discuss.open", "1");
  return renderWithApi(
    <DiscussProvider>
      <ScreenPage fallback={fallback} />
    </DiscussProvider>,
    {
      routes: {
        "/api/v1/agent-sessions/capabilities": aCapabilities(),
        "/api/v1/agent-sessions/workdirs": { items: workdirs, warnings: [] },
        "POST /api/v1/agent-sessions": anAgentSession({ id: ID, status: "running" }),
        [SESSION]: anAgentSession({ id: ID, status: "idle", last_seq: 0 }),
        [`${SESSION}/events`]: { items: [], next_after: null },
      },
    },
  );
}

async function sendFirst(view: ReturnType<typeof renderScreen>, text: string) {
  await userEvent.click(screen.getByRole("button", { name: "name screen" }));
  const box = await screen.findByRole("textbox", { name: "Message Claude" });
  await waitFor(() => {
    expect(box).toBeEnabled();
  });
  await userEvent.type(box, `${text}{Enter}`);
  const created = await waitFor(() => {
    const found = view.requests.find(
      (r) => r.method === "POST" && new URL(r.url).pathname === "/api/v1/agent-sessions",
    );
    expect(found).toBeDefined();
    return found;
  });
  return JSON.parse((await created?.clone().text()) ?? "{}") as {
    prompt: string;
    screenshot?: { media_type: string; data: string };
  };
}

describe("DiscussPanel on a whole screen (AGH-273)", () => {
  const runs = screenDiscussTarget({
    project: "demo",
    pathname: "/runs",
    search: "?status=failed",
    title: "Workflow runs",
  });

  it("AC-273.2: sends the screen's text and a screenshot with the first message", async () => {
    vi.mocked(captureScreen).mockResolvedValue({ ok: true, dataUrl: SHOT, bytes: 8 });
    const view = renderScreen(runs);
    await userEvent.click(screen.getByRole("button", { name: "name screen" }));
    expect(
      await screen.findByText(/Your first message takes its text and a screenshot along/),
    ).toBeInTheDocument();

    const body = await sendFirst(view, "Why did these fail?");

    expect(body.prompt).toMatch(/<screen>\n.*Workflow runs.*3 runs failed in verify.*\n<\/screen>/);
    expect(body.prompt).toContain("`/runs?status=failed`");
    expect(body.prompt).toContain("Why did these fail?");
    expect(body.screenshot).toEqual({ media_type: "image/png", data: "iVBORw0KGgo=" });
    expect(screenshotFor(ID)).toBe(SHOT);
  });

  it("AC-273.3: still sends the text when the screenshot cannot be taken", async () => {
    vi.mocked(captureScreen).mockResolvedValue({ ok: false, reason: "timeout" });
    const view = renderScreen(runs);

    const body = await sendFirst(view, "What is this?");

    expect(body.prompt).toContain("3 runs failed in verify");
    expect(body.screenshot).toBeUndefined();
  });

  it("AC-273.5: asks for a registered project when there is nothing to discuss", () => {
    renderScreen(null);

    expect(
      screen.getByText(/Register a project to talk with Claude about any screen/),
    ).toBeInTheDocument();
  });

  it("AC-273.1: names the open screen by its heading as the panel's target", async () => {
    vi.mocked(captureScreen).mockResolvedValue({ ok: false, reason: "timeout" });
    renderWithApi(
      <DiscussProvider>
        <main id="main">
          <h1>Health</h1>
        </main>
        <ScreenDiscussFallback />
        <TargetProbe />
      </DiscussProvider>,
      {
        path: "/health?x=1",
        routes: {
          "/api/v1/agent-sessions/capabilities": aCapabilities(),
          "/api/v1/projects": aPage([aProjectSummary({ name: "demo" })]),
        },
      },
    );

    expect(await screen.findByTestId("probe")).toHaveTextContent("screen:demo:/health · Health");
  });
});

function TargetProbe() {
  const { target } = useDiscuss();
  return target ? <span data-testid="probe">{`${target.key} · ${target.title}`}</span> : null;
}
