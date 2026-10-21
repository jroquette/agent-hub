import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  aBundledFileText,
  aCatalogItem,
  aSkillCatalog,
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
});
