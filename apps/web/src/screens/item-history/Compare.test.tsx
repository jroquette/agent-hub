import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import * as diffs from "../agent-session/model";

import {
  anItemVersion,
  anItemVersionContent,
  anItemVersionPage,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { HistoryPanel } from ".";
import { COMPARE_MAX_LINES } from "./model";
import type { HistoryTarget } from "./queries";

// The real diff, counted: Compare must compute it once per pair, not on every render.
vi.mock("../agent-session/model", async (importOriginal) => {
  const real = await importOriginal<typeof import("../agent-session/model")>();
  return { ...real, unifiedDiff: vi.fn(real.unifiedDiff) };
});

const AGENT = "/api/v1/projects/demo/skills/agent/hub-workflow/evaluator/versions";
const SKILL = "/api/v1/projects/demo/skills/skill/hub-workflow/feature/versions";
const id = (n: number) => `0199f0a1-0000-7000-8000-00000000000${String(n)}`;
const hash = (head: string) => `sha256:${head}${"0".repeat(56)}`;

/** Three versions, newest first: `3`, `2`, `1` (hashes `33333333`, `22222222`, `11111111`). */
const THREE = [3, 2, 1].map((n) =>
  anItemVersion({
    id: id(n),
    origin: n === 1 ? "external" : "publish",
    first: n === 1,
    author: n === 1 ? null : anItemVersion().author,
    recorded_at: new Date(Date.now() - (4 - n) * 3_600_000).toISOString(),
    content_hash: hash(String(n).repeat(8)),
  }),
);

/** A version's checkbox: its hash, then its origin (a restore can repeat a hash). */
const picked = (head: string) => new RegExp(`^Select ${head} \\(.+\\) to compare$`);

function renderPanel(target: HistoryTarget, routes: ApiRoutes) {
  return renderWithApi(<HistoryPanel target={target} />, { routes });
}

async function compare(first: string, second: string) {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Show history" }));
  await user.click(await screen.findByRole("checkbox", { name: picked(first) }));
  await user.click(screen.getByRole("checkbox", { name: picked(second) }));
  await user.click(screen.getByRole("button", { name: "Compare" }));
  return user;
}

describe("Compare", () => {
  it("compare_any_two non-adjacent versions shows the older against the newer", async () => {
    const file = (text: string) => [
      { path: "evaluator.md", executable: false, size: text.length, text },
    ];
    renderPanel(
      {
        kind: "item",
        project: "demo",
        item: { kind: "agent", source: "hub-workflow", name: "evaluator" },
      },
      {
        [AGENT]: anItemVersionPage({ items: THREE, unit_kind: "agent" }),
        [`${AGENT}/${id(1)}`]: anItemVersionContent({
          id: id(1),
          unit_kind: "agent",
          files: file("alpha\nbeta\n"),
        }),
        [`${AGENT}/${id(3)}`]: anItemVersionContent({
          id: id(3),
          unit_kind: "agent",
          files: file("alpha\ngamma\n"),
        }),
      },
    );

    // Picked newest first: the diff still runs from the older to the newer.
    await compare("33333333", "11111111");

    const diff = await screen.findByLabelText("Changes to evaluator.md");
    expect(diff.tagName).toBe("PRE");
    expect(diff).toHaveTextContent("-beta");
    expect(diff).toHaveTextContent("+gamma");
    expect(screen.getByRole("heading", { name: "From 11111111 to 33333333" })).toBeInTheDocument();
  });

  it("compare_any_two folder versions list added removed and bit changes", async () => {
    renderPanel(
      {
        kind: "item",
        project: "demo",
        item: { kind: "skill", source: "hub-workflow", name: "feature" },
      },
      {
        [SKILL]: anItemVersionPage({ items: THREE }),
        [`${SKILL}/${id(1)}`]: anItemVersionContent({
          id: id(1),
          files: [
            { path: "SKILL.md", executable: false, size: 3, text: "one" },
            { path: "references/old.md", executable: false, size: 3, text: "old" },
            { path: "scripts/run.sh", executable: false, size: 4, text: "echo" },
          ],
        }),
        [`${SKILL}/${id(2)}`]: anItemVersionContent({
          id: id(2),
          files: [
            { path: "SKILL.md", executable: false, size: 3, text: "two" },
            { path: "references/new.md", executable: false, size: 3, text: "new" },
            { path: "scripts/run.sh", executable: true, size: 4, text: "echo" },
          ],
        }),
      },
    );

    await compare("11111111", "22222222");

    const region = await screen.findByRole("region", { name: "From 11111111 to 22222222" });
    await within(region).findByLabelText("Changes to SKILL.md");
    expect(within(region).getByText("Added")).toBeInTheDocument();
    expect(within(region).getByText("Removed")).toBeInTheDocument();
    expect(within(region).getByLabelText("Changes to references/new.md")).toHaveTextContent("+new");
    expect(within(region).getByLabelText("Changes to references/old.md")).toHaveTextContent("-old");
    expect(within(region).getByText("Executable bit: off → on")).toBeInTheDocument();
    expect(within(region).queryByLabelText("Changes to scripts/run.sh")).toBeNull();
  });

  it("compare_any_two keeps the last two picked and waits for two", async () => {
    const user = userEvent.setup();
    renderPanel(
      {
        kind: "item",
        project: "demo",
        item: { kind: "skill", source: "hub-workflow", name: "feature" },
      },
      { [SKILL]: anItemVersionPage({ items: THREE }) },
    );

    await user.click(screen.getByRole("button", { name: "Show history" }));
    const pick = (h: string) => screen.getByRole("checkbox", { name: picked(h) });
    await user.click(await screen.findByRole("checkbox", { name: picked("33333333") }));
    expect(screen.getByRole("button", { name: "Compare" })).toBeDisabled();
    await user.click(pick("22222222"));
    await user.click(pick("11111111"));

    expect(pick("33333333")).not.toBeChecked();
    expect(pick("22222222")).toBeChecked();
    expect(pick("11111111")).toBeChecked();
    expect(screen.getByRole("button", { name: "Compare" })).toBeEnabled();
  });

  it("compare_any_two cuts the diffs at the line budget and says how many lines are left", async () => {
    // One line past the budget: three header lines and COMPARE_MAX_LINES - 2 added lines.
    const big = Array.from({ length: COMPARE_MAX_LINES - 2 }, (_, i) => `line ${String(i)}`).join(
      "\n",
    );
    renderPanel(
      {
        kind: "item",
        project: "demo",
        item: { kind: "skill", source: "hub-workflow", name: "feature" },
      },
      {
        [SKILL]: anItemVersionPage({ items: THREE }),
        [`${SKILL}/${id(1)}`]: anItemVersionContent({ id: id(1), files: [] }),
        [`${SKILL}/${id(2)}`]: anItemVersionContent({
          id: id(2),
          files: [
            { path: "a.md", executable: false, size: big.length, text: big },
            { path: "b.md", executable: false, size: 3, text: "two" },
          ],
        }),
      },
    );

    await compare("11111111", "22222222");

    const diff = await screen.findByLabelText("Changes to a.md");
    expect(diff.querySelectorAll(":scope > span")).toHaveLength(COMPARE_MAX_LINES);
    expect(screen.getByText("1 more line — too large to show here")).toBeInTheDocument();
    // The budget is spent: b.md is listed, not diffed.
    expect(screen.queryByLabelText("Changes to b.md")).toBeNull();
    expect(screen.getByText("Diff not shown — too large to show here.")).toBeInTheDocument();
  });

  it("compare_any_two computes the diffs once when the panel renders again", async () => {
    const unified = vi.mocked(diffs.unifiedDiff);
    renderPanel(
      {
        kind: "item",
        project: "demo",
        item: { kind: "skill", source: "hub-workflow", name: "feature" },
      },
      {
        [SKILL]: anItemVersionPage({ items: THREE }),
        [`${SKILL}/${id(1)}`]: anItemVersionContent({ id: id(1) }),
        [`${SKILL}/${id(3)}`]: anItemVersionContent({
          id: id(3),
          files: [{ path: "SKILL.md", executable: false, size: 4, text: "new\n" }],
        }),
      },
    );

    const user = await compare("11111111", "33333333");
    await screen.findByLabelText("Changes to SKILL.md");
    const calls = unified.mock.calls.length;
    expect(calls).toBeGreaterThan(0);
    // Picking another version re-renders the panel and Compare with it.
    await user.click(screen.getByRole("checkbox", { name: picked("22222222") }));

    expect(screen.getByLabelText("Changes to SKILL.md")).toBeInTheDocument();
    expect(unified.mock.calls.length).toBe(calls);
  });

  it("compare_any_two names the binary file when only its bytes differ", async () => {
    const binary = { path: "logo.png", executable: false, size: 64, text: null };
    renderPanel(
      {
        kind: "item",
        project: "demo",
        item: { kind: "skill", source: "hub-workflow", name: "feature" },
      },
      {
        [SKILL]: anItemVersionPage({ items: THREE }),
        [`${SKILL}/${id(1)}`]: anItemVersionContent({ id: id(1), files: [binary] }),
        [`${SKILL}/${id(2)}`]: anItemVersionContent({ id: id(2), files: [binary] }),
      },
    );

    await compare("11111111", "22222222");

    const region = await screen.findByRole("region", { name: "From 11111111 to 22222222" });
    await within(region).findByText(/differ in bytes the app cannot show/);
    expect(region).toHaveTextContent("in the binary file logo.png.");
    expect(region).not.toHaveTextContent("same content");
  });

  it("compare moves focus to its heading and back to Compare when closed", async () => {
    renderPanel(
      {
        kind: "item",
        project: "demo",
        item: { kind: "skill", source: "hub-workflow", name: "feature" },
      },
      {
        [SKILL]: anItemVersionPage({ items: THREE }),
        [`${SKILL}/${id(1)}`]: anItemVersionContent({ id: id(1) }),
        [`${SKILL}/${id(2)}`]: anItemVersionContent({ id: id(2) }),
      },
    );

    const user = await compare("11111111", "22222222");

    expect(screen.getByRole("heading", { name: "From 11111111 to 22222222" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Close compare" }));
    expect(screen.queryByRole("region", { name: "From 11111111 to 22222222" })).toBeNull();
    expect(screen.getByRole("button", { name: "Compare" })).toHaveFocus();
  });
});
