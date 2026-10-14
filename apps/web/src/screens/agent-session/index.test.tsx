import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aCapabilities,
  aDeltaFrame,
  aLogRecord,
  aPermissionRequest,
  aProblem,
  anAgentSession,
  anId,
  renderWithApi,
  type ApiRoutes,
  type LogRecord,
} from "../../testing/builders";
import { AgentSessionScreen } from "./index";

const ID = anId(1, "0192a5e5");
const SESSION = `/api/v1/agent-sessions/${ID}`;
const EVENTS = `${SESSION}/events`;
const STREAM = `${SESSION}/stream`;

function log(): LogRecord[] {
  return [
    aLogRecord("init", { seq: 1 }),
    aLogRecord("user.message", { seq: 2 }),
    aLogRecord("text", { seq: 3, body: { block: 0, text: "Starting." } }),
  ];
}

function routes(overrides: ApiRoutes = {}): ApiRoutes {
  return {
    [SESSION]: anAgentSession({ status: "running", last_seq: 3 }),
    [EVENTS]: { items: log(), next_after: null },
    "/api/v1/agent-sessions/capabilities": aCapabilities(),
    ...overrides,
  };
}

function renderChat(apiRoutes: ApiRoutes = routes()) {
  return renderWithApi(<AgentSessionScreen />, {
    routes: apiRoutes,
    path: `/agent-sessions/${ID}`,
    route: "/agent-sessions/:agentSessionId",
  });
}

async function bodyOf(request: Request | undefined): Promise<unknown> {
  if (!request) throw new Error("no request");
  return JSON.parse(await request.clone().text()) as unknown;
}

const posts = (requests: Request[], suffix: string) =>
  requests.filter((r) => r.method === "POST" && new URL(r.url).pathname === `${SESSION}${suffix}`);

