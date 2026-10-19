import { describe, expect, it, vi } from "vitest";

import type { InlineRef } from "../../components";
import { chatRefs, type ChatRefsSource } from "./chatRefs";

const FILE = "/Users/me/hub/brain/features/claims/reviews/DEM-64.md";

function finder(overrides: Partial<ChatRefsSource> = {}) {
  return chatRefs({
    ticketKeys: ["DEM"],
    linearBase: "https://linear.app/acme",
    ticketRoute: () => null,
    onNavigate: vi.fn(),
    repos: [{ name: "demo-web", dir: "demo-web", github: "acme/demo-web" }],
    files: [FILE, "/Users/me/ui/.claude/worktrees/t/src/app.ts"],
    onOpenFile: vi.fn(),
    ...overrides,
  });
}

const refs = (parts: readonly (string | InlineRef)[] | null) =>
  (parts ?? []).filter((part): part is InlineRef => typeof part !== "string");

describe("chatRefs", () => {
  it("links a bare URL without the sentence's full stop", () => {
    const parts = finder()("Opened https://github.com/acme/demo-web/pull/545.");
    expect(parts).toEqual([
      "Opened ",
      {
        href: "https://github.com/acme/demo-web/pull/545",
        label: "https://github.com/acme/demo-web/pull/545",
      },
      ".",
    ]);
  });

  it("links a pull request by owner/repo#n, and repo#n for a repo of the project", () => {
    const found = refs(finder()("Merge acme/demo-api#2391 before demo-web#545 and other#3."));
    expect(found.map((ref) => ref.href)).toEqual([
      "https://github.com/acme/demo-api/pull/2391",
      "https://github.com/acme/demo-web/pull/545",
    ]);
  });

  it("links a ticket of the project's teams to Linear, else to its feature, else not at all", () => {
    expect(refs(finder()("Moved DEM-64 to In Review; ABC-1 stays."))).toEqual([
      expect.objectContaining({
        href: "https://linear.app/acme/issue/DEM-64",
        label: "DEM-64",
      }),
    ]);

    const onNavigate = vi.fn();
    const [ref] = refs(
      finder({
        linearBase: null,
        ticketRoute: (id) => (id === "DEM-63" ? "/features/demo/claims" : null),
        onNavigate,
      })("DEM-63 and DEM-9"),
    );
    ref?.open?.();
    expect(onNavigate).toHaveBeenCalledWith("/features/demo/claims");
    expect(ref?.label).toBe("DEM-63");
  });

  it("opens a file of the review by its full path or by a tail that names one file", () => {
    const onOpenFile = vi.fn();
    const find = finder({ onOpenFile });
    const [byTail] = refs(find("reviews/DEM-64.md now points to the PR"));
    byTail?.open?.();
    expect(onOpenFile).toHaveBeenCalledWith(FILE);
    expect(refs(find(`see ${FILE}`))).toHaveLength(1);
    // Not a file of the review: text, and the ticket inside a path is not split out.
    expect(find("reviews/DEM-99.md")).toBeNull();
  });

  it("leaves text with nothing to link alone", () => {
    expect(finder()("Nothing here, and/or a fraction 1/2.")).toBeNull();
  });
});
