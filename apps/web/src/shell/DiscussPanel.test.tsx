import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { captureScreen } from "../lib/screenCapture";
import { screenshotFor } from "../lib/screenshotCopy";

import {
  aCapabilities,
  aPage,
  aProblem,
  aProjectSummary,
  aWorkdir,
  anAgentSession,
  anId,
  renderWithApi,
  type RouteReply,
} from "../testing/builders";
import {
  discussPrompt,
  DiscussProvider,
  referencedMessage,
  useDiscuss,
  useDiscussTarget,
} from "./discuss";
import type { DiscussReference, DiscussTarget } from "./discuss";
import { DiscussPanel, discussMax } from "./DiscussPanel";
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
  starters: [{ label: "Is this still true?", message: "Check it against the code." }],
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
        [`POST ${SESSION}/messages`]: { seq: 1 },
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
  it("AC-422.5 starts with the discuss prompt and the references, then keeps that session for its target, its full chat in the menu", async () => {
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
    const fullChat = async () => {
      await userEvent.click(
        await screen.findByRole("button", { name: "More for this conversation" }),
      );
      return screen.findByRole("button", { name: "Open the full chat" });
    };
    expect(await fullChat()).toBeInTheDocument();
    expect(window.localStorage.getItem(`ah.discuss.session.${feature.key}`)).toBe(ID);

    await userEvent.click(screen.getByRole("button", { name: "switch" }));
    expect(screen.queryByRole("button", { name: "More for this conversation" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "switch" }));
    expect(await fullChat()).toBeInTheDocument();
  });

  it("sends a file attached to the first message with the new session (AC-419.13)", async () => {
    const view = renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "point" }));
    const box = await screen.findByRole("textbox", { name: "Message Claude" });
    await waitFor(() => {
      expect(box).toBeEnabled();
    });

    fireEvent.paste(box, {
      clipboardData: { files: [new File(["# Brief"], "brief.md", { type: "text/markdown" })] },
    });
    await screen.findByText("brief.md");
    await userEvent.type(box, "Start from this brief.{Enter}");

    const created = await waitFor(() => {
      const found = view.requests.find(
        (r) => r.method === "POST" && new URL(r.url).pathname === "/api/v1/agent-sessions",
      );
      expect(found).toBeDefined();
      return found;
    });
    const body = JSON.parse((await created?.clone().text()) ?? "{}") as {
      files?: { name: string; media_type: string; data: string }[];
    };
    expect(body.files).toEqual([
      { name: "brief.md", media_type: "text/plain", data: btoa("# Brief") },
    ]);
  });

  it("sends a running conversation's files with the message (AC-419.14)", async () => {
    window.localStorage.setItem(`ah.discuss.session.${feature.key}`, ID);
    const view = renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "point" }));
    const box = await screen.findByRole("textbox", { name: "Message Claude" });
    await waitFor(() => {
      expect(box).toBeEnabled();
    });

    fireEvent.paste(box, {
      clipboardData: { files: [new File(["a,b"], "rows.csv", { type: "text/csv" })] },
    });
    await screen.findByRole("button", { name: "Remove rows.csv" });
    await userEvent.type(box, "Check these rows.{Enter}");

    const sent = await waitFor(() => {
      const found = view.requests.find(
        (r) => r.method === "POST" && new URL(r.url).pathname === `${SESSION}/messages`,
      );
      expect(found).toBeDefined();
      return found;
    });
    const body = JSON.parse((await sent?.clone().text()) ?? "{}") as {
      files?: { name: string; media_type: string; data: string }[];
    };
    expect(body.files).toEqual([{ name: "rows.csv", media_type: "text/plain", data: btoa("a,b") }]);
  });

  it("AC-PG-38.3 says in words that a pointed-at row goes in the next message", async () => {
    renderPanel();

    await userEvent.click(screen.getByRole("button", { name: "point" }));

    const refs = await screen.findByRole("group", { name: "References for the next message" });
    expect(refs).toHaveTextContent("Next message is about");
    expect(refs).toHaveTextContent("AC-7");
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

  it("starts the conversation with a starter's message in one click", async () => {
    window.localStorage.setItem("ah.discuss.open", "1");
    const view = renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "switch" }));
    const group = await screen.findByRole("group", { name: "Start with" });
    const starter = within(group).getByRole("button", { name: "Is this still true?" });
    await waitFor(() => {
      expect(starter).toBeEnabled();
    });

    await userEvent.click(starter);

    const created = await waitFor(() => {
      const found = view.requests.filter(
        (r) => r.method === "POST" && new URL(r.url).pathname === "/api/v1/agent-sessions",
      );
      expect(found).toHaveLength(1);
      return found[0];
    });
    const body = JSON.parse((await created?.clone().text()) ?? "{}") as { prompt: string };
    expect(body.prompt).toBe(discussPrompt(skill, "Check it against the code."));
  });

  it("offers no starters when the target has none", async () => {
    window.localStorage.setItem("ah.discuss.open", "1");
    renderPanel();
    await screen.findByRole("textbox", { name: "Message Claude" });

    expect(screen.queryByRole("group", { name: "Start with" })).toBeNull();
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
      await screen.findByText(/Your first message takes this screen's text and a screenshot/),
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

describe("discussMax (the Discuss panel's widest width)", () => {
  it("AC-422.2 leaves the page 640 px when docked and stops at 720", () => {
    expect(discussMax(1440, 240)).toBe(560);
    expect(discussMax(1920, 240)).toBe(720);
  });

  it("AC-422.2 leaves 96 px of the page in view over it, and never goes under 320", () => {
    expect(discussMax(1100, 240)).toBe(1004);
    expect(discussMax(360, 0)).toBe(320);
  });
});

const OWNER = anId(4, "0192a5e6");
const OWNER_SESSION = `/api/v1/agent-sessions/${OWNER}`;
const owned: DiscussTarget = {
  ...feature,
  openOnArrive: true,
  starters: [{ label: "Is the spec testable?", message: "Check every AC." }],
  ownerSession: { id: OWNER, name: "AGH-7: Export orders" },
};

function OwnedScreen({ target }: { target: DiscussTarget }) {
  useDiscussTarget(target);
  return <DiscussPanel />;
}

function renderOwned(target: DiscussTarget, sessionReply?: RouteReply) {
  return renderWithApi(
    <DiscussProvider>
      <OwnedScreen target={target} />
    </DiscussProvider>,
    {
      routes: {
        "/api/v1/agent-sessions/capabilities": aCapabilities(),
        "/api/v1/agent-sessions/workdirs": { items: [aWorkdir()], warnings: [] },
        [OWNER_SESSION]: sessionReply ?? anAgentSession({ id: OWNER, status: "idle", last_seq: 0 }),
        [`${OWNER_SESSION}/events`]: { items: [], next_after: null },
      },
    },
  );
}

describe("DiscussPanel and the feature's own session (AGH-422)", () => {
  it("AC-422.1 opens on the feature's session, names it in row 2 and offers a new conversation", async () => {
    renderOwned(owned);

    expect(await screen.findByText("Feature session ·")).toBeInTheDocument();
    expect(screen.getByTitle("Feature session · AGH-7: Export orders")).toBeInTheDocument();
    await userEvent.click(
      await screen.findByRole("button", { name: "More for this conversation" }),
    );
    expect(screen.getByRole("button", { name: "Open the full chat" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back to the feature session" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "New conversation" }));

    // A conversation of the panel's own: the start state, and the way back in the menu.
    expect(
      await screen.findByRole("heading", { name: "Ask about this feature spec" }),
    ).toBeVisible();
    expect(screen.getByText(`${feature.kind} · ${feature.title}`)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "More for this conversation" }));
    await userEvent.click(screen.getByRole("button", { name: "Back to the feature session" }));
    expect(await screen.findByText("Feature session ·")).toBeInTheDocument();
  });

  it("AC-422.5 shows the file under discussion in the menu, where a click copies it", async () => {
    renderOwned(owned);
    await userEvent.click(
      await screen.findByRole("button", { name: "More for this conversation" }),
    );
    expect(screen.getByRole("dialog", { name: "More for this conversation" })).toHaveTextContent(
      "spec.md",
    );
  });

  it("AC-422.7 starts with a title, one line, and full-width starters under Start with", async () => {
    renderOwned({ ...owned, ownerSession: null });

    expect(
      await screen.findByRole("heading", { name: "Ask about this feature spec" }),
    ).toBeVisible();
    expect(
      screen.getByText("Claude works in the hub folder of demo. Edits ask you first."),
    ).toBeInTheDocument();
    const group = screen.getByRole("group", { name: "Start with" });
    expect(within(group).getByRole("button", { name: "Is the spec testable?" })).toHaveAttribute(
      "title",
      "Sends this message now",
    );
  });

  it("AC-422.6 shows a load failure in full, with Try again", async () => {
    renderOwned(
      owned,
      aProblem({ status: 500, title: "Server error", detail: "The store is locked." }),
    );

    expect(await screen.findByText("Could not load this conversation")).toBeInTheDocument();
    expect(screen.getByText(/The store is locked\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
