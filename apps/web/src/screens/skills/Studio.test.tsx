import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  aCapabilities,
  aCatalogItem,
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
import { seriousViolations } from "../../testing/axe";
import { discardPrompt } from "./draft";
import { EditDraftScreen, PUBLISH_MANAGED_WARNING, StudioScreen } from "./Studio";
import { openDrafts, saveDraft, storedDraft } from "./studioDrafts";

const DRAFT = "skill-abc123";
const HUB = "/home/owner/hubs/demo";
const ID = anId(7, "0192a5e5");
const SESSION = `/api/v1/agent-sessions/${ID}`;
const PUBLISH = `/api/v1/projects/demo/skills/drafts/${DRAFT}/publish`;
const PUBLISHED = { changed: true, versioned: true, reason: null, version: null };

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

/** Opens the Studio on a draft whose session already wrote a publishable SKILL.md, and opens
 * the Publish dialog. */
async function openPublish(apiRoutes: ApiRoutes) {
  saveDraft(DRAFT, { project: "demo", kind: "skill" }, { sessionId: ID });
  const view = renderStudio(apiRoutes);
  const publish = await screen.findByRole("button", { name: "Publish" });
  await waitFor(() => {
    expect(publish).toBeEnabled();
  });
  await userEvent.click(publish);
  return { view, dialog: screen.getByRole("alertdialog") };
}

