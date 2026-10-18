import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aBrainNote,
  anAgentSession,
  anId,
  aProblem,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
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

  describe("open questions", () => {
    const NOTE = "/api/v1/projects/agent-hub/brain/note";
    const SPEC = [
      "# Spec",
      "",
      "## Open questions",
      "",
      "- Q1. **Signal names.** Which signal carries the cost? Research.",
      "- Q2. **Wire format.** JSON or protobuf? Research.",
      "- Q3. **Logs or metrics.** Which ones? Research.",
      "- Q9. **Port.** The brief says 7421. Assumed: the hook sensor's port, 7420.",
      "",
      "## Next",
    ].join("\n");
    const routes = (extra: ApiRoutes = {}): ApiRoutes => ({
      ...sessions([author], [author]),
      [NOTE]: aBrainNote({ path: "features/real-cost/spec.md", markdown: SPEC }),
      ...extra,
    });

    it("shows nothing more when the record has no open questions", async () => {
      renderWithApi(ui(), {
        routes: { ...routes(), [NOTE]: aBrainNote({ markdown: "# Spec\n" }) },
      });
      await topBar();
      expect(screen.queryByRole("heading", { name: "Open questions" })).toBe(null);
      expect(screen.getByRole("button", { name: "Approve spec" })).toBeVisible();
    });

    it("folds the questions and says what a blank answer does", async () => {
      renderWithApi(ui(), { routes: routes() });

      const block = within(await screen.findByRole("region", { name: "Open questions" }));
      expect(block.getByText("Takes the recommendation")).toBeVisible();
      expect(block.getAllByText("Claude decides")).toHaveLength(3);
      // The folded row's second line says what a blank answer sends.
      expect(block.getAllByText("the hook sensor's port, 7420.")[0]).toHaveClass("ah-aq-glimpse");
      expect(
        screen.getByText("No answers yet · 1 takes the recommendation · 3 left to Claude"),
      ).toBeVisible();
    });

    it("sends each answer, and the recommendation for a blank one", async () => {
      const view = renderWithApi(ui(), {
        routes: routes({ [`POST ${AGENT}/${author.id}/messages`]: { seq: 5 } }),
      });

      await userEvent.click(await screen.findByText("Signal names"));
      await userEvent.type(screen.getByLabelText("Your answer to Q1"), "The log event.");
      const approve = screen.getByRole("button", { name: "Approve spec with 1 answer" });
      expect(
        screen.getByText("1 answered · 1 takes the recommendation · 2 left to Claude"),
      ).toBeVisible();
      await userEvent.click(approve);

      expect(await screen.findByRole("status")).toHaveTextContent(
        "Approval of the spec sent to Estimativa de custo em dólares por tokens with 1 answer.",
      );
      const post = view.requests.find((r) => r.method === "POST");
      const body = JSON.parse(await (post ?? new Request("about:blank")).clone().text()) as {
        text: string;
      };
      expect(body.text).toContain("- Q1 (Signal names): The log event.");
      expect(body.text).toContain("- Q9 (Port): accept the recommendation.");
      expect(body.text).toContain("- Q2 (Wire format): no answer, use your own recommendation.");
      expect(screen.queryByLabelText("Your answer to Q1")).toBe(null);
      expect(window.localStorage.getItem("ah.approve.answers.agent-hub:real-cost:spec")).toBe(null);
    });

    it("keeps the answers as a draft across a reload, and on a failed send", async () => {
      window.localStorage.setItem(
        "ah.approve.answers.agent-hub:real-cost:spec",
        JSON.stringify({ Q9: { title: "Port", text: "Use 7421." } }),
      );
      renderWithApi(ui(), {
        routes: routes({
          [`POST ${AGENT}/${author.id}/messages`]: aProblem({
            status: 409,
            title: "Conflict",
            detail: "The session is busy.",
          }),
        }),
      });

      await userEvent.click(
        await screen.findByRole("button", { name: "Approve spec with 1 answer" }),
      );

      expect(await screen.findByRole("alert")).toHaveTextContent("The session is busy.");
      await userEvent.click(screen.getByText("Port"));
      expect(screen.getByLabelText("Your answer to Q9")).toHaveValue("Use 7421.");
    });

    it("has no serious a11y violations with questions open (a11y)", async () => {
      const { container } = renderWithApi(ui(), { routes: routes() });
      await userEvent.click(await screen.findByText("Port"));
      await screen.findByLabelText("Your answer to Q9");

      expect(await seriousViolations(container)).toEqual([]);
    });
  });
});
