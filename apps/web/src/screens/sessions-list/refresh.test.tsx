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
interface Data {
  current: ReturnType<typeof one>[];
  /** The cursor every first page answers with. */
  next?: string;
}

function routes(data: Data): ApiRoutes {
  return {
    [SESSIONS]: (request: Request) => {
      const status = new URL(request.url).searchParams.get("status");
      return aPage(
        data.current.filter((s) => s.status === status),
        { next_cursor: data.next ?? null },
      );
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

function render(data: Data) {
  return renderWithApi(
    <div data-testid="scroller" style={{ overflowY: "auto" }}>
      <SessionsListScreen />
    </div>,
    { routes: routes(data), path: "/sessions" },
  );
}

const REGION = ".ah-table-wrap > div[tabindex]";

/**
 * Each row (or bounded region, or with `headers` each section header) sits ROW px below the previous
 * one in page order, minus the scroller's offset; a row inside a bounded region sits by its index
 * below the region's top, minus the region's own offset.
 */
function layOutRows(headers = false) {
  const page = `${headers ? "section h2 button, " : ""}tr[data-key], ${REGION}`;
  const topOf = (element: Element): number => {
    const scroller = screen.getByTestId("scroller");
    if (element === scroller) return 0;
    const region = element.closest(REGION);
    if (region && element !== region) {
      return topOf(region) + Number(element.getAttribute("data-index")) * ROW - region.scrollTop;
    }
    const order = [...document.querySelectorAll(page)].filter(
      (candidate) => candidate.matches(REGION) || !candidate.closest(REGION),
    );
    const index = order.indexOf(element);
    return index < 0 ? 0 : index * ROW - scroller.scrollTop;
  };
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const top = topOf(this);
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

/** Lets a scroll's measurement (one per animation frame) run. */
const nextFrame = () =>
  act(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));

/** Sends one stream change and lets the 2 s throttle pass at once. */
async function change(source: FakeEventSource, type: string, data: unknown) {
  vi.useFakeTimers();
  source.emit(type, data);
  await act(() => vi.advanceTimersByTimeAsync(2_000));
  await act(() => vi.advanceTimersByTimeAsync(100)); // the refetch answers and commits
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

  it("sends nothing after an unmount while a refetch is pending", async () => {
    const { requests, stream, unmount } = render({ current: [one(2, "live")] });
    await screen.findByText("/s2");
    const source = stream(STREAM);
    const before = requests.length;
    vi.useFakeTimers();
    source.emit("tile.upsert", { id: anId(2), group: "live" });
    unmount();
    await vi.advanceTimersByTimeAsync(2_000);
    expect(statusesAsked(requests, before)).toEqual([]);
  });

  it("refetches the sections, throttled, when the agent-list poll brings data", async () => {
    const { requests, queryClient } = render({ current: [one(2, "live")] });
    await screen.findByText("/s2");
    const before = requests.length;
    vi.useFakeTimers();
    await act(() =>
      queryClient.refetchQueries({
        predicate: (query) => JSON.stringify(query.queryKey).includes("/api/v1/agent-sessions"),
      }),
    );
    await act(() => vi.advanceTimersByTimeAsync(1_999));
    expect(statusesAsked(requests, before)).toEqual([]);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(statusesAsked(requests, before)).toEqual(["ended", "idle", "live", "waiting"]);
  });

  it("does not cancel a Load more in flight when a refetch is due", async () => {
    const { stream } = render({ current: [one(3, "ended")], next: "e2" });
    await screen.findByText("/s3");
    let release = () => undefined as void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const base = vi.mocked(globalThis.fetch).getMockImplementation();
    vi.mocked(globalThis.fetch).mockImplementation(async (input, init) => {
      const request = input instanceof Request ? input : new Request(input, init);
      if (new URL(request.url).searchParams.get("cursor") !== "e2") return base!(request);
      await held;
      return new Response(JSON.stringify(aPage([one(9, "ended")])), {
        headers: { "content-type": "application/json" },
      });
    });
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await change(stream(STREAM), "tile.upsert", { id: anId(3), group: "ended_recently" });
    release();
    expect(await screen.findByText("/s9")).toBeInTheDocument();
  });

  it("keeps the first visible row in place when rows are inserted above it", async () => {
    const data = { current: [one(1, "live"), one(2, "ended"), one(3, "ended"), one(4, "ended")] };
    const { stream } = render(data);
    await screen.findByText("/s4");
    layOutRows();
    const scroller = screen.getByTestId("scroller");
    scroller.scrollTop = 2 * ROW + 10; // /s3 is the first row whose bottom is below the top
    fireEvent.scroll(scroller);
    await nextFrame();
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
    await nextFrame();

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

  it("anchors on a section's bounded region, not on the rows scrolling inside it", async () => {
    const ended = Array.from({ length: 101 }, (_, i) => one(100 + i, "ended"));
    const data = { current: [one(1, "live"), ...ended] };
    const { stream } = render(data);
    await screen.findByText("/s100");
    layOutRows();
    const scroller = screen.getByTestId("scroller");
    scroller.scrollTop = ROW + 10; // the Ended region is the first visible thing
    fireEvent.scroll(scroller);
    await nextFrame();

    data.current = [one(2, "live"), one(1, "live"), one(9, "ended"), one(8, "ended"), ...ended];
    await change(stream(STREAM), "tile.upsert", { id: anId(9), group: "ended_recently" });
    await screen.findByText("/s9");

    expect(scroller.scrollTop).toBe(2 * ROW + 10); // one row above the region, none for those inside
  });

  it("keeps the first visible row inside a bounded region when rows are inserted above it", async () => {
    const ended = Array.from({ length: 101 }, (_, i) => one(100 + i, "ended"));
    const data = { current: [one(1, "live"), ...ended] };
    const { stream } = render(data);
    await screen.findByText("/s100");
    layOutRows();
    const scroller = screen.getByTestId("scroller");
    const region = screen.getByRole("region", { name: /^Scrollable ended/ });
    scroller.scrollTop = ROW + 10; // the region's top is 10 px above the page's
    region.scrollTop = 5 * ROW + 10; // /s105 is the first row showing in it
    fireEvent.scroll(region);
    fireEvent.scroll(scroller);
    await nextFrame();

    data.current = [one(1, "live"), one(9, "ended"), one(8, "ended"), one(7, "ended"), ...ended];
    await change(stream(STREAM), "tile.upsert", { id: anId(9), group: "ended_recently" });
    await screen.findByText("/s9");

    expect(region.scrollTop).toBe(8 * ROW + 10);
    expect(scroller.scrollTop).toBe(ROW + 10);
  });

  it("does not correct the scroll for a collapse or a sort the reader made", async () => {
    const data = {
      current: [one(1, "live"), one(2, "live"), one(3, "ended"), one(4, "ended"), one(5, "ended")],
    };
    render(data);
    await screen.findByText("/s5");
    layOutRows();
    const scroller = screen.getByTestId("scroller");
    scroller.scrollTop = 3 * ROW + 10; // /s4 first
    fireEvent.scroll(scroller);
    await nextFrame();

    fireEvent.click(screen.getByRole("button", { name: /^Live/ }));
    expect(screen.getByRole("button", { name: /^Live/ })).toHaveAttribute("aria-expanded", "false");
    expect(scroller.scrollTop).toBe(3 * ROW + 10);

    const ended = screen.getByRole("table", { name: "Ended or failed sessions" });
    data.current = [
      one(1, "live"),
      one(2, "live"),
      one(5, "ended"),
      one(4, "ended"),
      one(3, "ended"),
    ];
    fireEvent.click(within(ended).getByRole("button", { name: /^Cost/ }));
    await waitFor(() => {
      expect(screen.getAllByText(/^\/s[345]$/).map((cell) => cell.textContent)).toEqual([
        "/s5",
        "/s4",
        "/s3",
      ]);
    });
    expect(scroller.scrollTop).toBe(3 * ROW + 10);
  });

  it("does not chase a row that moved within its section", async () => {
    const data = {
      current: [one(1, "live"), one(2, "ended"), one(3, "ended"), one(4, "ended"), one(5, "ended")],
    };
    const { stream } = render(data);
    await screen.findByText("/s5");
    layOutRows();
    const scroller = screen.getByTestId("scroller");
    scroller.scrollTop = 2 * ROW + 10; // /s3 first, then /s4
    fireEvent.scroll(scroller);
    await nextFrame();

    data.current = [
      one(1, "live"),
      one(2, "ended"),
      one(4, "ended"),
      one(5, "ended"),
      one(3, "ended"),
    ];
    await change(stream(STREAM), "tile.upsert", { id: anId(3), group: "ended_recently" });
    await waitFor(() => {
      expect(screen.getAllByText(/^\/s[2345]$/).at(-1)).toHaveTextContent("/s3");
    });

    expect(scroller.scrollTop).toBe(ROW + 10); // /s4 kept its offset; /s3 moved down
  });

  it("does not move focus to a header far from the viewport", async () => {
    const live = Array.from({ length: 30 }, (_, i) => one(10 + i, "live"));
    const data = { current: [...live, one(3, "ended")] };
    const { stream } = render(data);
    await screen.findByText("/s39");
    layOutRows(true);
    const scroller = screen.getByTestId("scroller");
    scroller.scrollTop = 29 * ROW; // the Live header is 1,160 px above
    fireEvent.scroll(scroller);
    await nextFrame();
    (screen.getByText("/s39").closest("tr") as HTMLElement).focus();

    data.current = [...live.slice(0, 29), one(3, "ended")];
    await change(stream(STREAM), "tile.remove", { id: anId(39) });
    await waitFor(() => {
      expect(screen.queryByText("/s39")).toBeNull();
    });
    expect(document.activeElement).toBe(document.body);
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
    data.current = [one(4, "live"), one(5, "live"), one(3, "ended"), one(1, "ended")];
    await change(stream(STREAM), "tile.upsert", { id: anId(5), group: "live" });
    await screen.findByText("/s5"); // a commit with new rows
    expect(requests.length).toBeGreaterThan(sent);
    expect(document.activeElement).toBe(check);

    // Focus the reader moved out of the list is left where they put it.
    (screen.getByText("/s4").closest("tr") as HTMLElement).focus();
    (document.activeElement as HTMLElement).blur();
    data.current = [one(5, "live"), one(3, "ended"), one(1, "ended")];
    await change(stream(STREAM), "tile.remove", { id: anId(4) });
    await waitFor(() => {
      expect(screen.queryByText("/s4")).toBeNull();
    });
    expect(document.activeElement).toBe(document.body);
  });
});
