import { beforeEach, describe, expect, it } from "vitest";

import { forgetDraft, openDrafts, openEditDraft, saveDraft, storedDraft } from "./studioDrafts";

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

const TARGET = { kind: "skill" as const, source: "hub-workflow", name: "feature" };

describe("studioDrafts edit drafts", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("finds the open edit draft of an item, so a second Edit reopens it", () => {
    saveDraft("skill-aaa111", { project: "demo", kind: "skill" }, { target: TARGET });

    expect(openEditDraft("demo", TARGET)?.draftId).toBe("skill-aaa111");
    expect(openEditDraft("demo", { ...TARGET, name: "fix" })).toBeNull();
    expect(openEditDraft("other", TARGET)).toBeNull();
  });

  it("keeps the edit target when a later save does not name it", () => {
    saveDraft("skill-aaa111", { project: "demo", kind: "skill" }, { target: TARGET });
    saveDraft("skill-aaa111", { project: "demo", kind: "skill" }, { sessionId: "s1" });

    expect(storedDraft("skill-aaa111")).toMatchObject({ target: TARGET, sessionId: "s1" });
  });

  it("skips a stored edit draft whose target is not an item reference", () => {
    saveDraft("skill-aaa111", { project: "demo", kind: "skill" }, { target: TARGET });
    const stored = JSON.parse(window.localStorage.getItem("ah.studio.drafts") ?? "[]") as object[];
    window.localStorage.setItem(
      "ah.studio.drafts",
      JSON.stringify([{ ...stored[0], target: { kind: "skill", name: 3 } }]),
    );

    expect(openEditDraft("demo", TARGET)).toBeNull();
  });

  it("does not reopen a published edit", () => {
    saveDraft(
      "skill-aaa111",
      { project: "demo", kind: "skill" },
      { target: TARGET, published: true },
    );

    expect(openEditDraft("demo", TARGET)).toBeNull();
  });
});
