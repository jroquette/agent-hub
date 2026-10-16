import { describe, expect, it } from "vitest";

import { BRAIN_NOTE_STARTERS, learningDiscussTarget } from "./discussLearning";

const base = {
  id: "l-1",
  project: "tipple",
  text: "Two Stripe clients",
  path: "brain/_inbox/two-stripe.md",
  recordedPath: "brain/_inbox/two-stripe.md",
  inBrain: false,
  proposed: true,
};

describe("learningDiscussTarget", () => {
  it("opens on a proposal with its note, the /learn bar and a verdict starter", () => {
    const target = learningDiscussTarget(base);

    expect(target.key).toBe("learning:tipple:l-1");
    expect(target.path).toBe("brain/_inbox/two-stripe.md");
    expect(target.openOnArrive).toBe(true);
    expect(target.brief).toContain("non-obvious");
    expect(target.brief).toContain("edit the note file in place");
    expect(target.starters?.[0]?.label).toBe("Is this worth keeping?");
  });

  it("asks whether a note already in the brain is still true, without opening by itself", () => {
    const target = learningDiscussTarget({
      ...base,
      path: "brain/learnings/two-stripe.md",
      inBrain: true,
      proposed: false,
    });

    expect(target.openOnArrive).toBe(false);
    expect(target.brief).toContain("already in the brain");
    expect(target.starters).toBe(BRAIN_NOTE_STARTERS);
  });

  it("says the note is missing and offers to write it again or drop it", () => {
    const target = learningDiscussTarget({ ...base, path: null });

    expect(target.path).toBeNull();
    expect(target.brief).toContain("missing from the hub checkout");
    expect(target.brief).toContain("brain/_inbox/two-stripe.md");
  });
});
