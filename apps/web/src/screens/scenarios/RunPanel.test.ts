import { describe, expect, it } from "vitest";

import { ApiProblem } from "../../lib/api";
import { aScenarioPlan } from "../../testing/builders";
import { oneCommit, planMessages, verdict } from "./RunPanel";

describe("oneCommit (scenario run panel)", () => {
  it("joins the draft actions' paths into one git add and one commit", () => {
    expect(
      oneCommit(
        [
          "git add -- actions/orders/a.yaml actions/orders/scripts/a.py actions/orders/scripts/personal.py && git commit -m 'Accept action orders/a'",
          "git add -- actions/orders/b.yaml actions/orders/scripts/personal.py && git commit -m 'Accept action orders/b'",
        ],
        ["orders/a", "orders/b"],
      ),
    ).toBe(
      "git add -- actions/orders/a.yaml actions/orders/scripts/a.py actions/orders/scripts/personal.py actions/orders/b.yaml && git commit -m 'Accept actions orders/a, orders/b'",
    );
  });

  it("keeps the server's command word for word for a single draft action", () => {
    const command = "git add -- actions/a.yaml && git commit -m 'Accept action orders/a'";
    expect(oneCommit([command], ["orders/a"])).toBe(command);
  });

  it("keeps the commands as they are when one has another shape", () => {
    expect(oneCommit(["git add x && git commit", "echo y"], ["a", "b"])).toBe(
      "git add x && git commit && echo y",
    );
  });
});

describe("verdict (scenario run panel)", () => {
  // AC-596.2.7: a plan with problems cannot start, and says how many.
  it("counts the plan's problems", () => {
    expect(verdict(aScenarioPlan({ problems: ["x is wrong"] }), null)).toEqual({
      ok: false,
      text: "Cannot start: the plan has 1 problem.",
      drafts: false,
    });
  });

  // AC-596.2.9: a stale plan says why before anything else.
  it("says why a stale plan cannot start", () => {
    expect(verdict(aScenarioPlan({ problems: ["x"] }), "Plan again.").text).toBe("Plan again.");
  });
});

describe("planMessages (scenario run panel)", () => {
  // AC-596.2.5: a 422's messages at the fields the form shows, the others listed apart.
  it("puts each message at its field, once, and keeps the others", () => {
    const error = new ApiProblem({
      status: 422,
      title: "Invalid request body",
      errors: [
        { pointer: "/inputs/external_ref", message: "external_ref must be a ref." },
        { pointer: "/inputs/external_ref", message: "a second one" },
        { pointer: "/inputs/hidden", message: "hidden is not an input." },
        { pointer: "/environment", message: "environment must name an environment." },
      ],
    });
    const { atFields, others } = planMessages(error, ["external_ref"]);
    expect([...atFields]).toEqual([["external_ref", "external_ref must be a ref."]]);
    expect(others).toEqual(["hidden is not an input.", "environment must name an environment."]);
  });

  it("reads nothing from another problem", () => {
    const error = new ApiProblem({ status: 502, title: "Bad gateway" });
    expect(planMessages(error, ["external_ref"]).others).toEqual([]);
    expect(planMessages(null, []).atFields.size).toBe(0);
  });
});
