import { describe, expect, it } from "vitest";

import { approvalMessage, countLine, openQuestions, outcomeOf } from "./openQuestions";

const SPEC = `# A spec

## Goals

- Not a question.

## Open questions

- Q1. **Signal names.** Which OTel signal carries the cost,
  and its \`attributes\`. Research.
- Q9. **Port.** The brief says 7421. Assumed: the endpoint follows the hook sensor
  (\`AGENT_HUB_WEB_URL\`, else \`http://127.0.0.1:7420\`). Then more prose.
- Q11. **Helper calls.** Count them or drop them? S5 assumes: their cost joins the run.
- **Q-12 (scope):** Which calls count? Not assumed: anything.
- Q13. A plain question without a bold title. It goes on.
- Q15. **Divergence.** The banner compares the requests both cover (assumed), not the whole estimate. And more?
- Q14. **Old one.** Settled (resolved 2026-10-01).
- None open beyond these.

**Owner decision:** spec approved, not a question.

## Next section

- Not a question either.
`;

const path = "brain/features/real-cost/spec.md";

describe("openQuestions", () => {
  it("reads each question of the section with its id, title and body", () => {
    const questions = openQuestions(SPEC);

    expect(questions.map((q) => q.id)).toEqual(["Q1", "Q9", "Q11", "Q-12", "Q13", "Q15"]);
    expect(questions[0]).toEqual({
      id: "Q1",
      title: "Signal names",
      body: "Which OTel signal carries the cost, and its `attributes`. Research.",
      recommendation: null,
      options: [],
    });
    expect(questions[3]?.title).toBe("scope");
    expect(questions[4]?.title).toBe("A plain question without a bold title");
  });

  it("finds what the record assumes or recommends, up to the end of that sentence", () => {
    const [, port, helpers, scope] = openQuestions(SPEC);

    expect(port?.recommendation).toBe(
      "the endpoint follows the hook sensor (`AGENT_HUB_WEB_URL`, else `http://127.0.0.1:7420`).",
    );
    expect(helpers?.recommendation).toBe("their cost joins the run.");
    expect(scope?.recommendation).toBe(null);
    expect(openQuestions(SPEC)[5]?.recommendation).toBe(
      "The banner compares the requests both cover, not the whole estimate.",
    );
  });

  it("reads the options nested under a question, and the recommended one", () => {
    const [cache, wire] = openQuestions(`## Open questions

- Q1. **Cache.** Where is the price list kept?
  - **In memory** (recommended): rebuilt on start, no
    new file.
  - **On disk** — survives a restart.
  - A new table
- Q2. **Wire format.** JSON or protobuf? Recommended: JSON.
  - JSON: what the API speaks.
  - Protobuf (recommended)
`);

    expect(cache?.options).toEqual([
      { label: "In memory", description: "rebuilt on start, no new file.", recommended: true },
      { label: "On disk", description: "survives a restart.", recommended: false },
      { label: "A new table", description: null, recommended: false },
    ]);
    expect(cache?.body).toBe("Where is the price list kept?");
    // The marked option is the recommendation when the prose names none; the prose wins otherwise.
    expect(cache?.recommendation).toBe("In memory");
    expect(wire?.recommendation).toBe("JSON.");
    expect(wire?.options.map((o) => [o.label, o.recommended])).toEqual([
      ["JSON", false],
      ["Protobuf", true],
    ]);
  });

  it("finds nothing without the section", () => {
    expect(openQuestions("# Spec\n\n## Goals\n\n- One.\n")).toEqual([]);
  });
});

describe("approvalMessage", () => {
  const questions = openQuestions(SPEC).slice(0, 3);

  it("is a plain approval when the record has no open questions", () => {
    expect(approvalMessage("spec", path)).toBe(
      "I approve the spec (`brain/features/real-cost/spec.md`) as it is now. Treat it as approved and go on with the next step of the feature.",
    );
  });

  it("lists each answer, else the recommendation, else the session's own call", () => {
    expect(approvalMessage("spec", path, questions, { Q11: "Drop them.\nAll of them." })).toBe(
      [
        "I approve the spec (`brain/features/real-cost/spec.md`) as it is now, with these answers to its open questions:",
        "- Q1 (Signal names): no answer, use your own recommendation.",
        "- Q9 (Port): accept the recommendation.",
        "- Q11 (Helper calls): Drop them.",
        "  All of them.",
        "Record the answers in the spec, then go on with the next step of the feature.",
      ].join("\n"),
    );
  });

  it("says how many are answered and what the blank ones do", () => {
    const [first] = questions;
    if (first) expect(outcomeOf(first, { Q1: "  " })).toBe("claude");
    expect(countLine(questions.slice(1), {})).toBe(
      "No answers: every question takes the recommendation.",
    );
    expect(countLine(questions, {})).toBe(
      "No answers yet · 2 take the recommendation · 1 left to Claude",
    );
    expect(countLine(questions, { Q1: "Logs only." })).toBe(
      "1 answered · 2 take the recommendation",
    );
    expect(countLine(questions, { Q9: "7420." })).toBe(
      "1 answered · 1 takes the recommendation · 1 left to Claude",
    );
  });
});
