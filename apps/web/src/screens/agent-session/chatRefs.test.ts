import { describe, expect, it, vi } from "vitest";

import type { InlineRef } from "../../components";
import { chatRefs, type ChatRefsSource } from "./chatRefs";

const FILE = "/Users/me/hub/brain/features/claims/reviews/TIP-1564.md";

function finder(overrides: Partial<ChatRefsSource> = {}) {
  return chatRefs({
    ticketKeys: ["TIP"],
    linearBase: "https://linear.app/heytipple",
    ticketRoute: () => null,
    onNavigate: vi.fn(),
    repos: [{ name: "tipple-ui", dir: "tipple-ui", github: "heytipple/tipple-ui" }],
    files: [FILE, "/Users/me/ui/.claude/worktrees/t/src/app.ts"],
    onOpenFile: vi.fn(),
    ...overrides,
  });
}

const refs = (parts: readonly (string | InlineRef)[] | null) =>
  (parts ?? []).filter((part): part is InlineRef => typeof part !== "string");

describe("chatRefs", () => {
  it("links a bare URL without the sentence's full stop", () => {
    const parts = finder()("Opened https://github.com/heytipple/tipple-ui/pull/545.");
    expect(parts).toEqual([
      "Opened ",
      {
        href: "https://github.com/heytipple/tipple-ui/pull/545",
        label: "https://github.com/heytipple/tipple-ui/pull/545",
      },
      ".",
    ]);
  });

  it("links a pull request by owner/repo#n, and repo#n for a repo of the project", () => {
    const found = refs(
      finder()("Merge heytipple/Tipple_API#2391 before tipple-ui#545 and other#3."),
    );
    expect(found.map((ref) => ref.href)).toEqual([
      "https://github.com/heytipple/Tipple_API/pull/2391",
      "https://github.com/heytipple/tipple-ui/pull/545",
    ]);
  });

  it("links a ticket of the project's teams to Linear, else to its feature, else not at all", () => {
    expect(refs(finder()("Moved TIP-1564 to In Review; ABC-1 stays."))).toEqual([
      expect.objectContaining({
        href: "https://linear.app/heytipple/issue/TIP-1564",
        label: "TIP-1564",
      }),
    ]);

    const onNavigate = vi.fn();
    const [ref] = refs(
      finder({
        linearBase: null,
        ticketRoute: (id) => (id === "TIP-1563" ? "/features/tipple/claims" : null),
        onNavigate,
      })("TIP-1563 and TIP-9"),
    );
    ref?.open?.();
    expect(onNavigate).toHaveBeenCalledWith("/features/tipple/claims");
    expect(ref?.label).toBe("TIP-1563");
  });

  it("opens a file of the review by its full path or by a tail that names one file", () => {
    const onOpenFile = vi.fn();
    const find = finder({ onOpenFile });
    const [byTail] = refs(find("reviews/TIP-1564.md now points to the PR"));
    byTail?.open?.();
    expect(onOpenFile).toHaveBeenCalledWith(FILE);
    expect(refs(find(`see ${FILE}`))).toHaveLength(1);
    // Not a file of the review: text, and the ticket inside a path is not split out.
    expect(find("reviews/TIP-1999.md")).toBeNull();
  });

  it("leaves text with nothing to link alone", () => {
    expect(finder()("Nothing here, and/or a fraction 1/2.")).toBeNull();
  });
});