/** Opens the Publish dialog and confirms it, then waits for the route's request. */
async function openDraft(apiRoutes: ApiRoutes) {
  const { view, dialog } = await openPublish(apiRoutes);
  await userEvent.click(within(dialog).getByRole("button", { name: "Publish" }));
  await waitFor(() => {
    expect(posts(view.requests, PUBLISH)).toHaveLength(1);
  });
  return view;
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
  it("publish_route sends the route and no chat message", async () => {
    const view = await openDraft(routes({ [`POST ${PUBLISH}`]: "pending" }));

    expect(await bodyOf(posts(view.requests, PUBLISH)[0])).toEqual({
      target: null,
      confirm_managed: false,
    });
    expect(posts(view.requests, `${SESSION}/messages`)).toEqual([]);
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByRole("button", { name: "Publishing…" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled();
  });

  it("publish_route shows Published with a link to the item once the route answers", async () => {
    let landed = false;
    const changelog = aCatalogItem({
      name: "changelog",
      source: "demo",
      origin: "project-owned",
      source_path: "plugin/demo/skills/changelog/SKILL.md",
    });
    const view = await openDraft(
      routes({
        "/api/v1/projects/demo/skills": () =>
          landed
            ? aSkillCatalog({ items: [...aSkillCatalog().items, changelog] })
            : aSkillCatalog(),
        [`POST ${PUBLISH}`]: () => {
          landed = true;
          return PUBLISHED;
        },
      }),
    );

    const link = await screen.findByRole("link", { name: "open changelog" });
    expect(link).toHaveAttribute("href", "/projects/demo/skills/skill/demo/changelog");
    expect(screen.getByText("Published.")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(posts(view.requests, `${SESSION}/messages`)).toEqual([]);
    await waitFor(() => {
      expect(storedDraft(DRAFT)?.published).toBe(true);
    });
    expect(openDrafts("demo")).toEqual([]);
  });

  it("publish_route keeps the draft and the session and shows a problem's detail", async () => {
    await openDraft(
      routes({
        [`POST ${PUBLISH}`]: aProblem({
          status: 409,
          title: "Item write refused",
          detail: "A skill named changelog already exists",
          code: "item_exists",
        }),
      }),
    );

    expect(await screen.findByText("A skill named changelog already exists")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Publish" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Discard draft" })).toBeNull();
    expect(screen.queryByText("Published.")).toBeNull();
    expect(screen.getByRole("region", { name: "Conversation with Claude" })).toBeInTheDocument();
    expect(openDrafts("demo").map((d) => d.draftId)).toEqual([DRAFT]);
    expect(storedDraft(DRAFT)?.sessionId).toBe(ID);
  });

  it("publish_secret message says the published file is not versioned", async () => {
    await openDraft(
      routes({ [`POST ${PUBLISH}`]: { ...PUBLISHED, versioned: false, reason: "secret" } }),
    );

    const banner = (await screen.findByText("Published.")).closest(".ah-banner");
    expect(banner).toHaveTextContent("Published. Not versioned: the file matches a secret rule.");
    expect(banner).toHaveClass("ah-banner-warning");
  });

  it.each([
    [
      { ...PUBLISHED, versioned: false, reason: "too_large" },
      "Published. Not versioned: the item is past the size its history keeps.",
    ],
    [
      { ...PUBLISHED, versioned: false, reason: "script_only" },
      "Published. Not versioned: only the hook's scripts were written, and scripts keep no history.",
    ],
    [
      { ...PUBLISHED, changed: false },
      "Nothing changed. The item already matches the draft: nothing was written, and the draft is removed.",
    ],
  ])("publish_route says what an answer did not version or change", async (answer, words) => {
    await openDraft(routes({ [`POST ${PUBLISH}`]: answer }));

    const banner = (await screen.findByText(/^(Published|Nothing changed)\.$/)).closest(
      ".ah-banner",
    );
    expect(banner).toHaveTextContent(words);
  });

  it.each([
    [
      "the draft is already published",
      aProblem({
        status: 409,
        title: "Item write refused",
        detail: "This draft was already published; discard it",
        code: "draft_already_published",
      }),
      "This draft was already published; discard it",
    ],
    [
      "the draft was not removed",
      aProblem({
        status: 500,
        title: "Draft not removed",
        detail: "Published; the draft is still there. Discard it.",
        code: "draft_not_removed",
        published: true,
      }),
      "Published; the draft is still there. Discard it.",
    ],
    [
      "the old item was not removed",
      aProblem({
        status: 500,
        title: "Item write failed",
        detail:
          "Published; the old item could not be removed and stays. The draft is still there: discard it.",
        code: "write_failed",
        kind: "old_not_removed",
        published: true,
      }),
      "Published; the old item could not be removed and stays. The draft is still there: discard it.",
    ],
  ])("publish_route offers Discard when %s", async (_case, problem, detail) => {
    const view = await openDraft(
      routes({ [`POST ${PUBLISH}`]: problem, [`POST ${SESSION}/messages`]: { seq: 5 } }),
    );

    expect(await screen.findByText(detail)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent("Discard this draft?");
    await userEvent.click(within(dialog).getByRole("button", { name: "Discard" }));

    await waitFor(() => {
      expect(posts(view.requests, `${SESSION}/messages`)).toHaveLength(1);
    });
    expect(await bodyOf(posts(view.requests, `${SESSION}/messages`)[0])).toEqual({
      text: discardPrompt(DRAFT),
    });
    expect(posts(view.requests, PUBLISH)).toHaveLength(1);
  });

  it("publish_managed asks again with the warning when the server says the item is managed", async () => {
    let calls = 0;
    const view = await openDraft(
      routes({
        [`POST ${PUBLISH}`]: () =>
          ++calls === 1
            ? aProblem({
                status: 409,
                title: "Item write refused",
                detail: "The item is managed by hub.lock",
                code: "managed_confirmation_required",
              })
            : PUBLISHED,
      }),
    );
    const dialog = screen.getByRole("alertdialog");
    expect(await within(dialog).findByText(PUBLISH_MANAGED_WARNING)).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Publish anyway" }));

    expect(await screen.findByText("Published.")).toBeInTheDocument();
    const sent = posts(view.requests, PUBLISH);
    expect(sent).toHaveLength(2);
    expect(await bodyOf(sent[1])).toEqual({ target: null, confirm_managed: true });
  });

  it("a11y publish dialog has no serious violations and cancels from the keyboard", async () => {
    const { view, dialog } = await openPublish(routes({ [`POST ${PUBLISH}`]: PUBLISHED }));

    expect(await seriousViolations(dialog)).toEqual([]);
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(posts(view.requests, PUBLISH)).toEqual([]);
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

  it("publish_managed warning and flag: a managed item's edit warns, then sends its target and the flag", async () => {
    const edited = `---
name: feature
description: Takes an idea from spec to delivery.
---

# Feature
`;
    saveDraft(
      DRAFT,
      { project: "demo", kind: "skill" },
      { target: TARGET, name: "feature", sessionId: ID },
    );
    const view = renderStudio(
      routes({
        [DETAIL]: aSkillDetail(),
        [`${SESSION}/events`]: {
          items: [
            aLogRecord("user.message", { seq: 1, body: { text: "Shorten it" } }),
            aLogRecord("tool.call", {
              seq: 2,
              body: {
                input: { file_path: `${HUB}/.hub-drafts/${DRAFT}/SKILL.md`, content: edited },
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
        [`POST ${PUBLISH}`]: PUBLISHED,
      }),
    );
    const publish = await screen.findByRole("button", { name: "Publish" });
    await waitFor(() => {
      expect(publish).toBeEnabled();
    });

    await userEvent.click(publish);
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText(PUBLISH_MANAGED_WARNING)).toBeInTheDocument();
    expect(PUBLISH_MANAGED_WARNING).toBe(
      "This file is managed by hub.lock: the next hub sync rewrites it. Publish anyway?",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Publish anyway" }));

    await waitFor(() => {
      expect(posts(view.requests, PUBLISH)).toHaveLength(1);
    });
    expect(await bodyOf(posts(view.requests, PUBLISH)[0])).toEqual({
      target: TARGET,
      confirm_managed: true,
    });
    expect(posts(view.requests, `${SESSION}/messages`)).toEqual([]);
    expect(await screen.findByText("Published.")).toBeInTheDocument();
  });

  it("starts the session on a copy of the item, leaving the original alone", async () => {
    saveDraft(DRAFT, { project: "demo", kind: "skill" }, { target: TARGET, name: "feature" });
    const view = renderStudio(
      routes({
        [DETAIL]: aSkillDetail(),
        "POST /api/v1/agent-sessions": anAgentSession({ id: ID, status: "running" }),
      }),
    );
    expect(await screen.findByRole("link", { name: "Toolkit" })).toBeInTheDocument();
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
