import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  aNeedsYouItem,
  anActivityItem,
  aPage,
  aProblem,
  aProjectSummary,
  renderWithApi,
  type ApiRoutes,
} from "../testing/builders";
import { apiKey, createQueryClient, useApi } from "./api";
import { ScreenReadProvider } from "./screenRead";

// Home's read for All projects and the three resources it stands in for, under the keys Home's
// queries read (activity: its first page of 20). The app's query client throughout: under the
// test client's staleTime 0 a seeded query would fetch anyway.
const PORTFOLIO = "/api/v1/screens/portfolio";
const ALL = { query: { project: null } };
const FIRST_PAGE = { query: { project: null, limit: 20 } };
const projectsKey = apiKey("/api/v1/projects", ALL);
const needsKey = apiKey("/api/v1/needs-you", ALL);
const activityKey = apiKey("/api/v1/activity", FIRST_PAGE);
const RESOURCES = ["/api/v1/activity", "/api/v1/needs-you", "/api/v1/projects"];

const read = {
  projects: aPage([aProjectSummary({ name: "read-project" })]),
  needs_you: aPage([aNeedsYouItem({ verb: "Read need" })]),
  activity: aPage([anActivityItem({ text: "Read activity" })]),
};
const resources: ApiRoutes = {
  "/api/v1/projects": aPage([aProjectSummary({ name: "route-project" })]),
  "/api/v1/needs-you": aPage([aNeedsYouItem({ verb: "Route need" })]),
  "/api/v1/activity": aPage([anActivityItem({ text: "Route activity" })]),
};

/** Home's three regions: each query's items, or "waiting" before it has any. */
function Regions() {
  const projects = useApi("/api/v1/projects", ALL).data?.items.map((item) => item.name);
  const needs = useApi("/api/v1/needs-you", ALL).data?.items.map((item) => item.verb);
  const activity = useApi("/api/v1/activity", FIRST_PAGE).data?.items.map((item) => item.text);
  return (
    <>
      <p>{`projects: ${projects?.join(", ") ?? "waiting"}`}</p>
      <p>{`needs: ${needs?.join(", ") ?? "waiting"}`}</p>
      <p>{`activity: ${activity?.join(", ") ?? "waiting"}`}</p>
    </>
  );
}

function Home({ enabled = true, children }: { enabled?: boolean; children: ReactNode }) {
  return (
    <ScreenReadProvider
      path={PORTFOLIO}
      params={ALL}
      seeds={(data) => [
        [projectsKey, data.projects],
        [needsKey, data.needs_you],
        [activityKey, data.activity],
      ]}
      enabled={enabled}
    >
      {children}
    </ScreenReadProvider>
  );
}

/** Home's activity after "Load more": the same path with another page size. */
function MoreActivity() {
  const more = useApi("/api/v1/activity", { query: { project: null, limit: 40 } });
  return <p>{`more activity: ${more.data?.items[0]?.text ?? "waiting"}`}</p>;
}

/** Home with its read's coverage on or off, as Sessions switches it when a filter is set. */
function Filterable({ covered, children }: { covered: boolean; children: ReactNode }) {
  const [enabled, setEnabled] = useState(covered);
  return (
    <>
      <button
        onClick={() => {
          setEnabled((on) => !on);
        }}
      >
        {enabled ? "Set a filter" : "Clear the filter"}
      </button>
      <Home enabled={enabled}>{children}</Home>
    </>
  );
}

/** Mounts Home once "Open Home" is pressed, as a visit does. */
function Visit({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  if (open) return <>{children}</>;
  return (
    <button
      onClick={() => {
        setOpen(true);
      }}
    >
      Open Home
    </button>
  );
}

/** Holds the screen read's answer until `release()`; `startedAt` is when it was asked. */
function holdScreenRead(): { release: () => void; startedAt: () => number | null } {
  const fetchMock = vi.mocked(globalThis.fetch);
  const answer = fetchMock.getMockImplementation();
  if (answer === undefined) throw new Error("holdScreenRead: render first");
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let startedAt: number | null = null;
  fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : String(input);
    if (new URL(url, window.location.origin).pathname !== PORTFOLIO) return answer(input, init);
    startedAt = Date.now();
    return gate.then(() => answer(input, init));
  });
  return {
    release: () => {
      release();
    },
    startedAt: () => startedAt,
  };
}

/** Lets a fetch that the last answer would start go out before the calls are read. */
async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));
  });
}

