import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { Diagnostics } from "./Diagnostics";

const FINDINGS = [
  {
    code: "name_mismatch",
    severity: "warning",
    message: "name: Feature is not the folder feature",
  },
  { code: "unknown_key", severity: "info", message: "reviewers: not understood by Claude Code" },
] as const;

describe("Diagnostics", () => {
  it("states each finding's severity and code as text beside its icon", () => {
    render(<Diagnostics diagnostics={[...FINDINGS]} />);

    const list = screen.getByRole("list", { name: "Diagnostics" });
    const [warning, info] = within(list).getAllByRole("listitem");
    expect(warning).toHaveTextContent("Warning");
    expect(warning).toHaveTextContent("name_mismatch");
    expect(warning).toHaveTextContent("name: Feature is not the folder feature");
    expect(info).toHaveTextContent("Info");
    expect(info).toHaveTextContent("unknown_key");
    expect(screen.getByRole("heading", { name: /Diagnostics/ })).toHaveTextContent("2");
    expect(screen.getByText(/never blocks/)).toBeInTheDocument();
  });

  it("says there is nothing to report when the list is empty", () => {
    render(<Diagnostics diagnostics={[]} />);

    expect(screen.getByText(/No diagnostics/)).toBeInTheDocument();
    expect(screen.queryByRole("list")).toBeNull();
  });
});

describe("Diagnostics a11y", () => {
  it("has no serious or critical axe violation", async () => {
    const { container } = render(<Diagnostics diagnostics={[...FINDINGS]} />);

    expect(await seriousViolations(container)).toEqual([]);
  });
});
