import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  aCapabilities,
  aLogRecord,
  aProblem,
  aSkillCatalog,
  aSkillDetail,
  aWorkdir,
  anAgentSession,
  anId,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { publishPrompt } from "./draft";
import { EditDraftScreen, StudioScreen } from "./Studio";
import { openDrafts, saveDraft, storedDraft } from "./studioDrafts";

const DRAFT = "skill-abc123";
const HUB = "/home/owner/hubs/demo";
const ID = anId(7, "0192a5e5");
const SESSION = `/api/v1/agent-sessions/${ID}`;
const STREAM = `${SESSION}/stream`;
const TO = "plugin/demo/skills/changelog/";

const SKILL = `---
name: changelog
description: Writes release notes from the merged PRs. Use when cutting a release.
---

# Changelog
`;

function routes(overrides: ApiRoutes = {}): ApiRoutes {
  return {
    "/api/v1/projects/demo/skills": aSkillCatalog(),
    "/api/v1/agent-sessions/capabilities": aCapabilities(),
    "/api/v1/agent-sessions/workdirs": { items: [aWorkdir()], warnings: [] },
    [SESSION]: anAgentSession({ id: ID, status: "idle", last_seq: 4 }),
    [`${SESSION}/events`]: {
      items: [
        aLogRecord("user.message", { seq: 1, body: { text: "A changelog skill" } }),
        aLogRecord("tool.call", {
          seq: 2,
          body: {
            input: { file_path: `${HUB}/.hub-drafts/${DRAFT}/SKILL.md`, content: SKILL },
            name: "Write",
            parent_tool_use_id: null,
            tool_use_id: "toolu_01",
          },
        }),
        aLogRecord("tool.result", { seq: 3 }),
        aLogRecord("result", { seq: 4 }),
      ],
      next_after: null,
    },
    ...overrides,
  };
}

function renderStudio(apiRoutes: ApiRoutes = routes()) {
  return renderWithApi(<StudioScreen />, {
    routes: apiRoutes,
    path: `/projects/demo/skills/drafts/${DRAFT}`,
    route: "/projects/:project/skills/drafts/:draftId",
  });
}

const posts = (requests: Request[], path: string) =>
  requests.filter((r) => r.method === "POST" && new URL(r.url).pathname === path);

async function bodyOf(request: Request | undefined): Promise<Record<string, unknown>> {
  if (!request) throw new Error("no request");
  return JSON.parse(await request.clone().text()) as Record<string, unknown>;
}

/** Opens the Studio on a draft whose session already wrote a publishable SKILL.md. */
async function openDraft(apiRoutes: ApiRoutes) {
  saveDraft(DRAFT, { project: "demo", kind: "skill" }, { sessionId: ID });
  const view = renderStudio(apiRoutes);
  const publish = await screen.findByRole("button", { name: "Publish" });
  await waitFor(() => {
    expect(publish).toBeEnabled();
  });
  await userEvent.click(publish);
  await userEvent.click(
    within(screen.getByRole("alertdialog")).getByRole("button", { name: "Publish" }),
  );
  await waitFor(() => {
    expect(posts(view.requests, `${SESSION}/messages`)).toHaveLength(1);
  });
  return view;
}

/** The publish turn as the stream brings it: the message, Claude's reply, the turn's end. */
function publishTurn(view: ReturnType<typeof renderStudio>, reply: string) {
  act(() => {
    const source = view.stream(STREAM);
    source.emit(
      "record.user.message",
      aLogRecord("user.message", { seq: 5, body: { text: publishPrompt("skill", DRAFT, TO) } }),
      "5",
    );
    source.emit(
      "record.text",
      aLogRecord("text", { seq: 6, body: { block: 0, text: reply } }),
      "6",
    );
    source.emit("record.result", aLogRecord("result", { seq: 7 }), "7");
  });
}

beforeEach(() => {
  window.localStorage.clear();
});
afterEach(() => {
  window.localStorage.clear();
});

describe("StudioScreen (start)", () => {
  it("starts a session in the hub folder with the Studio brief and the owner's ask", async () => {
    const view = renderStudio(
      routes({ "POST /api/v1/agent-sessions": anAgentSession({ id: ID, status: "running" }) }),
    );
    const box = await screen.findByRole("textbox", { name: "Message Claude" });
    await waitFor(() => {
      expect(box).toBeEnabled();
    });

    await userEvent.type(box, "A changelog skill{Enter}");

    await waitFor(() => {
      expect(posts(view.requests, "/api/v1/agent-sessions")).toHaveLength(1);
    });
    const body = await bodyOf(posts(view.requests, "/api/v1/agent-sessions")[0]);
    expect(body).toMatchObject({
      project: "demo",
      workdir_id: aWorkdir().workdir_id,
      mode: "acceptEdits",
      fork: false,
    });
    expect(body.prompt).toContain(`Write the draft ONLY inside the folder .hub-drafts/${DRAFT}/`);
    expect(String(body.prompt).endsWith("What I want:\nA changelog skill")).toBe(true);
    await waitFor(() => {
      expect(storedDraft(DRAFT)?.sessionId).toBe(ID);
    });
  });

  it("disables the composer while the session is being created", async () => {
    renderStudio(routes({ "POST /api/v1/agent-sessions": "pending" }));
    const starter = await screen.findByRole("button", { name: /A \/changelog skill/ });
    await waitFor(() => {
      expect(starter).toBeEnabled();
    });

    await userEvent.click(starter);

    expect(screen.getByRole("textbox", { name: "Message Claude" })).toBeDisabled();
  });
});

