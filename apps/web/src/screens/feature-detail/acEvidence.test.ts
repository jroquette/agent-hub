import { describe, expect, it } from "vitest";

import { parseEvidence, resultLine, resultPassed } from "./acEvidence";

const WHOLE_FEATURE =
  "Tipple_API@780917525 (= merged b811fca72, PR #2374), 2026-10-16, whole-feature eval: features.json verification command verbatim (DataMode=LOCAL_DEV prefix; DB__* to LOCAL test Postgres localhost:6432; worktree PYTHONPATH) exit 0, 10 passed, 42 deselected; red on merge base 38290da11 (ImportError on WebshopBusinessBillingVirtualBankAccount). evals/feature.md";

describe("parseEvidence", () => {
  it("reads the commit, PR, date, result, red-on-base, environment and eval file", () => {
    const facts = parseEvidence(WHOLE_FEATURE);

    expect(facts.commits).toEqual([{ repo: "Tipple_API", sha: "780917525" }]);
    expect(facts.prs).toEqual([{ repo: null, number: "2374" }]);
    expect(facts.date).toBe("2026-10-16");
    expect(resultLine(facts.result)).toBe("exit 0 · 10 passed · 42 deselected");
    expect(resultPassed(facts.result)).toBe(true);
    expect(facts.redOnBase).toBe(
      "red on merge base 38290da11 (ImportError on WebshopBusinessBillingVirtualBankAccount)",
    );
    expect(facts.environments).toEqual(["LOCAL_DEV"]);
    expect(facts.evalFiles).toEqual(["evals/feature.md"]);
    expect(facts.standing).toBeNull();
  });

  it("reads an eval named by delivery and a commit without a repo", () => {
    const facts = parseEvidence(
      "eval tip-1562 @1682f1f06: exit 0, 7 passed (presignedUrl …); 3 new tests red on base 78091752",
    );

    expect(facts.evalDeliveries).toEqual(["tip-1562"]);
    expect(facts.commits).toEqual([{ repo: null, sha: "1682f1f06" }]);
    expect(facts.redOnBase).toBe("3 new tests red on base 78091752");
  });

  it("says a failing result is not green", () => {
    const facts = parseEvidence("make type-check exit 2 with 6 errors, 3 failed");

    expect(resultPassed(facts.result)).toBe(false);
  });

  it("marks superseded evidence and a repo-qualified PR", () => {
    const facts = parseEvidence(
      "superseded 2026-10-12 by owner decision; Tipple_API#2368 closed without merging",
    );

    expect(facts.standing).toBe("superseded");
    expect(facts.prs).toEqual([{ repo: "Tipple_API", number: "2368" }]);
    expect(facts.result).toBeNull();
  });

  it("notices a manual check that is still an owner step, and ignores AC ids as issues", () => {
    const facts = parseEvidence("covered with AC-15 by TIP-1552; manual check still an owner step");

    expect(facts.ownerCheckOpen).toBe(true);
    expect(facts.issues).toEqual(["TIP-1552"]);
  });

  it("returns empty facts for plain text", () => {
    const facts = parseEvidence("eval.md §Owner steps");

    expect(facts.result).toBeNull();
    expect(facts.commits).toEqual([]);
    expect(facts.date).toBeNull();
  });
});
