import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { aProblem, anAcRow, anEvalRecord, renderWithApi } from "../../testing/builders";
import { passOf } from "./CriteriaTab";
import { MarkAcPassing } from "./MarkAcPassing";

const SIGNOFF = "/api/v1/features/agent-hub/control-plane/owner-signoff";

function mark(ac = anAcRow({ id: "AC-21", passes: false })) {
  return <MarkAcPassing ac={ac} project="agent-hub" slug="control-plane" />;
}

describe("MarkAcPassing", () => {
  it("AC-425.1 signs off one criterion the owner checked by hand, with a note", async () => {
    const written = anEvalRecord({ delivery: "owner-signoff", verdict: "SHIP", acs: ["AC-21"] });
    const view = renderWithApi(mark(), { routes: { [`POST ${SIGNOFF}`]: written } });

    await userEvent.click(screen.getByRole("button", { name: "I checked it, mark as passing" }));
    await userEvent.type(
      screen.getByRole("textbox", { name: "Note (optional)" }),
      "Clicked through the order page",
    );
    await userEvent.click(screen.getByRole("button", { name: "Mark as passing" }));

    await waitFor(() => {
      expect(view.requests.some((r) => r.method === "POST")).toBe(true);
    });
    const post = view.requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({
      acs: ["AC-21"],
      decision: "done",
      note: "Clicked through the order page",
    });
  });

  it("AC-425.1 says a signed-off criterion counts as passing, with no button", () => {
    renderWithApi(mark(anAcRow({ passes: false, signed_off: true })));

    expect(screen.getByText(/signed it off; it counts as passing/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("AC-425.1 offers nothing on a criterion that already passes", () => {
    const { container } = renderWithApi(mark(anAcRow({ passes: true })));

    expect(container).toBeEmptyDOMElement();
  });

  it("AC-425.1 reads a signed-off criterion as passing", () => {
    expect(passOf(anAcRow({ passes: false, signed_off: true }))).toBe("yes");
    expect(passOf(anAcRow({ passes: false, manual: true }))).toBe("owner");
  });

  it("AC-425.2 shows the server's refusal in the form, and Cancel sends nothing", async () => {
    const refused = aProblem({
      status: 409,
      title: "Nothing to sign off",
      detail: "the latest eval of AC-21 is NO-SHIP; fix or re-evaluate first",
    });
    const view = renderWithApi(mark(), { routes: { [`POST ${SIGNOFF}`]: refused } });

    await userEvent.click(screen.getByRole("button", { name: "I checked it, mark as passing" }));
    await userEvent.click(screen.getByRole("button", { name: "Mark as passing" }));

    expect(await screen.findByText(/latest eval of AC-21 is NO-SHIP/)).toBeInTheDocument();
    expect(screen.getByText("Could not mark AC-21 as passing")).toBeInTheDocument();
    const posts = view.requests.filter((r) => r.method === "POST").length;
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(view.requests.filter((r) => r.method === "POST")).toHaveLength(posts);
    expect(screen.getByRole("button", { name: "I checked it, mark as passing" })).toBeVisible();
  });
});
