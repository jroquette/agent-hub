import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { GlobalStreamProvider } from "../../shell/GlobalStream";
import {
  aCapabilities,
  aLearning,
  aLearningDetail,
  aLogRecord,
  anAgentSession,
  anId,
  aPage,
  aProjectDetail,
  aWorkdir,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { initialTranscript } from "../agent-session/model";
import { LearningsScreen } from "./index";
import { runOf } from "./triage";

const SESSION_ID = anId(7, "0192a5e5");
const SESSION = `/api/v1/agent-sessions/${SESSION_ID}`;
const first = aLearning({ id: "l-1", text: "Stripe has two clients", note_path: "_inbox/a.md" });
const second = aLearning({
  id: "l-2",
  text: "Guard env files",
  proposed_at: "2026-10-12T00:00:00Z",
});
const blocked = aLearning({ id: "l-3", text: "Gone note", actions_unavailable: "Note is gone" });

function open(routes: ApiRoutes = {}) {
  return renderWithApi(
    <GlobalStreamProvider project={null}>
      <LearningsScreen />
    </GlobalStreamProvider>,
    {
      path: "/knowledge/learnings",
      routes: {
        "/api/v1/learnings": aPage([first, second, blocked]),
        "/api/v1/learnings/l-1": aLearningDetail({ ...first }),
        "/api/v1/learnings/l-2": aLearningDetail({ ...second }),
        "/api/v1/projects/agent-hub": aProjectDetail({ hub_repo: "agent-hub-hub" }),
        "/api/v1/agent-sessions/capabilities": aCapabilities(),
        "/api/v1/agent-sessions/workdirs": aPage([aWorkdir()]),
        ...routes,
      },
    },
  );
}

beforeEach(() => {
  window.localStorage.clear();
});
afterEach(() => {
  window.localStorage.clear();
});

describe("Triage with Claude", () => {
  it("starts one session over the decidable learnings and links each to its folder", async () => {
    const { requests } = open({
      "POST /api/v1/agent-sessions": anAgentSession({ id: SESSION_ID }),
      [SESSION]: anAgentSession({ id: SESSION_ID, status: "running", last_seq: 1 }),
      [`${SESSION}/events`]: { items: [aLogRecord("init", { seq: 1 })], next_after: null },
    });

    await userEvent.click(await screen.findByRole("button", { name: "Triage with Claude · 2" }));

    const posts = requests.filter((r) => r.method === "POST");
    expect(posts).toHaveLength(1);
    const body = (await posts[0]?.json()) as { prompt: string; workdir_id: string };
    expect(body.workdir_id).toBe(aWorkdir().workdir_id);
    expect(body.prompt).toContain("Triage the 2 proposed learnings of project agent-hub");
    expect(body.prompt).toContain("`brain/_inbox/a.md`");
    expect(body.prompt).not.toContain("Gone note");
    for (const id of ["l-1", "l-2"]) {
      const link = JSON.parse(window.localStorage.getItem(`ah.learning.review.${id}`) ?? "{}") as {
        sessionId?: string;
        draftId?: string;
        order?: number;
      };
      expect(link.sessionId).toBe(SESSION_ID);
      expect(typeof link.order).toBe("number");
      expect(link.draftId).toMatch(new RegExp(`^triage-[a-z0-9]+/${id}$`));
    }
    const progress = await screen.findByRole("region", { name: "Triage progress" });
    expect(await within(progress).findByText("Claude is triaging 2 learnings")).toBeInTheDocument();
    expect(within(progress).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
    expect(within(progress).getByText("0 of 2 reviewed")).toBeInTheDocument();
  });

  it("shows Claude's verdict on each row and filters by it", async () => {
    const draft = "triage-abc123";
    ["l-1", "l-2"].forEach((id, order) => {
      window.localStorage.setItem(
        `ah.learning.review.${id}`,
        JSON.stringify({ sessionId: SESSION_ID, draftId: `${draft}/${id}`, order }),
      );
    });
    open({
      [SESSION]: anAgentSession({ id: SESSION_ID, status: "running", last_seq: 3 }),
      [`${SESSION}/events`]: {
        items: [
          aLogRecord("init", { seq: 1 }),
          aLogRecord("tool.call", {
            seq: 2,
            body: {
              input: {
                file_path: `/hubs/demo/.hub-drafts/${draft}/l-1/review.json`,
                content: JSON.stringify({ verdict: "ready", summary: "Holds up.", checks: [] }),
              },
              name: "Write",
              parent_tool_use_id: null,
              tool_use_id: "toolu_2",
            },
          }),
          aLogRecord("tool.result", {
            seq: 3,
            body: { content: "written", is_error: false, tool_use_id: "toolu_2" },
          }),
        ],
        next_after: null,
      },
    });

    const table = await screen.findByRole("table", { name: "Proposed learnings" });
    expect(await within(table).findByText("Claude: Ready for the brain")).toBeInTheDocument();
    expect(within(table).getByText("Claude is reviewing this now")).toBeInTheDocument();
    const progress = screen.getByRole("region", { name: "Triage progress" });
    expect(within(progress).getByText("1 of 2 reviewed")).toBeInTheDocument();
    expect(within(progress).getByRole("button", { name: "Guard env files" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Claude: Any" }));
    const menu = screen.getByRole("dialog", { name: "Claude filter" });
    await userEvent.click(within(menu).getByRole("checkbox", { name: /Goes in/ }));

    expect(within(table).queryByText("Guard env files")).not.toBeInTheDocument();
    expect(within(table).getByText("Stripe has two clients")).toBeInTheDocument();
  });

  it("asks for one project when the queue spans several", async () => {
    open({
      "/api/v1/learnings": aPage([first, aLearning({ id: "l-9", project: "tipple" })]),
    });

    const button = await screen.findByRole("button", { name: /Triage with Claude/ });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Pick one project to triage its learnings.");
  });

  it("marks the learnings behind the current one as queued and says when Claude needs you", async () => {
    ["l-1", "l-2"].forEach((id, order) => {
      window.localStorage.setItem(
        `ah.learning.review.${id}`,
        JSON.stringify({ sessionId: SESSION_ID, draftId: `triage-abc123/${id}`, order }),
      );
    });
    open({
      [SESSION]: anAgentSession({ id: SESSION_ID, status: "waiting_permission", last_seq: 1 }),
      [`${SESSION}/events`]: { items: [aLogRecord("init", { seq: 1 })], next_after: null },
    });

    const table = await screen.findByRole("table", { name: "Proposed learnings" });
    expect(await within(table).findByText("Claude needs your answer")).toBeInTheDocument();
    expect(within(table).getByText("Up next for Claude")).toBeInTheDocument();
    const progress = screen.getByRole("region", { name: "Triage progress" });
    expect(within(progress).getByText("Claude is waiting for you")).toBeInTheDocument();
    expect(
      within(progress).getByRole("link", { name: "Answer in the conversation" }),
    ).toHaveAttribute("href", `/agent-sessions/${SESSION_ID}`);
    const detail = await screen.findByRole("complementary", { name: "Claude's review" });
    expect(within(detail).getByText(/Claude stopped on a permission request/)).toBeInTheDocument();
  });
});

describe("runOf ended_session", () => {
  it("gives no verdict to the learnings a finished session never reviewed", () => {
    const state = { ...initialTranscript(), status: "ended" as const };
    const { run, reviews } = runOf(
      SESSION_ID,
      [
        ["l-1", { sessionId: SESSION_ID, draftId: "triage-x/l-1", order: 0 }],
        ["l-2", { sessionId: SESSION_ID, draftId: "triage-x/l-2", order: 1 }],
      ],
      state,
      false,
    );

    expect(run).toMatchObject({ status: "ended", reviewed: 0, missing: 2, currentId: null });
    expect(reviews["l-1"]?.verdict).toBe("no_verdict");
    expect(reviews["l-2"]?.position).toBeNull();
  });
});
