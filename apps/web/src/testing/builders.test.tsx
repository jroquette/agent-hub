import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useApi } from "../lib/api";
import {
  aCollectorStatus,
  aFeature,
  aFeatureDetail,
  aFinding,
  aHub,
  aLearning,
  aLiveTile,
  aNeedsYouItem,
  anActivityItem,
  anApproval,
  anId,
  aPage,
  aProblem,
  aProjectDetail,
  aProjectNow,
  aProjectSummary,
  aRepo,
  aRun,
  aSearchHit,
  aSession,
  aSessionCost,
  aSessionFile,
  aSessionSummary,
  aSettings,
  aStreamCounts,
  aTimelineEvent,
  at,
  manyEvents,
  renderWithApi,
  stubApi,
} from "./builders";

describe("builders", () => {
  it("build every response schema with overrides", () => {
    const bodies = [
      aSession({ status: "ended" }),
      aTimelineEvent({ seq: 3 }),
      aRun({ stage: "FAILED" }),
      anApproval({ status: "approved" }),
      aLearning({ status: "accepted" }),
      aLiveTile({ group: "waiting" }),
      aProjectSummary({ name: "loki-trader" }),
      aProjectDetail(),
      aProjectNow(),
      aRepo(),
      aFeature(),
      aFeatureDetail(),
      aFinding({ severity: "warning" }),
      aHub({ valid: false }),
      aCollectorStatus(),
      aSettings(),
      aNeedsYouItem(),
      anActivityItem(),
      aSearchHit(),
      aSessionSummary(),
      aSessionCost(),
      aSessionFile(),
      aStreamCounts(),
    ];

    expect(bodies).toHaveLength(23);
    expect(aSession({ status: "ended" }).status).toBe("ended");
    expect(aTimelineEvent({ seq: 3 }).event_id).toBe(anId(3, "0192aaaa"));
    expect(aPage([1, 2])).toEqual({ items: [1, 2], next_cursor: null, total_estimate: 2 });
  });

  it("makes n ordered synthetic events of one session", () => {
    const events = manyEvents(5000);

    expect(events).toHaveLength(5000);
    expect(events[4999]?.seq).toBe(5000);
    expect(new Set(events.map((e) => e.event_id)).size).toBe(5000);
    expect(events[5]?.payload).toMatchObject({ turn: 2 });
  });

  it("writes UTC timestamps relative to T0", () => {
    expect(at(90)).toBe("2026-10-11T14:01:30.000Z");
  });
});

describe("stubApi", () => {
  it("answers bodies, problems, functions, methods and unknown routes", async () => {
    stubApi({
      "/a": { ok: true },
      "/b": aProblem({ status: 409, title: "Conflict" }),
      "/c": (request: Request) => ({ method: request.method }),
      "POST /d": { created: true },
    });

    const a = await fetch("http://localhost/a");
    const b = await fetch("http://localhost/b");
    const c = await fetch("http://localhost/c");
    const d = await fetch("http://localhost/d", { method: "POST" });
    const e = await fetch("http://localhost/e");

    expect(await a.json()).toEqual({ ok: true });
    expect(b.status).toBe(409);
    expect(b.headers.get("content-type")).toBe("application/problem+json");
    expect(await c.json()).toEqual({ method: "GET" });
    expect(d.status).toBe(201);
    expect(await e.json()).toMatchObject({ detail: "No stub for GET /e" });
  });
});

function HubCount() {
  const hubs = useApi("/api/v1/hubs");
  if (hubs.isPending) return <p>loading</p>;
  return <p>{hubs.data?.items.length ?? hubs.error?.title}</p>;
}

describe("renderWithApi", () => {
  it("renders against the stubbed API and records requests", async () => {
    const { requests } = renderWithApi(<HubCount />, {
      routes: { "/api/v1/hubs": aPage([aHub()]) },
    });

    expect(await screen.findByText("1")).toBeInTheDocument();
    expect(requests).toHaveLength(1);
  });

  it("keeps a pending route loading", () => {
    renderWithApi(<HubCount />, { routes: { "/api/v1/hubs": "pending" } });

    expect(screen.getByText("loading")).toBeInTheDocument();
  });

  it("finds the streams a render opened", () => {
    const { stream } = renderWithApi(<p>x</p>);
    new EventSource("/api/v1/live-sessions/stream");

    expect(stream("/api/v1/live-sessions/stream").url).toBe("/api/v1/live-sessions/stream");
    expect(() => stream("/api/v1/nothing")).toThrow("No EventSource opened for /api/v1/nothing");
  });
});
