import { describe, expect, it } from "vitest";

import { aFeature, aRun, aSession, aSessionLabel } from "../../testing/builders";
import { ticketsOf } from "../tickets/model";
import { recentFeatures, recentTickets, runsInOrder } from "./model";

const NOW = Date.parse("2026-10-21T12:00:00Z");
const hoursAgo = (h: number) => new Date(NOW - h * 3_600_000).toISOString();

describe("recentFeatures", () => {
  it("AC-273.15 lists a feature when a session on one of its issues was active this week, newest first", () => {
    const sessions = [
      aSession({
        last_activity_at: hoursAgo(2),
        cost_usd: "1.50",
        label: aSessionLabel({ issue: "acme-2" }),
      }),
      aSession({
        last_activity_at: hoursAgo(5),
        cost_usd: "0.50",
        label: aSessionLabel({ issue: "ACME-2" }),
      }),
      aSession({ last_activity_at: hoursAgo(1), label: aSessionLabel({ issue: "ACME-9" }) }),
      aSession({ last_activity_at: hoursAgo(24 * 10), label: aSessionLabel({ issue: "ACME-5" }) }),
    ];
    const rows = recentFeatures(
      [
        aFeature({ slug: "export", issues: ["ACME-2"] }),
        aFeature({ slug: "search", issues: ["ACME-9"] }),
        aFeature({ slug: "stale", issues: ["ACME-5"] }),
      ],
      sessions,
      NOW,
    );

    expect(rows.map((r) => r.feature.slug)).toEqual(["search", "export"]);
    expect(rows[1]?.costUsd).toBe(2);
    expect(rows[1]?.lastActivityAt).toBe(hoursAgo(2));
  });
});

describe("recentTickets", () => {
  it("AC-427.22 leaves out only the issues the agents' runs list shows, not every issue that ever ran", () => {
    const sessions = [
      aSession({
        last_activity_at: hoursAgo(1),
        label: aSessionLabel({ issue: "ACME-7", workflows: ["/fix"] }),
      }),
      aSession({
        last_activity_at: hoursAgo(2),
        label: aSessionLabel({ issue: "ACME-8", workflows: ["/fix"] }),
      }),
    ];
    const runs = [
      aRun({ id: "live", stage: "IMPLEMENTING", issue: { key: "ACME-7", title: "x", url: null } }),
      aRun({
        id: "old",
        stage: "REPORTED",
        ended_at: hoursAgo(24 * 30),
        issue: { key: "ACME-8", title: "y", url: null },
      }),
    ];
    const shown = new Set(
      runsInOrder(runs, NOW).ordered.flatMap((r) => (r.issue ? [r.issue.key] : [])),
    );

    const rows = recentTickets(ticketsOf(sessions, new Set()), shown, NOW);

    expect(rows.map((r) => r.issue)).toEqual(["ACME-8"]);
  });
});
