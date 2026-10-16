import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  aPage,
  aProblem,
  aProjectSummary,
  aSession,
  aSessionLabel,
  aSessionsByStatus,
  anId,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { SessionsListScreen } from "./index";

// These tests read the tables; the grid is the default view (AC-234.3).
beforeEach(() => {
  window.localStorage.setItem("ah.sessions.view", "table");
});

const SESSIONS = "/api/v1/sessions";
const COLLAPSED = "ah.sessions.collapsed";

const named = (name: string) =>
  aSessionLabel({ issue: null, workflow: `/${name}`, workflows: [`/${name}`] });
const one = (n: number, status: "waiting" | "live" | "idle" | "ended", name: string) =>
  aSession({ id: anId(n, `bbbb${String(n).padStart(4, "0")}`), status, label: named(name) });
const many = (count: number, status: "live" | "ended", from: number) =>
  Array.from({ length: count }, (_, i) => one(from + i, status, `${status}-${String(i)}`));

const SAMPLE = [one(1, "waiting", "asker"), one(2, "live", "runner"), one(3, "ended", "done")];

function routes(sessions: ApiRoutes[string] = aSessionsByStatus(SAMPLE)): ApiRoutes {
  return {
    [SESSIONS]: sessions,
    "/api/v1/projects": aPage([aProjectSummary()]),
    "/api/v1/agent-sessions": { items: [] },
  };
}

const sessionRequests = (requests: Request[]) =>
  requests.filter((r) => new URL(r.url).pathname === SESSIONS).map((r) => new URL(r.url));
/** The section header buttons, in page order, with whether each is expanded. */
const toggles = () =>
  screen
    .queryAllByRole("button")
    .filter(
      (button) => button.hasAttribute("aria-controls") && button.id.startsWith("sl-section-"),
    );
const headers = () => toggles().map((button) => button.textContent);
const collapsedHeaders = () =>
  toggles()
    .filter((button) => button.getAttribute("aria-expanded") === "false")
    .map((button) => button.textContent);

afterEach(() => {
  window.localStorage.clear();
});