describe("AgentSessionScreen (transcript)", () => {
  it("loads the log then streams after its last record, appending deltas to one bubble", async () => {
    const view = renderChat();

    expect(await screen.findByText("Run the tests.")).toBeInTheDocument();
    expect(screen.getByText("Starting.")).toBeInTheDocument();
    const source = view.stream(STREAM);
    expect(new URL(source.url, window.location.origin).search).toBe("?after=3");

    act(() => {
      source.open();
      source.emit(
        "record.user.message",
        aLogRecord("user.message", { seq: 4, body: { text: "Again." } }),
        "4",
      );
      source.emit("delta", aDeltaFrame({ after_seq: 4, block: 1, index: 0, text: "Hel" }), "4.0");
      source.emit("delta", aDeltaFrame({ after_seq: 4, block: 1, index: 1, text: "lo" }), "4.1");
    });

    const bubbles = screen.getAllByRole("article", { name: "Claude" });
    expect(bubbles).toHaveLength(2);
    expect(bubbles[1]).toHaveTextContent("Hello");

    act(() => {
      source.emit(
        "record.text",
        aLogRecord("text", { seq: 5, body: { block: 1, text: "Hello there." } }),
        "5",
      );
      source.emit("record.tool.call", aLogRecord("tool.call", { seq: 6 }), "6");
    });

    expect(screen.getAllByRole("article", { name: "Claude" })).toHaveLength(2);
    expect(screen.getByText("Hello there.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Edit src\/app\.py/ })).toBeInTheDocument();
  });

  it("reads every log page when the log is longer than one page", async () => {
    const first = [aLogRecord("user.message", { seq: 1 })];
    const second = [aLogRecord("text", { seq: 2, body: { block: 0, text: "Page two." } })];
    const view = renderChat(
      routes({
        [EVENTS]: (request: Request) =>
          new URL(request.url).searchParams.get("after") === "1"
            ? { items: second, next_after: null }
            : { items: first, next_after: 1 },
      }),
    );

    expect(await screen.findByText("Page two.")).toBeInTheDocument();
    expect(view.requests.filter((r) => new URL(r.url).pathname === EVENTS)).toHaveLength(2);
    expect(new URL(view.stream(STREAM).url, window.location.origin).search).toBe("?after=2");
  });

  it("reloads the snapshot and the log and reopens the stream when the stream resets", async () => {
    const view = renderChat();
    await screen.findByText("Starting.");
    const before = view.stream(STREAM);

    act(() => {
      before.open();
      before.emit("reset", { reason: "unknown_position" });
    });

    await waitFor(() => {
      expect(view.requests.filter((r) => new URL(r.url).pathname === EVENTS)).toHaveLength(2);
    });
    await waitFor(() => {
      expect(view.stream(STREAM)).not.toBe(before);
    });
    expect(before.readyState).toBe(2);
    expect(screen.getByText("Starting.")).toBeInTheDocument();
  });

  it("opens no stream and offers Delete when the session has ended", async () => {
    const view = renderChat(
      routes({ [SESSION]: anAgentSession({ status: "ended", end_reason: "closed" }) }),
    );

    await screen.findByText("Starting.");
    expect(screen.getByText(/Ended · closed/)).toBeInTheDocument();
    expect(() => view.stream(STREAM)).toThrow();
    expect(screen.getByRole("button", { name: "Delete session" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close session" })).toBeNull();
  });

  it("deletes the session after confirmation and goes back to Sessions", async () => {
    const view = renderChat(
      routes({
        [SESSION]: anAgentSession({ status: "ended", end_reason: "closed" }),
        [`DELETE ${SESSION}`]: () => undefined,
      }),
    );
    await screen.findByText("Starting.");

    await userEvent.click(screen.getByRole("button", { name: "Delete session" }));
    const dialog = screen.getByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe("/sessions");
    });
    expect(view.requests.some((r) => r.method === "DELETE")).toBe(true);
  });

  it("links the agent session to its observed session", async () => {
    renderChat();

    const link = await screen.findByRole("link", { name: /Observed session/ });
    expect(link).toHaveAttribute("href", `/sessions/${anId(1, "5091b986")}`);
  });
});

describe("AgentSessionScreen (layout)", () => {
  it("keeps the header and the composer outside the one scrolling transcript column", async () => {
    const todos = aLogRecord("todos", { seq: 4 });
    const view = renderChat(
      routes({
        [SESSION]: anAgentSession({ status: "running", last_seq: 4 }),
        [EVENTS]: { items: [...log(), todos], next_after: null },
      }),
    );
    const conversation = await screen.findByRole("log", { name: "Conversation" });

    const header = view.container.querySelector("header.as-header");
    if (!(header instanceof HTMLElement)) throw new Error("no chat header");
    expect(within(header).getByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(within(header).getByText("Running")).toBeInTheDocument();
    expect(within(header).getByRole("group", { name: /Cost and tokens/ })).toBeInTheDocument();
    expect(within(header).getByRole("button", { name: "Close session" })).toBeInTheDocument();

    const scroller = conversation.closest(".as-scroll");
    expect(scroller).not.toBeNull();
    expect(scroller?.contains(header)).toBe(false);
    const composer = screen.getByRole("form", { name: "Message composer" });
    expect(scroller?.contains(composer)).toBe(false);
    expect(composer.closest("footer.as-footer")).not.toBeNull();
    expect(conversation).toHaveClass("as-column");

    const list = within(header).getByRole("region", { name: "Todo list" });
    expect(list.querySelector("details")).not.toHaveAttribute("open");
    expect(within(list).getByText(/0 of 1 done/)).toBeVisible();
  });
});

/** jsdom lays nothing out: a 1000 px transcript in a 400 px scroller, frames run at once. */
function stubScrolling() {
  vi.spyOn(Element.prototype, "scrollHeight", "get").mockReturnValue(1000);
  vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(400);
  vi.spyOn(HTMLElement.prototype, "offsetTop", "get").mockReturnValue(300);
  const writes = vi.spyOn(Element.prototype, "scrollTop", "set").mockImplementation((value) => {
    scrolled.top = Math.min(value, 600);
  });
  vi.spyOn(Element.prototype, "scrollTop", "get").mockImplementation(() => scrolled.top);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
  return writes;
}

/** The one scroll position stubScrolling's elements share. */
const scrolled = { top: 0 };

/** The reader scrolls the transcript up to `top`. */
function scrollUp(scroller: Element, top = 100) {
  scrolled.top = top;
  fireEvent.scroll(scroller);
}

describe("AgentSessionScreen (open-position)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens the saved transcript at its latest entry", async () => {
    const writes = stubScrolling();
    renderChat();
    const conversation = await screen.findByRole("log", { name: "Conversation" });

    const scroller = conversation.closest(".as-scroll");
    await waitFor(() => {
      expect(writes.mock.contexts).toContain(scroller);
    });
    expect(writes).toHaveBeenLastCalledWith(1000);
  });

  it("opens at the oldest pending permission card when one waits", async () => {
    const writes = stubScrolling();
    const older = aLogRecord("permission.request", { seq: 4 });
    renderChat(
      routes({
        [SESSION]: anAgentSession({
          status: "waiting_permission",
          last_seq: 4,
          open_permission: aPermissionRequest({ request_id: "req-2", summary: "ls" }),
        }),
        [EVENTS]: { items: [...log(), older], next_after: null },
      }),
    );

    const cards = await screen.findAllByRole("region", { name: /Claude wants to use Bash/ });
    expect(cards).toHaveLength(2);
    const scroller = cards[0]?.closest(".as-scroll");
    await waitFor(() => {
      expect(writes.mock.contexts).toContain(scroller);
    });
    // The first card's top, less a 16 px margin; never the bottom.
    expect(writes.mock.calls).toEqual([[284]]);
  });
});

describe("AgentSessionScreen (jump-to-latest)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    scrolled.top = 0;
  });

  async function detachedChat() {
    stubScrolling();
    const view = renderChat();
    const conversation = await screen.findByRole("log", { name: "Conversation" });
    const scroller = conversation.closest(".as-scroll");
    if (!scroller) throw new Error("no scroller");
    await waitFor(() => {
      expect(scrolled.top).toBe(600);
    });
    expect(screen.queryByRole("button", { name: /Jump to latest/ })).toBeNull();
    scrollUp(scroller);
    return { view, scroller };
  }

  it("counts the entries that arrive while detached and jumps to the latest", async () => {
    const { view, scroller } = await detachedChat();
    expect(screen.getByRole("button", { name: "Jump to latest" })).toBeInTheDocument();

    act(() => {
      const source = view.stream(STREAM);
      source.emit("record.user.message", aLogRecord("user.message", { seq: 4 }), "4");
      source.emit(
        "record.text",
        aLogRecord("text", { seq: 5, body: { block: 1, text: "On it." } }),
        "5",
      );
      source.emit("record.tool.call", aLogRecord("tool.call", { seq: 6 }), "6");
    });
    expect(scrolled.top).toBe(100);
    const jump = screen.getByRole("button", { name: "Jump to latest, 3 new" });
    expect(jump).toHaveTextContent("Jump to latest · 3 new");

    await userEvent.click(jump);

    expect(scrolled.top).toBe(600);
    expect(screen.queryByRole("button", { name: /Jump to latest/ })).toBeNull();
    scrollUp(scroller);
    expect(screen.getByRole("button", { name: "Jump to latest" })).toBeInTheDocument();
  });

  it("jumps with End in the transcript, smoothly unless the reader asks for less motion", async () => {
    const { scroller } = await detachedChat();
    const smooth = vi.fn();
    Object.defineProperty(scroller, "scrollTo", { value: smooth, configurable: true });

    fireEvent.keyDown(scroller, { key: "End" });

    expect(smooth).toHaveBeenCalledWith({ top: 1000, behavior: "smooth" });
    expect(screen.queryByRole("button", { name: /Jump to latest/ })).toBeNull();

    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce") }));
    scrollUp(scroller, 50);
    await userEvent.click(screen.getByRole("button", { name: "Jump to latest" }));

    expect(smooth).toHaveBeenCalledTimes(1);
    expect(scrolled.top).toBe(600);
  });
});

