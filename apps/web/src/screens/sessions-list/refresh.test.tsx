import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  aPage,
  aProjectSummary,
  aSession,
  aSessionLabel,
  anId,
  renderWithApi,
  type ApiRoutes,
  type FakeEventSource,
} from "../../testing/builders";
import { SessionsListScreen } from "./index";

const SESSIONS = "/api/v1/sessions";
const STREAM = "/api/v1/live-sessions/stream";
const ROW = 40;

const one = (n: number, status: "waiting" | "live" | "ended") =>
  aSession({
    id: anId(n, "cccc0000"),
    status,
    label: aSessionLabel({ issue: null, workflow: `/s${String(n)}`, workflows: [] }),
  });

/** `GET /sessions` answering from `data` as it is when asked, so a test can change it. */
function routes(data: { current: ReturnType<typeof one>[] }): ApiRoutes {
  return {
    [SESSIONS]: (request: Request) => {
      const status = new URL(request.url).searchParams.get("status");
      return aPage(data.current.filter((s) => s.status === status));
    },
    "/api/v1/projects": aPage([aProjectSummary()]),
    "/api/v1/agent-sessions": { items: [] },
  };
}

const statusesAsked = (requests: Request[], from: number) =>
  requests
    .slice(from)
    .filter((r) => new URL(r.url).pathname === SESSIONS)
    .map((r) => new URL(r.url).searchParams.get("status"))
    .sort();

function render(data: { current: ReturnType<typeof one>[] }) {
  return renderWithApi(
    <div data-testid="scroller" style={{ overflowY: "auto" }}>
      <SessionsListScreen />
    </div>,
    { routes: routes(data), path: "/sessions" },
  );
}

/** Each row sits ROW px below the previous one, in document order, minus the scroller's offset. */
function layOutRows() {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const scroller = screen.getByTestId("scroller");
    const rows = [...document.querySelectorAll("tr[data-key]")];
    const index = rows.indexOf(this);
    const top = this === scroller ? 0 : index < 0 ? 0 : index * ROW - scroller.scrollTop;
    return {
      top,
      bottom: top + ROW,
      left: 0,
      right: 0,
      height: ROW,
      width: 0,
      x: 0,
      y: top,
    } as DOMRect;
  });
}

/** Sends one stream change and lets the 2 s throttle pass at once. */
async function change(source: FakeEventSource, type: string, data: unknown) {
  vi.useFakeTimers();
  source.emit(type, data);
  await act(() => vi.advanceTimersByTimeAsync(2_000));
  vi.useRealTimers();
}

afterEach(() => {
  vi.useRealTimers();
  window.localStorage.clear();
});

