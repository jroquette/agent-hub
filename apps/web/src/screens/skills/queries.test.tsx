import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { useApi } from "../../lib/api";

import {
  aBundledFileText,
  aCatalogItem,
  aSkillCatalog,
  aProblem,
  aSkillDetail,
  renderWithApi,
} from "../../testing/builders";
import {
  skillRoute,
  usePublishDraft,
  useSkillCatalog,
  useSkillDetail,
  useSkillFile,
  type SkillRef,
} from "./queries";
import { saveDraft, storedDraft } from "./studioDrafts";

const FEATURE = { kind: "skill", source: "hub-workflow", name: "feature" } as const;
const DETAIL = "/api/v1/projects/demo/skills/skill/hub-workflow/feature";

function Probe({ fileEnabled }: { fileEnabled: boolean }) {
  const catalog = useSkillCatalog("demo");
  const detail = useSkillDetail("demo", FEATURE);
  const file = useSkillFile("demo", FEATURE, "0123456789abcdef", fileEnabled);
  return (
    <p>
      {catalog.data?.items.length ?? "-"} {detail.data?.name ?? "-"} {file.data?.path ?? "-"}
    </p>
  );
}

const PUBLISH = "/api/v1/projects/demo/skills/drafts/skill-abc123/publish";

async function bodyOf(request: Request | undefined): Promise<unknown> {
  if (!request) throw new Error("no request");
  return JSON.parse(await request.clone().text()) as unknown;
}

function Publisher({
  target,
  confirmManaged,
}: {
  target: SkillRef | null;
  confirmManaged: boolean;
}) {
  const catalog = useSkillCatalog("demo");
  const publish = usePublishDraft("demo", "skill-abc123");
  return (
    <>
      <p>{catalog.data ? "catalog read" : "-"}</p>
      <button
        type="button"
        onClick={() => {
          publish.mutate({ target, confirmManaged });
        }}
      >
        Publish
      </button>
      <p>{publish.data ? `changed ${String(publish.data.changed)}` : "-"}</p>
    </>
  );
}

const VERSION = `${DETAIL}/versions/0192a5e5-0000-7000-8000-000000000001`;
const AGENT = "/api/v1/projects/demo/skills/agent/hub-workflow/evaluator";

/** Every kind of query a publish could reach, each shown with how many times it was fetched. */
function Reader() {
  const catalog = useSkillCatalog("demo");
  const other = useApi("/api/v1/projects/{project}/skills", { path: { project: "other" } });
  const edited = useSkillDetail("demo", FEATURE);
  const sibling = useSkillDetail("demo", { kind: "agent", source: "hub-workflow", name: "evaluator" });
  const version = useApi(
    "/api/v1/projects/{project}/skills/{kind}/{source}/{name}/versions/{version_id}",
    {
      path: {
        ...FEATURE,
        project: "demo",
        version_id: "0192a5e5-0000-7000-8000-000000000001",
      },
    },
  );
  const publish = usePublishDraft("demo", "skill-abc123");
  const ready = [catalog, other, edited, sibling, version].every((q) => q.data !== undefined);
  return (
    <>
      <p>{ready ? "all read" : "-"}</p>
      <button
        type="button"
        onClick={() => {
          publish.mutate({ target: FEATURE, confirmManaged: false });
        }}
      >
        Publish
      </button>
      <p>{publish.isSuccess ? "published" : "-"}</p>
    </>
  );
}

afterEach(() => {
  window.localStorage.clear();
});