describe("AgentSessionScreen (permission)", () => {
  it("shows the snapshot's raw request over the stored copy and posts one answer", async () => {
    const stored = aLogRecord("permission.request", {
      seq: 4,
      body: {
        request_id: "req-1",
        request_kind: "tool",
        suggestions: [],
        summary: "echo [redacted: token]",
        tool: "Bash",
      },
    });
    const view = renderChat(
      routes({
        [SESSION]: anAgentSession({
          status: "waiting_permission",
          last_seq: 4,
          open_permission: aPermissionRequest({ summary: "echo raw-value" }),
        }),
        [EVENTS]: { items: [...log(), stored], next_after: null },
        [`POST ${SESSION}/permissions/req-1`]: anAgentSession({ status: "running" }),
      }),
    );

    const card = await screen.findByRole("region", { name: /Claude wants to use Bash/ });
    expect(within(card).getByText("echo raw-value")).toBeInTheDocument();
    await waitFor(() => {
      expect(card).toHaveFocus();
    });

    const allow = within(card).getByRole("button", { name: "Allow once" });
    await userEvent.click(allow);
    await userEvent.click(allow);

    const sent = posts(view.requests, "/permissions/req-1");
    expect(sent).toHaveLength(1);
    expect(await bodyOf(sent[0])).toEqual({ decision: "allow" });
    expect(allow).toBeDisabled();
  });

  it("shows a request that arrives on the stream", async () => {
    const view = renderChat();
    await screen.findByText("Starting.");

    act(() => {
      view
        .stream(STREAM)
        .emit("record.permission.request", aLogRecord("permission.request", { seq: 4 }), "4");
      view.stream(STREAM).emit("status", { status: "waiting_permission" });
    });

    expect(screen.getByRole("region", { name: /Claude wants to use Bash/ })).toBeInTheDocument();
    expect(screen.getAllByText("Waiting for you").length).toBeGreaterThan(0);
  });
});