describe("SessionsListScreen no-jump", () => {
  it("refetches each open section once after a burst, at the 2 s edge, never a collapsed one", async () => {
    window.localStorage.setItem("ah.sessions.collapsed", JSON.stringify(["ended"]));
    const data = { current: [one(1, "waiting"), one(2, "live"), one(3, "ended")] };
    const { requests, stream } = render(data);
    await screen.findByText("/s2");
    const source = stream(STREAM);
    const before = requests.length;

    vi.useFakeTimers();
    for (let i = 0; i < 10; i += 1) {
      source.emit(i % 2 ? "tile.remove" : "tile.upsert", { id: anId(i), group: "live" });
      await act(() => vi.advanceTimersByTimeAsync(i < 9 ? 222 : 1)); // 10 events within 1,999 ms
    }
    expect(statusesAsked(requests, before)).toEqual([]);
    await act(() => vi.advanceTimersByTimeAsync(1)); // exactly 2,000 ms after the first event
    expect(statusesAsked(requests, before)).toEqual(["idle", "live", "waiting"]);

    const second = requests.length;
    source.emit("tile.upsert", { id: anId(1), group: "waiting" });
    await act(() => vi.advanceTimersByTimeAsync(1_999));
    expect(statusesAsked(requests, second)).toEqual([]);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(statusesAsked(requests, second)).toEqual(["idle", "live", "waiting"]);
    vi.useRealTimers();

    // A section that missed a change while collapsed catches up once when opened.
    const opened = requests.length;
    fireEvent.click(screen.getByRole("button", { name: /^Ended or failed/ }));
    await waitFor(() => {
      expect(statusesAsked(requests, opened)).toEqual(["ended"]);
    });
  });

  it("stops listening on unmount", async () => {
    const { stream, unmount } = render({ current: [one(2, "live")] });
    await screen.findByText("/s2");
    const source = stream(STREAM);
    unmount();
    expect(source.readyState).toBe(2);
  });

  it("keeps the first visible row in place when rows are inserted above it", async () => {
    const data = { current: [one(1, "live"), one(2, "ended"), one(3, "ended"), one(4, "ended")] };
    const { stream } = render(data);
    await screen.findByText("/s4");
    layOutRows();
    const scroller = screen.getByTestId("scroller");
    scroller.scrollTop = 2 * ROW + 10; // /s3 is the first row whose bottom is below the top
    fireEvent.scroll(scroller);
    const anchor = () => screen.getByText("/s3").closest("tr") as Element;
    expect(anchor().getBoundingClientRect().top).toBe(-10);

    data.current = [
      one(5, "live"),
      one(6, "live"),
      one(1, "live"),
      one(7, "ended"),
      ...data.current.slice(1),
    ];
    await change(stream(STREAM), "tile.upsert", { id: anId(5), group: "live" });
    await screen.findByText("/s7");

    expect(anchor().getBoundingClientRect().top).toBe(-10);
    expect(scroller.scrollTop).toBe(5 * ROW + 10);
  });

  it("anchors on the next visible row when the first one moves to another section", async () => {
    const data = { current: [one(1, "live"), one(2, "ended"), one(3, "ended"), one(4, "ended")] };
    const { stream } = render(data);
    await screen.findByText("/s4");
    layOutRows();
    const scroller = screen.getByTestId("scroller");
    scroller.scrollTop = ROW + 10; // /s2 first, then /s3
    fireEvent.scroll(scroller);

    data.current = [
      one(1, "live"),
      one(2, "live"),
      one(5, "ended"),
      one(3, "ended"),
      one(4, "ended"),
    ];
    await change(stream(STREAM), "tile.upsert", { id: anId(2), group: "live" });
    await screen.findByText("/s5");

    expect(scroller.scrollTop).toBe(2 * ROW + 10); // /s3 kept its offset; /s2 moved
  });

  it("does not move a reader at the very top", async () => {
    const data = { current: [one(1, "live"), one(2, "ended")] };
    const { stream } = render(data);
    await screen.findByText("/s2");
    layOutRows();
    const scroller = screen.getByTestId("scroller");

    data.current = [one(5, "waiting"), ...data.current];
    await change(stream(STREAM), "tile.upsert", { id: anId(5), group: "waiting" });
    await screen.findByText("/s5");

    expect(scroller.scrollTop).toBe(0);
  });

  it("keeps focus on the row by key when it moves to another section, else on its section header", async () => {
    const data = { current: [one(1, "live"), one(2, "live"), one(4, "live"), one(3, "ended")] };
    const { requests, stream } = render(data);
    await screen.findByText("/s1");
    (screen.getByText("/s1").closest("tr") as HTMLElement).focus();

    data.current = [one(2, "live"), one(4, "live"), one(3, "ended"), one(1, "ended")];
    await change(stream(STREAM), "tile.upsert", { id: anId(1), group: "ended_recently" });
    const ended = screen.getByRole("table", { name: "Ended or failed sessions" });
    await waitFor(() => {
      expect(screen.getByText("/s1").closest("table")).toBe(ended);
    });
    expect(document.activeElement).toBe(screen.getByText("/s1").closest("tr"));

    (screen.getByText("/s2").closest("tr") as HTMLElement).focus();
    data.current = [one(4, "live"), one(3, "ended"), one(1, "ended")]; // /s2 is gone
    await change(stream(STREAM), "tile.remove", { id: anId(2) });
    await waitFor(() => {
      expect(screen.queryByText("/s2")).toBeNull();
    });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /^Live/ }));
    const sent = requests.length;

    // Focus on a control inside a row stays on it.
    const check = within(screen.getByText("/s4").closest("tr") as HTMLElement).getByRole(
      "checkbox",
    );
    check.focus();
    await change(stream(STREAM), "tile.upsert", { id: anId(4), group: "live" });
    await waitFor(() => {
      expect(requests.length).toBeGreaterThan(sent);
    });
    expect(document.activeElement).toBe(check);

    // Focus the reader moved out of the list is left where they put it.
    (screen.getByText("/s4").closest("tr") as HTMLElement).focus();
    (document.activeElement as HTMLElement).blur();
    data.current = [one(3, "ended"), one(1, "ended")];
    await change(stream(STREAM), "tile.remove", { id: anId(4) });
    await waitFor(() => {
      expect(screen.queryByText("/s4")).toBeNull();
    });
    expect(document.activeElement).toBe(document.body);
  });
});