describe("skills queries", () => {
  it("reads the catalog, a detail and a bundled file by id", async () => {
    const { requests } = renderWithApi(<Probe fileEnabled />, {
      routes: {
        "/api/v1/projects/demo/skills": aSkillCatalog(),
        [DETAIL]: aSkillDetail(),
        [`${DETAIL}/files/0123456789abcdef`]: aBundledFileText(),
      },
    });

    expect(await screen.findByText("4 feature references/checklist.md")).toBeInTheDocument();
    expect(requests).toHaveLength(3);
  });

  it("fetches no file while disabled", async () => {
    const { requests } = renderWithApi(<Probe fileEnabled={false} />, {
      routes: { "/api/v1/projects/demo/skills": aSkillCatalog(), [DETAIL]: aSkillDetail() },
    });

    expect(await screen.findByText("4 feature -")).toBeInTheDocument();
    expect(requests).toHaveLength(2);
  });

  it("routes to an item's detail by its id segments", () => {
    expect(skillRoute("demo", aCatalogItem())).toBe(
      "/projects/demo/skills/skill/hub-workflow/feature",
    );
    expect(skillRoute("my hub", { kind: "agent", source: "claude", name: "local-agent" })).toBe(
      "/projects/my%20hub/skills/agent/claude/local-agent",
    );
  });

  it("publishes a draft with its target stated, null for a new item, then reads the catalog again", async () => {
    const { requests } = renderWithApi(<Publisher target={null} confirmManaged={false} />, {
      routes: {
        "/api/v1/projects/demo/skills": aSkillCatalog(),
        [`POST ${PUBLISH}`]: { changed: true, versioned: true, reason: null, version: null },
      },
    });
    await screen.findByText("catalog read");

    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    expect(await screen.findByText("changed true")).toBeInTheDocument();
    const sent = requests.filter((r) => r.method === "POST");
    expect(sent.map((r) => new URL(r.url).pathname)).toEqual([PUBLISH]);
    expect(await bodyOf(sent[0])).toEqual({
      target: null,
      confirm_managed: false,
    });
    await waitFor(() => {
      expect(requests.filter((r) => r.method === "GET")).toHaveLength(2);
    });
  });

  it("names an edit's item as its target and passes the managed confirmation", async () => {
    const { requests } = renderWithApi(<Publisher target={FEATURE} confirmManaged />, {
      routes: {
        "/api/v1/projects/demo/skills": aSkillCatalog(),
        [`POST ${PUBLISH}`]: { changed: true, versioned: true, reason: null, version: null },
      },
    });
    await screen.findByText("catalog read");

    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    expect(await screen.findByText("changed true")).toBeInTheDocument();
    const sent = requests.find((r) => r.method === "POST");
    expect(await bodyOf(sent)).toEqual({
      target: { kind: "skill", source: "hub-workflow", name: "feature" },
      confirm_managed: true,
    });
  });

  it("reads the project's Toolkit again after a publish, but not the edited item, a version's content or another project", async () => {
    // A rename (feature -> feature2) removes the edited item: reading its detail again would 404
    // under the Studio that edits it. It is marked stale for the next visit instead.
    const view = renderWithApi(<Reader />, {
      routes: {
        "/api/v1/projects/demo/skills": aSkillCatalog(),
        "/api/v1/projects/other/skills": aSkillCatalog({ project: "other" }),
        [DETAIL]: aSkillDetail(),
        [AGENT]: aSkillDetail({ kind: "agent", name: "evaluator" }),
        [VERSION]: { id: "v", unit_kind: "folder", files: [] },
        [`POST ${PUBLISH}`]: { changed: true, versioned: true, reason: null, version: null },
      },
    });
    await screen.findByText("all read");
    const gets = (path: string) =>
      view.requests.filter((r) => r.method === "GET" && new URL(r.url).pathname === path);

    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    expect(await screen.findByText("published")).toBeInTheDocument();
    await waitFor(() => {
      expect(gets("/api/v1/projects/demo/skills")).toHaveLength(2);
      expect(gets(AGENT)).toHaveLength(2);
    });
    expect(gets(DETAIL)).toHaveLength(1);
    expect(gets(VERSION)).toHaveLength(1);
    expect(gets("/api/v1/projects/other/skills")).toHaveLength(1);
    const detailKey = [
      "api",
      "/api/v1/projects/{project}/skills/{kind}/{source}/{name}",
      { path: { project: "demo", ...FEATURE } },
    ];
    expect(view.queryClient.getQueryState(detailKey)?.isInvalidated).toBe(true);
  });

  it("records a publish, or a spent draft, on the stored draft even once its screen is gone", async () => {
    saveDraft("skill-abc123", { project: "demo", kind: "skill" }, { sessionId: "s" });
    const answered = renderWithApi(<Publisher target={null} confirmManaged={false} />, {
      routes: {
        "/api/v1/projects/demo/skills": aSkillCatalog(),
        [`POST ${PUBLISH}`]: { changed: true, versioned: true, reason: null, version: null },
      },
    });
    await screen.findByText("catalog read");
    screen.getByRole("button", { name: "Publish" }).click();
    answered.unmount();
    await waitFor(() => {
      expect(storedDraft("skill-abc123")?.published).toBe(true);
    });

    saveDraft("skill-def456", { project: "demo", kind: "skill" }, { sessionId: "s" });
    const spent = renderWithApi(<SpentPublisher />, {
      routes: {
        "/api/v1/projects/demo/skills": aSkillCatalog(),
        "POST /api/v1/projects/demo/skills/drafts/skill-def456/publish": aProblem({
          status: 500,
          title: "Draft not removed",
          code: "draft_not_removed",
          published: true,
        }),
      },
    });
    await screen.findByText("catalog read");
    screen.getByRole("button", { name: "Publish" }).click();
    spent.unmount();
    await waitFor(() => {
      expect(storedDraft("skill-def456")?.spent).toBe(true);
    });
    expect(storedDraft("skill-def456")?.published).toBe(false);
  });
});

function SpentPublisher() {
  const catalog = useSkillCatalog("demo");
  const publish = usePublishDraft("demo", "skill-def456");
  return (
    <>
      <p>{catalog.data ? "catalog read" : "-"}</p>
      <button
        type="button"
        onClick={() => {
          publish.mutate({ target: null, confirmManaged: false });
        }}
      >
        Publish
      </button>
    </>
  );
}
