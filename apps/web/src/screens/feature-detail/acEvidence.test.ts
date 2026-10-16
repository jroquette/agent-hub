import { describe, expect, it } from "vitest";

import {
  parseEvidence,
  resultExplanation,
  resultHeadline,
  resultLine,
  resultPassed,
} from "./acEvidence";

const WHOLE_FEATURE =
  "demo-api@780917525 (= merged b811fca72, PR #74), 2026-10-16, whole-feature eval: features.json verification command verbatim (APP_MODE=test prefix; a local test database) exit 0, 10 passed, 42 deselected; red on merge base 38290da11 (ImportError on ExportRoute). evals/feature.md";

describe("parseEvidence", () => {
  it("reads the commit, PR, date, result, red-on-base, environment and eval file", () => {
    const facts = parseEvidence(WHOLE_FEATURE);

    expect(facts.commits).toEqual([{ repo: "demo-api", sha: "780917525" }]);
    expect(facts.prs).toEqual([{ repo: null, number: "74" }]);
    expect(facts.date).toBe("2026-10-16");
    expect(resultLine(facts.result)).toBe("exit 0 · 10 passed · 42 deselected");
    expect(resultPassed(facts.result)).toBe(true);
    expect(facts.redOnBase).toBe("red on merge base 38290da11 (ImportError on ExportRoute)");
    expect(facts.environments).toEqual(["APP_MODE=test"]);
    expect(facts.evalFiles).toEqual(["evals/feature.md"]);
    expect(facts.standing).toBeNull();
  });

  it("reads an eval named by delivery and a commit without a repo", () => {
    const facts = parseEvidence(
      "eval agh-62 @1682f1f06: exit 0, 7 passed (export url …); 3 new tests red on base 78091752",
    );

    expect(facts.evalDeliveries).toEqual(["agh-62"]);
    expect(parseEvidence("see the AGH-63 eval").evalDeliveries).toEqual(["agh-63"]);
    expect(facts.commits).toEqual([{ repo: null, sha: "1682f1f06" }]);
    expect(facts.redOnBase).toBe("3 new tests red on base 78091752");
  });

  it("says a failing result is not green", () => {
    const facts = parseEvidence("make type-check exit 2 with 6 errors, 3 failed");

    expect(resultPassed(facts.result)).toBe(false);
    expect(resultHeadline(facts.result)).toBe("3 of 3 tests failed");
  });

  it("puts the result in plain words and explains each number", () => {
    const facts = parseEvidence(WHOLE_FEATURE);

    expect(resultHeadline(facts.result)).toBe("10 tests passed");
    const explained = resultExplanation(facts.result);
    expect(explained).toHaveLength(3);
    expect(explained[0]).toContain("exit code 0, which means success");
    expect(explained[2]).toContain("42 tests in the same files were not run");
    expect(resultHeadline(parseEvidence("make lint exit 0").result)).toBe("Command succeeded");
    expect(resultHeadline(parseEvidence("make lint exit 2").result)).toBe(
      "Command failed (exit code 2)",
    );
  });

  it("marks superseded evidence and a repo-qualified PR", () => {
    const facts = parseEvidence(
      "superseded 2026-10-12 by owner decision; demo-api#68 closed without merging",
    );

    expect(facts.standing).toBe("superseded");
    expect(facts.prs).toEqual([{ repo: "demo-api", number: "68" }]);
    expect(facts.result).toBeNull();
  });

  it("notices a manual check that is still an owner step, and ignores AC ids as issues", () => {
    const facts = parseEvidence("covered with AC-15 by AGH-52; manual check still an owner step");

    expect(facts.ownerCheckOpen).toBe(true);
    expect(facts.issues).toEqual(["AGH-52"]);
  });

  it("returns empty facts for plain text", () => {
    const facts = parseEvidence("eval.md §Owner steps");

    expect(facts.result).toBeNull();
    expect(facts.commits).toEqual([]);
    expect(facts.date).toBeNull();
  });
});