describe("StudioScreen (publish)", () => {
  it("shows Published and leaves Drafts in progress once Claude confirms", async () => {
    const view = await openDraft(routes({ [`POST ${SESSION}/messages`]: { seq: 5 } }));
    expect(await bodyOf(posts(view.requests, `${SESSION}/messages`)[0])).toEqual({
      text: publishPrompt("skill", DRAFT, TO),
    });

    publishTurn(view, `PUBLISHED ${TO}SKILL.md`);

    expect(await screen.findByText("Published.")).toBeInTheDocument();
    await waitFor(() => {
      expect(storedDraft(DRAFT)?.published).toBe(true);
    });
    expect(openDrafts("demo")).toEqual([]);
  });

  it("goes back to drafting with the problem when the message is refused", async () => {
    await openDraft(
      routes({
        [`POST ${SESSION}/messages`]: aProblem({
          status: 409,
          title: "Conflict",
          detail: "A turn is already running.",
        }),
      }),
    );

    expect(await screen.findByText("A turn is already running.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish" })).toBeEnabled();
    expect(screen.queryByText("Published.")).toBeNull();
    expect(openDrafts("demo").map((d) => d.draftId)).toEqual([DRAFT]);
  });

  it("keeps the draft listed when the turn ends without Claude's confirmation", async () => {
    const view = await openDraft(routes({ [`POST ${SESSION}/messages`]: { seq: 5 } }));

    publishTurn(view, "I could not find the plugin folder.");

    expect(await screen.findByText(/Claude did not confirm the publish/)).toBeInTheDocument();
    expect(screen.queryByText("Published.")).toBeNull();
    expect(openDrafts("demo").map((d) => d.draftId)).toEqual([DRAFT]);
  });
});

describe("StudioScreen (edit an existing item)", () => {
  const TARGET = { kind: "skill" as const, source: "hub-workflow", name: "feature" };
  const DETAIL = "/api/v1/projects/demo/skills/skill/hub-workflow/feature";

  function openEdit() {
    return renderWithApi(<EditDraftScreen />, {
      path: "/projects/demo/skills/skill/hub-workflow/feature/edit",
      route: "/projects/:project/skills/:kind/:source/:name/edit",
    });
  }

  it("opens a new edit draft of the item, and the same one on a second Edit", async () => {
    const first = openEdit();
    await waitFor(() => {
      expect(first.router.state.location.pathname).toMatch(
        /^\/projects\/demo\/skills\/drafts\/skill-/,
      );
    });
    const draftId = first.router.state.location.pathname.split("/").at(-1) ?? "";
    expect(storedDraft(draftId)).toMatchObject({ target: TARGET, name: "feature" });
    first.unmount();

    const second = openEdit();
    await waitFor(() => {
      expect(second.router.state.location.pathname).toBe(`/projects/demo/skills/drafts/${draftId}`);
    });
  });

  it("starts the session on a copy of the item, leaving the original alone", async () => {
    saveDraft(DRAFT, { project: "demo", kind: "skill" }, { target: TARGET, name: "feature" });
    const view = renderStudio(
      routes({
        [DETAIL]: aSkillDetail(),
        "POST /api/v1/agent-sessions": anAgentSession({ id: ID, status: "running" }),
      }),
    );
    expect(await screen.findByRole("link", { name: "Skills" })).toBeInTheDocument();
    expect(screen.getByText("Edit feature")).toBeInTheDocument();
    const box = await screen.findByRole("textbox", { name: "Message Claude" });
    await waitFor(() => {
      expect(box).toBeEnabled();
    });

    await userEvent.type(box, "Shorten it{Enter}");

    await waitFor(() => {
      expect(posts(view.requests, "/api/v1/agent-sessions")).toHaveLength(1);
    });
    const body = await bodyOf(posts(view.requests, "/api/v1/agent-sessions")[0]);
    expect(body.prompt).toContain(`writing it unchanged, whole, to .hub-drafts/${DRAFT}/SKILL.md`);
    expect(body.prompt).toContain("Do not touch the original");
  });
});
