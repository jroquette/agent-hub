import { act, screen, waitFor, within } from "@testing-library/react";
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

/** The live regions (and live roles) whose text holds `text`, outermost only: one per announcement. */
function announcing(text: string): Element[] {
  const live = [...document.querySelectorAll('[aria-live], [role="status"], [role="alert"]')];
  return live.filter(
    (node) =>
      node.textContent.includes(text) &&
      !live.some((outer) => outer !== node && outer.contains(node)),
  );
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

describe("StudioScreen (files)", () => {
  // AC-596.5.22: a draft's file is coloured by the language its path names.
  it("colours each draft file by its language", async () => {
    const script = "def notes(prs):\n    return [pr.title for pr in prs]\n";
    const base = routes();
    const events = base[`${SESSION}/events`] as { items: unknown[]; next_after: null };
    saveDraft(DRAFT, { project: "demo", kind: "skill" }, { sessionId: ID });
    renderStudio({
      ...base,
      [`${SESSION}/events`]: {
        ...events,
        items: [
          ...events.items.slice(0, 3),
          aLogRecord("tool.call", {
            seq: 4,
            body: {
              input: {
                file_path: `${HUB}/.hub-drafts/${DRAFT}/scripts/notes.py`,
                content: script,
              },
              name: "Write",
              parent_tool_use_id: null,
              tool_use_id: "toolu_02",
            },
          }),
          aLogRecord("tool.result", { seq: 5 }),
          aLogRecord("result", { seq: 6 }),
        ],
      },
      [SESSION]: anAgentSession({ id: ID, status: "idle", last_seq: 6 }),
    });

    await userEvent.click(await screen.findByRole("button", { name: /^Files 2/ }));
    const tree = screen.getByRole("list", { name: "Draft files" });
    await userEvent.click(within(tree).getByRole("button", { name: /scripts\/notes\.py/ }));
    const python = screen.getByLabelText("scripts/notes.py").querySelector("code");
    await waitFor(() => {
      expect(python).toHaveClass("hljs");
    });
    expect(python?.querySelector(".hljs-keyword")).toHaveTextContent("def");

    await userEvent.click(within(tree).getByRole("button", { name: /SKILL\.md/ }));
    const markdown = screen.getByLabelText("SKILL.md").querySelector("code");
    await waitFor(() => {
      expect(markdown).toHaveClass("hljs");
    });
    expect(markdown?.querySelector("span[class^='hljs-']")).not.toBeNull();
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

  it("publish_route records the publish when the Studio is left while it runs", async () => {
    const { view, dialog } = await openPublish(routes({ [`POST ${PUBLISH}`]: PUBLISHED }));

    act(() => {
      within(dialog).getByRole("button", { name: "Publish" }).click();
    });
    view.unmount();

    await waitFor(() => {
      expect(storedDraft(DRAFT)?.published).toBe(true);
    });
    expect(openDrafts("demo")).toEqual([]);
  });

  it("publish_route sends one request when Publish is pressed twice at once", async () => {
    const { view, dialog } = await openPublish(routes({ [`POST ${PUBLISH}`]: PUBLISHED }));
    const confirm = within(dialog).getByRole("button", { name: "Publish" });

    act(() => {
      confirm.click();
      confirm.click();
    });

    expect(await screen.findByText("Published.")).toBeInTheDocument();
    expect(posts(view.requests, PUBLISH)).toHaveLength(1);
  });

  it("publish_route says Publishing once, in the page's live region mounted before it", async () => {
    const { view, dialog } = await openPublish(routes({ [`POST ${PUBLISH}`]: "pending" }));
    const region = view.container.querySelector('.ah-sr[aria-live="polite"]');
    expect(region).toBeInTheDocument();
    expect(region?.textContent).toBe("");

    await userEvent.click(within(dialog).getByRole("button", { name: "Publish" }));

    expect(region).toHaveTextContent("Publishing…");
    expect(view.container.querySelector('.ah-sr[aria-live="polite"]')).toBe(region);
    // Not from inside the busy dialog too.
    expect(announcing("Publishing…")).toEqual([region]);
  });

  it("publish_route says Published in the page's live region, then focuses the result", async () => {
    const { view, dialog } = await openPublish(routes({ [`POST ${PUBLISH}`]: PUBLISHED }));
    const region = view.container.querySelector('.ah-sr[aria-live="polite"]');
    expect(region).toBeInTheDocument();
    expect(region?.textContent).toBe("");

    await userEvent.click(within(dialog).getByRole("button", { name: "Publish" }));

    await waitFor(() => {
      expect(region).toHaveTextContent("Published.");
    });
    const result = (await screen.findByText("Published.")).closest("[tabindex]");
    await waitFor(() => {
      expect(result).toHaveFocus();
    });
    // One announcement: the focused result is a named region, and its banner is not live.
    expect(announcing("Published.")).toEqual([region]);
    expect(result).toHaveAccessibleName("Publish result");
  });

  it("publish_route says a problem once and focuses it again on a second identical failure", async () => {
    const { view, dialog } = await openPublish(
      routes({
        [`POST ${PUBLISH}`]: aProblem({
          status: 409,
          title: "Item write refused",
          detail: "A skill named changelog already exists",
          code: "item_exists",
        }),
      }),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Publish" }));
    const notice = (await screen.findByText("A skill named changelog already exists")).closest(
      "[tabindex]",
    );
    await waitFor(() => {
      expect(notice).toHaveFocus();
    });
    const region = view.container.querySelector('.ah-sr[aria-live="polite"]');
    expect(announcing("A skill named changelog already exists")).toEqual([region]);

    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    await userEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Publish" }),
    );

    await waitFor(() => {
      expect(posts(view.requests, PUBLISH)).toHaveLength(2);
    });
    const again = (await screen.findByText("A skill named changelog already exists")).closest(
      "[tabindex]",
    );
    await waitFor(() => {
      expect(again).toHaveFocus();
    });
  });

  it("publish_route focuses Discard draft when the draft is spent", async () => {
    await openDraft(
      routes({
        [`POST ${PUBLISH}`]: aProblem({
          status: 409,
          title: "Item write refused",
          detail: "This draft was already published; discard it",
          code: "draft_already_published",
        }),
      }),
    );

    const discard = await screen.findByRole("button", { name: "Discard draft" });
    await waitFor(() => {
      expect(discard).toHaveFocus();
    });
  });

  it("publish_route offers Discard again when a spent draft is reopened", async () => {
    saveDraft(DRAFT, { project: "demo", kind: "skill" }, { sessionId: ID, spent: true });
    renderStudio(routes());

    expect(await screen.findByRole("button", { name: "Discard draft" })).toBeInTheDocument();
    expect(screen.getByText("This draft was already published; discard it.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
    expect(screen.queryByText(/nothing is published until you click Publish/)).toBeNull();
    expect(screen.getByText(/stays until you discard it/)).toBeInTheDocument();
  });

  it("publish_route shows a reopened spent draft with the server's own detail", async () => {
    const detail =
      "Published; the old item could not be removed and stays. The draft is still there: discard it.";
    saveDraft(
      DRAFT,
      { project: "demo", kind: "skill" },
      { sessionId: ID, spent: true, spentDetail: detail },
    );
    renderStudio(routes());

    expect(await screen.findByText(detail)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discard draft" })).toBeInTheDocument();
  });

  it("publish_managed announces the server's warning and focuses Publish anyway", async () => {
    let calls = 0;
    const { dialog } = await openPublish(
      routes({
        [`POST ${PUBLISH}`]: () =>
          ++calls === 1
            ? aProblem({
                status: 409,
                title: "Item write refused",
                code: "managed_confirmation_required",
              })
            : PUBLISHED,
      }),
    );
    const region = dialog.querySelector('.ah-sr[aria-live="polite"]');

    await userEvent.click(within(dialog).getByRole("button", { name: "Publish" }));

    const anyway = await within(dialog).findByRole("button", { name: "Publish anyway" });
    await waitFor(() => {
      expect(anyway).toHaveFocus();
    });
    expect(region).toHaveTextContent(PUBLISH_MANAGED_WARNING);
    expect(announcing(PUBLISH_MANAGED_WARNING)).toEqual([region]);
  });
});

describe("StudioScreen (edit an existing item)", () => {
  const TARGET = { kind: "skill" as const, source: "hub-workflow", name: "feature" };
  const DETAIL = "/api/v1/projects/demo/skills/skill/hub-workflow/feature";
  const SOURCE = "plugin/hub-workflow/skills/feature/SKILL.md";

  /** The session of an edit that renamed feature to feature2. */
  function renamedEvents() {
    const renamed =
      "---\nname: feature2\ndescription: Takes an idea from spec to delivery.\n---\n\n# Feature\n";
    return {
      items: [
        aLogRecord("user.message", { seq: 1, body: { text: "Rename it" } }),
        aLogRecord("tool.call", {
          seq: 2,
          body: {
            input: { file_path: `${HUB}/.hub-drafts/${DRAFT}/SKILL.md`, content: renamed },
            name: "Write",
            parent_tool_use_id: null,
            tool_use_id: "toolu_01",
          },
        }),
        aLogRecord("tool.result", { seq: 3 }),
        aLogRecord("result", { seq: 4 }),
      ],
      next_after: null,
    };
  }

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

  it("publish_route links a renamed item by its new name, also when the draft is reopened", async () => {
    const renamed = `---
name: feature2
description: Takes an idea from spec to delivery.
---

# Feature
`;
    let landed = false;
    const feature2 = aCatalogItem({ name: "feature2" });
    const editRoutes = routes({
      "/api/v1/projects/demo/skills": () =>
        landed
          ? aSkillCatalog({
              items: [...aSkillCatalog().items.filter((i) => i.name !== "feature"), feature2],
            })
          : aSkillCatalog(),
      [DETAIL]: () =>
        landed
          ? aProblem({ status: 404, title: "Not found", detail: "No skill feature." })
          : aSkillDetail(),
      [`${SESSION}/events`]: {
        items: [
          aLogRecord("user.message", { seq: 1, body: { text: "Rename it" } }),
          aLogRecord("tool.call", {
            seq: 2,
            body: {
              input: { file_path: `${HUB}/.hub-drafts/${DRAFT}/SKILL.md`, content: renamed },
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
      [`POST ${PUBLISH}`]: () => {
        landed = true;
        return PUBLISHED;
      },
    });
    saveDraft(
      DRAFT,
      { project: "demo", kind: "skill" },
      { target: TARGET, name: "feature", sessionId: ID },
    );
    const view = renderStudio(editRoutes);
    const publish = await screen.findByRole("button", { name: "Publish" });
    await waitFor(() => {
      expect(publish).toBeEnabled();
    });
    await userEvent.click(publish);
    await userEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Publish anyway" }),
    );

    const link = await screen.findByRole("link", { name: "open feature2" });
    expect(link).toHaveAttribute("href", "/projects/demo/skills/skill/hub-workflow/feature2");
    expect(screen.queryByText("feature is not in the catalog any more.")).toBeNull();
    view.unmount();

    renderStudio(editRoutes);

    expect(await screen.findByRole("link", { name: "open feature2" })).toBeInTheDocument();
    expect(screen.getByText("Published.")).toBeInTheDocument();
    expect(screen.queryByText("feature is not in the catalog any more.")).toBeNull();
  });

  it("shows that an unpublished edit draft's item is gone, on reopen and on a read again", async () => {
    saveDraft(
      DRAFT,
      { project: "demo", kind: "skill" },
      { target: TARGET, name: "feature", sessionId: ID, sourcePath: SOURCE },
    );
    const gone = renderStudio(
      routes({
        [DETAIL]: aProblem({ status: 404, title: "Not found", detail: "No skill feature." }),
      }),
    );
    expect(await screen.findByText("feature is not in the catalog any more.")).toBeInTheDocument();
    gone.unmount();

    let deleted = false;
    const view = renderStudio(
      routes({
        [DETAIL]: () =>
          deleted
            ? aProblem({ status: 404, title: "Not found", detail: "No skill feature." })
            : aSkillDetail(),
      }),
    );
    expect(await screen.findByRole("button", { name: "Publish" })).toBeInTheDocument();
    deleted = true;
    await act(async () => {
      await view.queryClient.refetchQueries();
    });

    expect(await screen.findByText("feature is not in the catalog any more.")).toBeInTheDocument();
  });

  it("publish_route reopens a renamed, published edit without its old place", async () => {
    saveDraft(
      DRAFT,
      { project: "demo", kind: "skill" },
      { target: TARGET, name: "feature2", sessionId: ID, sourcePath: SOURCE, published: true },
    );
    renderStudio(
      routes({
        "/api/v1/projects/demo/skills": aSkillCatalog({
          items: [
            ...aSkillCatalog().items.filter((i) => i.name !== "feature"),
            aCatalogItem({ name: "feature2" }),
          ],
        }),
        [DETAIL]: aProblem({ status: 404, title: "Not found", detail: "No skill feature." }),
        [`${SESSION}/events`]: renamedEvents(),
      }),
    );

    expect(await screen.findByRole("link", { name: "open feature2" })).toBeInTheDocument();
    expect(screen.queryByText(/the original is unchanged until you click Publish/)).toBeNull();
    expect(screen.queryByText(/Publishes to/)).toBeNull();
    expect(screen.queryByText("plugin/hub-workflow/skills/feature/", { exact: false })).toBeNull();
    expect(screen.queryByText(SOURCE, { exact: false })).toBeNull();
    expect(screen.getByText(/Published from/)).toBeInTheDocument();
    expect(screen.getByText(/The item's earlier text is in its history/)).toBeInTheDocument();
  });

  it("keeps an edit draft's place in the list and its time when it is opened", async () => {
    const AT = new Date("2026-10-11T14:00:00.000Z");
    saveDraft(
      DRAFT,
      { project: "demo", kind: "skill" },
      { target: TARGET, name: "changelog", sessionId: ID, sourcePath: SOURCE },
      AT,
    );
    saveDraft("agent-zzz999", { project: "demo", kind: "agent" }, { name: "other" }, AT);
    renderStudio(routes({ [DETAIL]: aSkillDetail() }));

    expect(await screen.findByRole("button", { name: "Publish" })).toBeInTheDocument();
    expect(openDrafts("demo").map((d) => d.draftId)).toEqual(["agent-zzz999", DRAFT]);
    expect(storedDraft(DRAFT)?.updatedAt).toBe(AT.toISOString());
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
