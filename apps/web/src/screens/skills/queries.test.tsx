import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  aBundledFileText,
  aCatalogItem,
  aSkillCatalog,
  aSkillDetail,
  renderWithApi,
} from "../../testing/builders";
import { skillRoute, useSkillCatalog, useSkillDetail, useSkillFile } from "./queries";

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
});