describe("AgentSessionScreen (composer)", () => {
  it("sends on Enter and keeps a new line on Shift+Enter", async () => {
    const view = renderChat(routes({ [`POST ${SESSION}/messages`]: { seq: 4 } }));
    await screen.findByText("Starting.");

    const box = screen.getByRole("textbox", { name: "Message Claude" });
    await userEvent.type(box, "first{Shift>}{Enter}{/Shift}second");
    expect(box).toHaveValue("first\nsecond");
    await userEvent.type(box, "{Enter}");

    await waitFor(() => {
      expect(posts(view.requests, "/messages")).toHaveLength(1);
    });
    expect(await bodyOf(posts(view.requests, "/messages")[0])).toEqual({
      text: "first\nsecond",
    });
  });

  it("interrupts with an empty JSON body only while a turn runs", async () => {
    const view = renderChat(
      routes({ [`POST ${SESSION}/interrupt`]: anAgentSession({ status: "idle" }) }),
    );
    await screen.findByText("Starting.");

    await userEvent.click(screen.getByRole("button", { name: "Stop" }));

    await waitFor(() => {
      expect(posts(view.requests, "/interrupt")).toHaveLength(1);
    });
    const sent = posts(view.requests, "/interrupt")[0];
    expect(sent?.headers.get("content-type")).toContain("application/json");
    expect(await bodyOf(sent)).toEqual({});

    act(() => {
      view.stream(STREAM).emit("status", { status: "idle" });
    });
    expect(screen.getByRole("button", { name: "Stop" })).toBeDisabled();
  });

  it("posts settings when the mode or the model changes", async () => {
    const view = renderChat(
      routes({ [`POST ${SESSION}/settings`]: anAgentSession({ status: "running" }) }),
    );
    await screen.findByText("Starting.");

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Mode" }), "plan");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Model" }), "opus");

    await waitFor(() => {
      expect(posts(view.requests, "/settings")).toHaveLength(2);
    });
    const [mode, model] = posts(view.requests, "/settings");
    expect(await bodyOf(mode)).toEqual({ mode: "plan" });
    expect(await bodyOf(model)).toEqual({ model: "opus" });
  });

  it("shows the reconnect banner while the stream is lost and hides it once it resumes", async () => {
    const view = renderChat();
    await screen.findByText("Starting.");
    const source = view.stream(STREAM);
    act(() => {
      source.open();
    });
    expect(screen.queryByText(/Connection to this session lost/)).toBeNull();

    act(() => {
      source.fail();
    });
    expect(screen.getByText(/Connection to this session lost/)).toBeInTheDocument();

    act(() => {
      source.open();
    });
    expect(screen.queryByText(/Connection to this session lost/)).toBeNull();
  });

  it("has a polite live region and no serious axe violation (a11y)", async () => {
    const view = renderChat();
    await screen.findByText("Starting.");

    expect(screen.getByRole("log", { name: "Conversation" })).toHaveAttribute(
      "aria-live",
      "polite",
    );
    expect(await seriousViolations(view.container)).toEqual([]);
  });
});

describe("AgentSessionScreen (unavailable)", () => {
  it("tells the user to open the token link once when the cookie is missing", async () => {
    renderChat(
      routes({
        [SESSION]: aProblem({ status: 401, title: "Session control is locked" }),
        [EVENTS]: aProblem({ status: 401, title: "Session control is locked" }),
      }),
    );

    expect(await screen.findByText(/it ends with \?token=/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Message Claude" })).toBeNull();
  });

  it("says session control is off in the container", async () => {
    const off = aProblem({
      status: 404,
      title: "Session control is off",
      type: "urn:agent-hub:problem:agent-sessions-off",
    });
    renderChat(routes({ [SESSION]: off, [EVENTS]: off }));

    expect(await screen.findByText(/off in the container/)).toBeInTheDocument();
  });

  it("says the session does not exist when it is unknown", async () => {
    const missing = aProblem({ status: 404, title: "Agent session not found" });
    renderChat(routes({ [SESSION]: missing, [EVENTS]: missing }));

    expect(await screen.findByText("Agent session not found")).toBeInTheDocument();
  });
});
