import { beforeEach, describe, expect, it } from "vitest";

import { openEditDraft, saveDraft, storedDraft } from "./studioDrafts";

const TARGET = { kind: "skill" as const, source: "hub-workflow", name: "feature" };

beforeEach(() => {
  window.localStorage.clear();
});

describe("studio drafts", () => {
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

  it("does not reopen a published edit", () => {
    saveDraft(
      "skill-aaa111",
      { project: "demo", kind: "skill" },
      { target: TARGET, published: true },
    );

    expect(openEditDraft("demo", TARGET)).toBeNull();
  });
});