describe("SessionsListScreen status-sections", () => {
  it("shows the sections in order with their counts, one query each, and hides an empty one", async () => {
    const live = { ...aPage([one(2, "live", "runner")], { next_cursor: "c2" }), total_estimate: 4 };
    const { requests } = renderWithApi(<SessionsListScreen />, {
      routes: routes((request: Request) =>
        new URL(request.url).searchParams.get("status") === "live"
          ? live
          : aSessionsByStatus(SAMPLE)(request),
      ),
      path: "/sessions",
    });

    await screen.findByText("/runner");
    expect(headers()).toEqual(["Waiting · 1", "Live · ~4", "Ended or failed · 1"]);
    expect(screen.queryByRole("region", { name: /^Idle/ })).toBeNull();
    expect(
      sessionRequests(requests)
        .map((url) => url.searchParams.get("status"))
        .sort(),
    ).toEqual(["ended", "idle", "live", "waiting"]);
  });

  it("collapses a section from its header and remembers it", async () => {
    const first = renderWithApi(<SessionsListScreen />, { routes: routes(), path: "/sessions" });
    await screen.findByText("/runner");

    const live = screen.getByRole("button", { name: "Live · 1" });
    fireEvent.click(live);
    expect(live).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("/runner")).toBeNull();
    expect(screen.getByText("/asker")).toBeInTheDocument();
    expect(window.localStorage.getItem(COLLAPSED)).toBe('["live"]');
    first.unmount();

    renderWithApi(<SessionsListScreen />, { routes: routes(), path: "/sessions" });
    await screen.findByText("/asker");
    expect(screen.getByRole("button", { name: "Live · 1" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    fireEvent.click(screen.getByRole("button", { name: "Live · 1" }));
    expect(screen.getByText("/runner")).toBeInTheDocument();
    expect(window.localStorage.getItem(COLLAPSED)).toBe("[]");
  });

  it("shows one empty state and no section when every section is empty", async () => {
    renderWithApi(<SessionsListScreen />, { routes: routes(aPage([])), path: "/sessions" });

    expect(await screen.findByText("No sessions yet.")).toBeInTheDocument();
    expect(headers()).toEqual([]);
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("SessionsListScreen collapsed-bad-json", () => {
  it.each([
    ["{not json", []],
    ['{"live":true}', []],
    ['"live"', []],
    ['["live","bogus","live",3]', ["Live · 1"]],
  ])("reads %s as the collapsed set %j", async (stored, collapsed) => {
    window.localStorage.setItem(COLLAPSED, stored);
    renderWithApi(<SessionsListScreen />, { routes: routes(), path: "/sessions" });
    await screen.findByText("/asker");

    expect(headers()).toEqual(["Waiting · 1", "Live · 1", "Ended or failed · 1"]);
    expect(collapsedHeaders()).toEqual(collapsed);
  });

  it("keeps only the known sections when it writes the set back", async () => {
    window.localStorage.setItem(COLLAPSED, '["live","bogus","live",3]');
    renderWithApi(<SessionsListScreen />, { routes: routes(), path: "/sessions" });
    await screen.findByText("/asker");

    fireEvent.click(screen.getByRole("button", { name: "Waiting · 1" }));
    expect(window.localStorage.getItem(COLLAPSED)).toBe('["live","waiting"]');
  });
});

describe("SessionsListScreen section-error", () => {
  it("shows the error and Retry in the failing section while the others keep rendering", async () => {
    let failing = true;
    const { requests } = renderWithApi(<SessionsListScreen />, {
      routes: routes((request: Request) =>
        failing && new URL(request.url).searchParams.get("status") === "ended"
          ? aProblem({ status: 500, title: "Boom", detail: "The read model failed." })
          : aSessionsByStatus(SAMPLE)(request),
      ),
      path: "/sessions",
    });

    const ended = await screen.findByRole("region", { name: /^Ended or failed/ });
    expect(await within(ended).findByText("Could not load ended or failed sessions")).toBeVisible();
    // No query returned a count: the header shows the ellipsis, not 0.
    expect(headers()).toEqual(["Waiting · 1", "Live · 1", "Ended or failed · …"]);
    expect(screen.getByText("/asker")).toBeInTheDocument();
    expect(screen.getByText("/runner")).toBeInTheDocument();

    failing = false;
    fireEvent.click(within(ended).getByRole("button", { name: "Try again" }));
    expect(await within(ended).findByText("/done")).toBeInTheDocument();
    expect(headers()).toEqual(["Waiting · 1", "Live · 1", "Ended or failed · 1"]);
    await waitFor(() => {
      expect(sessionRequests(requests).map((url) => url.searchParams.get("status"))).toHaveLength(
        5,
      );
    });
    expect(
      sessionRequests(requests).filter((url) => url.searchParams.get("status") === "ended"),
    ).toHaveLength(2);
  });
});

describe("SessionsListScreen filters-both-views", () => {
  it("asks and shows only the faceted section, with the period on Ended only", async () => {
    const faceted = renderWithApi(<SessionsListScreen />, {
      routes: routes(),
      path: "/sessions?status=waiting",
    });
    await screen.findByText("/asker");
    expect(headers()).toEqual(["Waiting · 1"]);
    expect(sessionRequests(faceted.requests).map((url) => url.searchParams.get("status"))).toEqual([
      "waiting",
    ]);
    faceted.unmount();

    const all = renderWithApi(<SessionsListScreen />, {
      routes: routes(),
      path: "/sessions?period=24 h&repo=demo",
    });
    await screen.findByText("/asker");
    const asked = sessionRequests(all.requests);
    expect(asked.every((url) => url.searchParams.get("repo") === "demo")).toBe(true);
    expect(
      asked
        .filter((url) => url.searchParams.has("from"))
        .map((url) => url.searchParams.get("status")),
    ).toEqual(["ended"]);
  });
});

describe("SessionsListScreen select-all-section", () => {
  it("selects and clears only its own section's rows", async () => {
    const rows = [...SAMPLE, one(4, "live", "runner-2")];
    renderWithApi(<SessionsListScreen />, {
      routes: routes(aSessionsByStatus(rows)),
      path: "/sessions",
    });
    await screen.findByText("/runner-2");

    const waiting = screen.getByRole("table", { name: "Waiting sessions" });
    const live = screen.getByRole("table", { name: "Live sessions" });
    fireEvent.click(within(waiting).getByRole("checkbox", { name: "Select row" }));
    fireEvent.click(within(live).getByRole("checkbox", { name: "Select all" }));
    expect(screen.getByText("Selected", { exact: false })).toHaveTextContent("Selected 3");
    expect(within(live).getByRole("checkbox", { name: "Select all" })).toBeChecked();
    expect(
      within(screen.getByRole("table", { name: "Ended or failed sessions" })).getByRole(
        "checkbox",
        { name: "Select all" },
      ),
    ).not.toBeChecked();

    fireEvent.click(within(live).getByRole("checkbox", { name: "Select all" }));
    expect(screen.getByText("Selected", { exact: false })).toHaveTextContent("Selected 1");
    expect(within(waiting).getByRole("checkbox", { name: "Select row" })).toBeChecked();
    expect(
      within(live)
        .getAllByRole("checkbox", { name: "Select row" })
        .map((box) => (box as HTMLInputElement).checked),
    ).toEqual([false, false]);
  });
});

/** Waits until `count` session requests were sent, then a beat more, so a duplicate would show. */
async function settled(requests: Request[], count: number) {
  await waitFor(() => {
    expect(sessionRequests(requests).length).toBeGreaterThanOrEqual(count);
  });
  await new Promise((resolve) => setTimeout(resolve, 50));
  return sessionRequests(requests);
}

describe("SessionsListScreen filter-requests", () => {
  it("asks only Ended again on a period change, and every section once on a repo filter", async () => {
    const { requests } = renderWithApi(<SessionsListScreen />, {
      routes: routes(),
      path: "/sessions",
    });
    await screen.findByText("/asker");
    const first = await settled(requests, 4);
    expect(first).toHaveLength(4);

    fireEvent.click(screen.getByRole("button", { name: "24 h" }));
    const afterPeriod = (await settled(requests, 5)).slice(4);
    expect(afterPeriod.map((url) => url.searchParams.get("status"))).toEqual(["ended"]);
    expect(afterPeriod[0]?.searchParams.has("from")).toBe(true);
    // The period filters Ended only, and the count line says so.
    expect(await screen.findByText(/· Ended: last 24 h ·/)).toBeInTheDocument();

    const repo = screen.getByRole("textbox", { name: "Repo" });
    fireEvent.change(repo, { target: { value: "demo" } });
    fireEvent.blur(repo);
    const afterRepo = (await settled(requests, 9)).slice(5);
    expect(afterRepo.map((url) => url.searchParams.get("status")).sort()).toEqual([
      "ended",
      "idle",
      "live",
      "waiting",
    ]);
    expect(afterRepo.every((url) => url.searchParams.get("repo") === "demo")).toBe(true);
  });
});

describe("SessionsListScreen keep-previous", () => {
  it("keeps the shown sections while a sort refetches; a hidden empty one stays hidden", async () => {
    // The sorted pages never arrive, so the screen stays mid-refetch.
    const { requests } = renderWithApi(<SessionsListScreen />, {
      routes: routes((request: Request) =>
        new URL(request.url).searchParams.get("sort") === "-cost"
          ? "pending"
          : aSessionsByStatus(SAMPLE)(request),
      ),
      path: "/sessions",
    });
    await screen.findByText("/asker");
    expect(headers()).toEqual(["Waiting · 1", "Live · 1", "Ended or failed · 1"]);

    const live = screen.getByRole("table", { name: "Live sessions" });
    fireEvent.click(within(live).getByRole("button", { name: /^Cost/ }));
    await waitFor(() => {
      expect(
        sessionRequests(requests).filter((url) => url.searchParams.get("sort") === "-cost"),
      ).toHaveLength(4);
    });
    // Mid-refetch: the same sections and rows, no Idle placeholder, no skeleton.
    expect(headers()).toEqual(["Waiting · 1", "Live · 1", "Ended or failed · 1"]);
    expect(screen.getByText("/runner")).toBeInTheDocument();
  });

  it("marks a section busy and hides Load more while it shows the previous pages", async () => {
    renderWithApi(<SessionsListScreen />, {
      routes: routes((request: Request) =>
        new URL(request.url).searchParams.get("sort") === "-cost"
          ? "pending"
          : aSessionsByStatus(SAMPLE, { next_cursor: "c2" })(request),
      ),
      path: "/sessions",
    });
    await screen.findByText("/runner");
    const section = screen.getByRole("region", { name: /^Live/ });
    expect(section).not.toHaveAttribute("aria-busy");
    expect(within(section).getByRole("button", { name: "Load more" })).toBeInTheDocument();

    fireEvent.click(within(section).getByRole("button", { name: /^Cost/ }));
    await waitFor(() => {
      expect(section).toHaveAttribute("aria-busy", "true");
    });
    expect(within(section).getByText("Updating…")).toBeInTheDocument();
    // A Load more on placeholder pages would refetch page 1 instead of the next one.
    expect(within(section).queryByRole("button", { name: "Load more" })).toBeNull();
  });
});

/**
 * A browser-like layout: a scroll element is as tall as its table's rows (40 px each), capped by its
 * own max-height, so an unbounded section measures its full content and a bounded one its window.
 */
function layOutTables() {
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(function (
    this: HTMLElement,
  ) {
    const table = this.style.overflow === "auto" ? this.querySelector("table") : null;
    if (!table) return 0;
    const rows = Number(table.getAttribute("aria-rowcount") ?? table.querySelectorAll("tr").length);
    const cap = this.style.maxHeight ? Number.parseFloat(this.style.maxHeight) : Infinity;
    return Math.min(rows * 40, cap);
  });
}

describe("SessionsListScreen table-sections", () => {
  it("gives each section its own table with the chosen columns, density and sort", async () => {
    const { router, requests } = renderWithApi(<SessionsListScreen />, {
      routes: routes(),
      path: "/sessions",
    });
    await screen.findByText("/asker");

    const tables = screen
      .getAllByRole("table")
      .map(
        (table) => table.getAttribute("aria-label") ?? table.querySelector("caption")?.textContent,
      );
    expect(tables).toEqual(["Waiting sessions", "Live sessions", "Ended or failed sessions"]);
    fireEvent.click(screen.getByRole("button", { name: "Columns" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Model" }));
    expect(screen.getAllByRole("columnheader", { name: "Model" })).toHaveLength(3);
    expect(document.querySelectorAll('[data-density="compact"]')).toHaveLength(3);

    const live = screen.getByRole("table", { name: "Live sessions" });
    fireEvent.click(within(live).getByRole("button", { name: /^Cost/ }));
    expect(router.state.location.search).toBe("?sort=-cost");
    await waitFor(() => {
      expect(
        sessionRequests(requests)
          .filter((url) => url.searchParams.get("sort") === "-cost")
          .map((url) => url.searchParams.get("status"))
          .sort(),
      ).toEqual(["ended", "idle", "live", "waiting"]);
    });
  });

  it("pages one section with Load more and virtualises a section past 100 rows only", async () => {
    const rows = [...many(100, "live", 1000), ...many(150, "ended", 2000)];
    const { requests } = renderWithApi(<SessionsListScreen />, {
      routes: routes((request: Request) => {
        const url = new URL(request.url);
        if (url.searchParams.get("cursor") === "e2") return aPage([one(9, "ended", "older")]);
        return aSessionsByStatus(rows, {
          next_cursor: url.searchParams.get("status") === "ended" ? "e2" : null,
        })(request);
      }),
      path: "/sessions",
    });
    await screen.findByText("/live-0");

    const live = screen.getByRole("table", { name: "Live sessions" });
    const ended = screen.getByRole("table", { name: "Ended or failed sessions" });
    // 100 rows render whole (plus the header row); 150 render a window.
    expect(within(live).getAllByRole("row")).toHaveLength(101);
    expect(ended.querySelectorAll("tbody tr[data-index]").length).toBeLessThan(150);

    const endedRegion = screen.getByRole("region", { name: /^Ended or failed/ });
    expect(
      within(screen.getByRole("region", { name: /^Live/ })).queryByRole("button", {
        name: "Load more",
      }),
    ).toBeNull();
    fireEvent.click(within(endedRegion).getByRole("button", { name: "Load more" }));
    await waitFor(() => {
      expect(
        sessionRequests(requests)
          .filter((url) => url.searchParams.get("cursor") === "e2")
          .map((url) => url.searchParams.get("status")),
      ).toEqual(["ended"]);
    });
    expect(await within(endedRegion).findByText("Showing all 151")).toBeInTheDocument();
    // 250 rendered rows: slow under a loaded CPU, not a budget.
  }, 20_000);

  describe("virtual-bounded", () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it("bounds and virtualises a section past 100 rows only, in a measured layout", async () => {
      layOutTables();
      const rows = [...many(100, "live", 1000), ...many(101, "ended", 3000)];
      renderWithApi(<SessionsListScreen />, {
        routes: routes(aSessionsByStatus(rows)),
        path: "/sessions",
      });
      await screen.findByText("/live-0");

      const live = screen.getByRole("table", { name: "Live sessions" });
      const ended = screen.getByRole("table", { name: "Ended or failed sessions" });
      // 100 rows stay in the page flow, whole; 101 get a bounded, focusable scroll region.
      expect(within(live).getAllByRole("row")).toHaveLength(101);
      expect(screen.queryByRole("region", { name: "Scrollable live sessions" })).toBeNull();
      const scroller = screen.getByRole("region", { name: "Scrollable ended or failed sessions" });
      expect(scroller).toHaveAttribute("tabindex", "0");
      expect(scroller.style.maxHeight).toBe("640px");
      expect(scroller).toContainElement(ended);
      // 640 px of 40 px rows plus overscan, not all 101.
      expect(ended.querySelectorAll("tbody tr[data-index]").length).toBeLessThan(50);
    }, 20_000);
  });
});
