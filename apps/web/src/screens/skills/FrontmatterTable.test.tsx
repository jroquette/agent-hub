import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aSkillDetail } from "../../testing/builders";
import { FrontmatterTable, frontmatterText } from "./FrontmatterTable";

function nth(list: HTMLElement[], index: number): HTMLElement {
  const element = list[index];
  if (!element) throw new Error(`No element ${String(index)}`);
  return element;
}

const PAIRS = [
  ...aSkillDetail().frontmatter,
  { key: "allowed-tools", known: true, value: ["Read", "Grep"] },
  { key: "metadata", known: true, value: { owner: "platform", tier: "core" } },
  { key: "description-long", known: false, value: "line one\nline two" },
];

describe("FrontmatterTable detail_header_raw", () => {
  it("lists pairs in file order and flags unknown keys as not understood, not as errors (AC-164.17)", () => {
    const { container } = render(<FrontmatterTable pairs={PAIRS} />);

    const table = screen.getByRole("table", { name: "Frontmatter" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getAllByRole("cell")[0]?.textContent)).toEqual([
      "name",
      "description",
      "argument-hint",
      "reviewers",
      "allowed-tools",
      "metadata",
      "description-long",
    ]);
    expect(rows[3]).toHaveTextContent("not understood by Claude Code");
    expect(rows[0]).not.toHaveTextContent("not understood");
    expect(container.querySelector("[role='alert'], .ah-banner-error")).toBeNull();
    expect(
      within(nth(rows, 4))
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["Read", "Grep"]);
    expect(rows[5]).toHaveTextContent("owner: platform");
    expect(rows[5]).toHaveTextContent("tier: core");
  });

  it("says no frontmatter was read when there are no pairs", () => {
    render(<FrontmatterTable pairs={[]} />);

    expect(screen.getByText(/No frontmatter was read/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("writes any value as one line of text", () => {
    expect(frontmatterText("x")).toBe("x");
    expect(frontmatterText(["a", "b"])).toBe("a, b");
    expect(frontmatterText({ k: "v", w: "z" })).toBe("k: v; w: z");
  });
});

describe("FrontmatterTable a11y", () => {
  it("has no serious or critical axe violation", async () => {
    const { container } = render(<FrontmatterTable pairs={PAIRS} />);

    expect(await seriousViolations(container)).toEqual([]);
  });
});
