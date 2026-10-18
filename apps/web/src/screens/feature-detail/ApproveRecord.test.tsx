import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { anAgentSession, anId, renderWithApi, type ApiRoutes } from "../../testing/builders";
import { ApproveRecord, approvalMessage, featureSessions, writersOf } from "./ApproveRecord";

const AGENT = "/api/v1/agent-sessions";
const PATH = "brain/features/real-cost/spec.md";

const author = anAgentSession({
  id: anId(4, "0192a5e5"),
  title: "Estimativa de custo em dólares por tokens",
  updated_at: "2026-10-18T09:00:00Z",
});
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

/** `GET /agent-sessions`, answering `?wrote=` with `wrote` and the plain list with `items`. */
function sessions(items: unknown[], wrote: unknown[] = []): ApiRoutes {
  return {
    [AGENT]: (request: Request) => ({
      items: new URL(request.url).searchParams.has("wrote") ? wrote : items,
    }),
  };
}

const ui = (tickets: string[] = []) => (
  <ApproveRecord project="agent-hub" slug="real-cost" record="spec" path={PATH} tickets={tickets}>
    <p>The spec</p>
  </ApproveRecord>
);

async function topBar() {
  return within(await screen.findByRole("group", { name: "Approve the spec" }));
}

describe("ApproveRecord", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("prefers the session that changed the feature's files, then the ones naming it", () => {
    const found = featureSessions([other, mention, writer], "real-cost", ["AGH-303"], null);
    expect(found.map((s) => s.id)).toEqual([writer.id, mention.id]);
    expect(featureSessions([writer], "real-cost", [], writer.id)).toEqual([]);
    const listed = { ...mention } as Partial<typeof mention>;
    delete listed.changed_files;
    expect(featureSessions([listed as typeof mention], "real-cost", [], null)).toHaveLength(1);
  });

  it("trusts no writer when the server ignored ?wrote= and answered every session", () => {
    expect(writersOf([other, author], [other, author])).toEqual([]);
    expect(writersOf([author], [other, author])).toEqual([author]);
    expect(writersOf([author], [author])).toEqual([author]);
  });

  it("sends the approval to the session that wrote the record by default", async () => {
    const view = renderWithApi(ui(["AGH-303"]), {
      routes: {
        ...sessions([other, mention, author], [author]),
        [`POST ${AGENT}/${author.id}/messages`]: { seq: 5 },
      },
    });

    const bar = await topBar();
    expect(
      await bar.findByRole("button", { name: /goes to: Estimativa de custo/ }),
    ).toHaveTextContent("wrote it");
    expect(
      new URL(
        view.requests.find((r) => r.url.includes("wrote="))?.url ?? "http://x",
      ).searchParams.get("wrote"),
    ).toBe(PATH);
    await userEvent.click(bar.getByRole("button", { name: "Approve spec" }));

    expect((await screen.findAllByRole("status"))[0]).toHaveTextContent(
      "Approval of the spec sent to Estimativa de custo em dólares por tokens.",
    );
    const post = view.requests.find((r) => r.method === "POST");
    expect(new URL(post?.url ?? "http://x").pathname).toBe(`${AGENT}/${author.id}/messages`);
    const body = JSON.parse(await (post ?? new Request("about:blank")).clone().text()) as {
      text: string;
    };
    expect(body.text).toBe(approvalMessage("spec", PATH));
  });

  it("shows the approve bar once, at the end of the record", async () => {
    renderWithApi(ui(), { routes: sessions([author], [author]) });

    await topBar();
    expect(screen.getAllByRole("button", { name: "Approve spec" })).toHaveLength(1);
    const text = document.body.textContent;
    expect(text.indexOf("The spec")).toBeLessThan(text.indexOf("Approve spec"));
  });

  it("falls back to a session naming the feature when none wrote the record", async () => {
    renderWithApi(ui(["AGH-303"]), { routes: sessions([other, writer]) });

    expect(
      await (await topBar()).findByRole("button", { name: /goes to: \/feature AGH-303/ }),
    ).toBeVisible();
  });

  it("lets the owner pick another session, and remembers it", async () => {
    const view = renderWithApi(ui(), {
      routes: {
        ...sessions([other, author], [author]),
        [`POST ${AGENT}/${other.id}/messages`]: { seq: 5 },
      },
    });

    const bar = await topBar();
    await userEvent.click(await bar.findByRole("button", { name: /goes to: Estimativa/ }));
    await userEvent.click(bar.getByRole("button", { name: /Something else/ }));
    await userEvent.click(bar.getByRole("button", { name: "Approve spec" }));

    await waitFor(() => {
      expect(view.requests.some((r) => r.url.endsWith(`${other.id}/messages`))).toBe(true);
    });
    expect(window.localStorage.getItem("ah.approve.session.agent-hub:real-cost")).toBe(other.id);
  });

  it("shows only the record without session control", async () => {
    renderWithApi(ui());
    expect(await screen.findByText("The spec")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Approve spec" })).toBe(null);
  });
});
