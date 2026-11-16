import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  aCapabilities,
  aLearningDetail,
  aLogRecord,
  anAgentSession,
  anId,
  aPage,
  aWorkdir,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { ReviewPanel } from "./ReviewPanel";

const SESSION_ID = anId(1, "0192a5e5");
const SESSION = `/api/v1/agent-sessions/${SESSION_ID}`;
const DRAFT = "learning-abc123";
const DIR = `/hubs/demo/.hub-drafts/${DRAFT}`;
const detail = aLearningDetail();

function write(seq: number, file: string, content: string) {
  const id = `toolu_${String(seq)}`;
  return [
    aLogRecord("tool.call", {
      seq,
      body: {
        input: { file_path: `${DIR}/${file}`, content },
        name: "Write",
        parent_tool_use_id: null,
        tool_use_id: id,
      },
    }),
    aLogRecord("tool.result", {
      seq: seq + 1,
      body: { content: "written", is_error: false, tool_use_id: id },
    }),
  ];
}

const VERDICT = JSON.stringify({
  verdict: "needs_changes",
  summary: "True, but the command changed.",
  checks: [{ name: "Verified", result: "fail", note: "Makefile:68 runs check-fast" }],
  target: "learnings/gotchas/",
});

function open(routes: ApiRoutes = {}) {
  const onUseRevision = vi.fn();
  const onUseTarget = vi.fn();
  const view = renderWithApi(
    <ReviewPanel
      detail={detail}
      currentBody={detail.note?.markdown ?? ""}
      onUseRevision={onUseRevision}
      onUseTarget={onUseTarget}
    />,
    {
      routes: {
        "/api/v1/agent-sessions/capabilities": aCapabilities(),
        "/api/v1/agent-sessions/workdirs": aPage([aWorkdir()]),
        ...routes,
      },
    },
  );
  return { ...view, onUseRevision, onUseTarget };
}

beforeEach(() => {
  window.localStorage.clear();
});
afterEach(() => {
  window.localStorage.clear();
});

describe("ReviewPanel", () => {
  it("starts a review session in the hub folder with the review prompt", async () => {
    const { requests } = open({
      [`POST /api/v1/agent-sessions`]: anAgentSession({ id: SESSION_ID }),
    });

    await userEvent.click(await screen.findByRole("button", { name: "Review with Claude" }));

    const post = requests.find((r) => r.method === "POST");
    const body = (await post?.json()) as { mode: string; workdir_id: string; prompt: string };
    expect(body.mode).toBe("acceptEdits");
    expect(body.workdir_id).toBe(aWorkdir().workdir_id);
    expect(body.prompt).toContain("`brain/_inbox/web-gates.md` of project agent-hub");
    const link = JSON.parse(
      window.localStorage.getItem(`ah.learning.review.${detail.id}`) ?? "{}",
    ) as {
      sessionId?: string;
    };
    expect(link.sessionId).toBe(SESSION_ID);
  });

  it("shows Claude's verdict and hands its revision and target to the learning", async () => {
    window.localStorage.setItem(
      `ah.learning.review.${detail.id}`,
      JSON.stringify({ sessionId: SESSION_ID, draftId: DRAFT }),
    );
    const { onUseRevision, onUseTarget } = open({
      [SESSION]: anAgentSession({
        id: SESSION_ID,
        status: "ended",
        end_reason: "closed",
        last_seq: 5,
      }),
      [`${SESSION}/events`]: {
        items: [
          aLogRecord("init", { seq: 1 }),
          ...write(2, "note.md", "# Fixed\n"),
          ...write(4, "review.json", VERDICT),
        ],
        next_after: null,
      },
    });

    const panel = await screen.findByRole("region", { name: "Review by Claude" });
    expect(await within(panel).findByText("Needs changes")).toBeInTheDocument();
    expect(within(panel).getByText("True, but the command changed.")).toBeInTheDocument();
    expect(within(panel).getByRole("list", { name: "Checks" })).toHaveTextContent(
      "Verified · Fail — Makefile:68 runs check-fast",
    );

    await userEvent.click(within(panel).getByRole("button", { name: "Use Claude's revision" }));
    await userEvent.click(within(panel).getByRole("button", { name: /Use target/ }));

    expect(onUseRevision).toHaveBeenCalledWith("# Fixed\n");
    expect(onUseTarget).toHaveBeenCalledWith("learnings/gotchas/");
    expect(within(panel).getByRole("link", { name: "Open the conversation" })).toHaveAttribute(
      "href",
      `/agent-sessions/${SESSION_ID}`,
    );
  });

  it("says why a review cannot start on this machine", async () => {
    open({ "/api/v1/agent-sessions/capabilities": aCapabilities({ available: false }) });

    expect(await screen.findByRole("button", { name: "Review with Claude" })).toBeDisabled();
  });
});