describe("ScreenReadProvider", () => {
  it("seeds the covered queries so they send no request", async () => {
    const { calls } = renderWithApi(
      <Home>
        <Regions />
      </Home>,
      { routes: { [PORTFOLIO]: read, ...resources }, queryClient: createQueryClient() },
    );

    expect(await screen.findByText("projects: read-project")).toBeInTheDocument();
    expect(await screen.findByText("needs: Read need")).toBeInTheDocument();
    expect(await screen.findByText("activity: Read activity")).toBeInTheDocument();
    await settle();
    expect(calls()).toEqual([PORTFOLIO]);
  });

  it("lets each covered query read its resource when the screen read fails", async () => {
    const { calls } = renderWithApi(
      <Home>
        <Regions />
      </Home>,
      {
        routes: { [PORTFOLIO]: aProblem({ status: 500, title: "Internal error" }), ...resources },
        queryClient: createQueryClient(),
      },
    );

    expect(await screen.findByText("projects: route-project")).toBeInTheDocument();
    expect(await screen.findByText("needs: Route need")).toBeInTheDocument();
    expect(await screen.findByText("activity: Route activity")).toBeInTheDocument();
    // The covered queries waited for the read's answer before reading their routes.
    expect(calls()[0]).toBe(PORTFOLIO);
    expect([...calls().slice(1)].sort()).toEqual(RESOURCES);
  });

  it("lets each covered query read its resource when the screen read does not answer in 5 s", async () => {
    vi.useFakeTimers();
    try {
      const { calls, requests } = renderWithApi(
        <Home>
          <Regions />
        </Home>,
        { routes: { [PORTFOLIO]: "pending", ...resources }, queryClient: createQueryClient() },
      );

      await act(async () => {
        await vi.advanceTimersByTimeAsync(4_900);
      });
      expect(calls()).toEqual([PORTFOLIO]);
      expect(screen.getByText("projects: waiting")).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(200);
      });
      expect(screen.getByText("projects: route-project")).toBeInTheDocument();
      expect(screen.getByText("needs: Route need")).toBeInTheDocument();
      expect(screen.getByText("activity: Route activity")).toBeInTheDocument();
      expect([...calls()].sort()).toEqual([...RESOURCES, PORTFOLIO]);
      // The read that did not answer is given up.
      const asked = requests.find((request) => new URL(request.url).pathname === PORTFOLIO);
      expect(asked?.signal.aborted).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("never overwrites an entry newer than the screen read", async () => {
    const user = userEvent.setup();
    const { queryClient } = renderWithApi(
      <Visit>
        <Home>
          <Regions />
        </Home>
      </Visit>,
      { routes: { [PORTFOLIO]: read, ...resources }, queryClient: createQueryClient() },
    );
    // Written before the visit, so older than the read: its part replaces it.
    queryClient.setQueryData(projectsKey, aPage([aProjectSummary({ name: "older-project" })]));
    const olderAt = Date.now();
    const held = holdScreenRead();
    await waitFor(() => {
      expect(Date.now()).toBeGreaterThan(olderAt);
    });

    await user.click(screen.getByRole("button", { name: "Open Home" }));
    expect(screen.getByText("projects: older-project")).toBeInTheDocument();
    await waitFor(() => {
      expect(held.startedAt()).not.toBeNull();
    });
    const askedAt = held.startedAt() ?? Infinity;
    await waitFor(() => {
      expect(Date.now()).toBeGreaterThan(askedAt);
    });
    // Written while the read is on its way, so newer than it: it stays.
    act(() => {
      queryClient.setQueryData(needsKey, aPage([aNeedsYouItem({ verb: "Newer need" })]));
    });
    held.release();

    expect(await screen.findByText("projects: read-project")).toBeInTheDocument();
    expect(await screen.findByText("activity: Read activity")).toBeInTheDocument();
    await settle();
    expect(screen.getByText("needs: Newer need")).toBeInTheDocument();
  });

  it("leaves a query it does not cover alone", async () => {
    const { requests } = renderWithApi(
      <Home>
        <Regions />
        <MoreActivity />
      </Home>,
      { routes: { [PORTFOLIO]: "pending", ...resources }, queryClient: createQueryClient() },
    );

    // The same path with another page size is another key: it reads its route at once.
    expect(await screen.findByText("more activity: Route activity")).toBeInTheDocument();
    expect(screen.getByText("projects: waiting")).toBeInTheDocument();
    expect(screen.getByText("activity: waiting")).toBeInTheDocument();
    const asked = requests.map((request) => {
      const url = new URL(request.url);
      return [url.pathname, url.searchParams.get("limit")];
    });
    expect(asked.filter(([path]) => path !== PORTFOLIO)).toEqual([["/api/v1/activity", "40"]]);
  });

  it("fetches nothing and covers nothing while disabled, even once enabled later", async () => {
    const user = userEvent.setup();
    const { calls } = renderWithApi(
      <Filterable covered={false}>
        <Regions />
      </Filterable>,
      { routes: { [PORTFOLIO]: read, ...resources }, queryClient: createQueryClient() },
    );

    expect(await screen.findByText("projects: route-project")).toBeInTheDocument();
    expect(await screen.findByText("needs: Route need")).toBeInTheDocument();
    expect(await screen.findByText("activity: Route activity")).toBeInTheDocument();
    expect([...calls()].sort()).toEqual(RESOURCES);

    // A visit that began uncovered stays uncovered: no read, the routes' answers kept.
    await user.click(screen.getByRole("button", { name: "Clear the filter" }));
    await settle();
    expect([...calls()].sort()).toEqual(RESOURCES);
    expect(screen.getByText("projects: route-project")).toBeInTheDocument();
  });

  it("keeps its children mounted and stops covering when disabled later", async () => {
    const user = userEvent.setup();
    const { calls } = renderWithApi(
      <Filterable covered>
        <input aria-label="Period anchor" />
        <Regions />
      </Filterable>,
      { routes: { [PORTFOLIO]: "pending", ...resources }, queryClient: createQueryClient() },
    );
    await user.type(screen.getByRole("textbox", { name: "Period anchor" }), "2026-10-11");
    expect(screen.getByText("projects: waiting")).toBeInTheDocument();
    expect(calls()).toEqual([PORTFOLIO]);

    await user.click(screen.getByRole("button", { name: "Set a filter" }));

    expect(await screen.findByText("projects: route-project")).toBeInTheDocument();
    expect(await screen.findByText("needs: Route need")).toBeInTheDocument();
    expect(await screen.findByText("activity: Route activity")).toBeInTheDocument();
    // The screen's own state survives: the children were not mounted again.
    expect(screen.getByRole("textbox", { name: "Period anchor" })).toHaveValue("2026-10-11");
  });
});
