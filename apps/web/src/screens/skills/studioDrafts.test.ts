import { beforeEach, describe, expect, it } from "vitest";

import { forgetDraft, openDrafts, saveDraft, storedDraft } from "./studioDrafts";

const KEY = "ah.studio.drafts";
const AT = new Date("2026-10-11T14:00:00.000Z");

describe("studioDrafts", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("keeps a saved draft, lists it until published and forgets it", () => {
    saveDraft("skill-abc123", { project: "demo", kind: "skill" }, { sessionId: "s1" }, AT);
    saveDraft("skill-abc123", { project: "demo", kind: "skill" }, { name: "changelog" }, AT);

    expect(storedDraft("skill-abc123")).toEqual({
      draftId: "skill-abc123",
      project: "demo",
      kind: "skill",
      sessionId: "s1",
      name: "changelog",
      updatedAt: AT.toISOString(),
      published: false,
    });
    expect(openDrafts("demo").map((d) => d.draftId)).toEqual(["skill-abc123"]);
    expect(openDrafts("other")).toEqual([]);

    saveDraft("skill-abc123", { project: "demo", kind: "skill" }, { published: true }, AT);
    expect(openDrafts("demo")).toEqual([]);

    forgetDraft("skill-abc123");
    expect(storedDraft("skill-abc123")).toBeNull();
  });

  it("skips stored entries that are not drafts, and storage that is not JSON", () => {
    const kept = {
      draftId: "agent-abc123",
      project: "demo",
      kind: "agent",
      sessionId: null,
      name: null,
      updatedAt: AT.toISOString(),
      published: false,
    };
    window.localStorage.setItem(
      KEY,
      JSON.stringify([null, 3, { draftId: "x" }, { ...kept, kind: "plugin" }, kept]),
    );
    expect(openDrafts("demo")).toEqual([kept]);

    window.localStorage.setItem(KEY, "{not json");
    expect(openDrafts("demo")).toEqual([]);
  });
});
