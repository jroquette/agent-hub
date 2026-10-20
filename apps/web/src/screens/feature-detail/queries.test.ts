import { describe, expect, it } from "vitest";

import type { components } from "../../api/schema";
import { pickFeatureSession } from "./queries";

type AgentSession = components["schemas"]["AgentSession"];

const session = (id: string, created_at: string) => ({ id, created_at }) as AgentSession;

describe("pickFeatureSession", () => {
  it("picks the first session that wrote the spec", () => {
    const spec = [
      session("late", "2026-10-20T10:00:00Z"),
      session("first", "2026-10-19T10:00:00Z"),
    ];
    expect(pickFeatureSession([spec, [session("plan", "2026-10-18T10:00:00Z")]])?.id).toBe("first");
  });

  it("falls back to the next record with a writer", () => {
    expect(pickFeatureSession([[], undefined, [session("plan", "2026-10-18T10:00:00Z")]])?.id).toBe(
      "plan",
    );
  });

  it("is null when no session wrote a record", () => {
    expect(pickFeatureSession([undefined, [], []])).toBeNull();
  });
});
