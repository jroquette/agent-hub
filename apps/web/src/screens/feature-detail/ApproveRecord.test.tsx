import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { anAgentSession, anId, renderWithApi } from "../../testing/builders";
import { ApproveRecord, approvalMessage, featureSessions } from "./ApproveRecord";

const AGENT = "/api/v1/agent-sessions";
const PATH = "brain/features/real-cost/spec.md";

const writer = anAgentSession({
  id: anId(1, "0192a5e5"),
  title: "/feature AGH-303",
  status: "idle",
  updated_at: "2026-10-18T10:00:00Z",
  changed_files: [{ path: PATH, last_change_id: "c1" }],
});
const mention = anAgentSession({
  id: anId(2, "0192a5e5"),
  title: "Talk about real-cost",
  updated_at: "2026-10-18T11:00:00Z",
});
const other = anAgentSession({
  id: anId(3, "0192a5e5"),
  title: "Something else",
  updated_at: "2026-10-18T12:00:00Z",
});

describe("ApproveRecord", () => {
  it("prefers the session that changed the feature's files, then the ones naming it", () => {
    const found = featureSessions([other, mention, writer], "real-cost", ["AGH-303"], null);
    expect(found.map((s) => s.id)).toEqual([writer.id, mention.id]);
    expect(featureSessions([writer], "real-cost", [], writer.id)).toEqual([]);
  });

  it("sends the approval to the session that worked on the feature", async () => {
    const view = renderWithApi(
      <ApproveRecord
        project="agent-hub"
        slug="real-cost"
        record="spec"
        path={PATH}
        tickets={["AGH-303"]}
      />,
      {
        routes: {
          [AGENT]: { items: [other, mention, writer] },
          [`POST ${AGENT}/${writer.id}/messages`]: { seq: 5 },
        },
      },
    );

    expect(await screen.findByRole("button", { name: /goes to: \/feature AGH-303/ })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Approve spec" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Approval of the spec sent to /feature AGH-303.",
    );
    const post = view.requests.find((r) => r.method === "POST");
    expect(new URL(post?.url ?? "http://x").pathname).toBe(`${AGENT}/${writer.id}/messages`);
    const body = JSON.parse(await (post ?? new Request("about:blank")).clone().text()) as {
      text: string;
    };
    expect(body.text).toBe(approvalMessage("spec", PATH));
  });

  it("lets the owner pick another session", async () => {
    const view = renderWithApi(
      <ApproveRecord project="agent-hub" slug="real-cost" record="spec" path={PATH} tickets={[]} />,
      {
        routes: {
          [AGENT]: { items: [other, writer] },
          [`POST ${AGENT}/${other.id}/messages`]: { seq: 5 },
        },
      },
    );

    await userEvent.click(
      await screen.findByRole("button", { name: /goes to: \/feature AGH-303/ }),
    );
    await userEvent.click(screen.getByRole("button", { name: /Something else/ }));
    await userEvent.click(screen.getByRole("button", { name: "Approve spec" }));

    await waitFor(() => {
      expect(view.requests.some((r) => r.url.endsWith(`${other.id}/messages`))).toBe(true);
    });
  });

  it("shows nothing without session control", () => {
    const { container } = renderWithApi(
      <ApproveRecord project="agent-hub" slug="real-cost" record="spec" path={PATH} tickets={[]} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
