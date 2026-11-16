import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../testing/axe";
import { RedactionChip } from "./status";
import { JsonViewer } from "./trace";

describe("RedactionChip", () => {
  it("shows a redacted github token with no reveal control", () => {
    render(<RedactionChip kind="github token" />);

    const chip = screen.getByRole("note", { name: "Redacted github token" });
    expect(chip).toHaveTextContent("[redacted: github token]");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      "A github token was removed before storage. The value never reached agent-hub and cannot be revealed.",
    );
  });

  it("renders redacted values of a raw event as chips, so the original matches nothing", () => {
    const { container } = render(
      <JsonViewer value={{ command: "[redacted: github token]", tool: "Bash" }} />,
    );

    expect(screen.getByRole("note", { name: "Redacted github token" })).toBeInTheDocument();
    expect(container.textContent).not.toContain("ghp_");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("calls an unnamed value a secret", () => {
    render(<RedactionChip />);

    expect(screen.getByRole("note", { name: "Redacted secret" })).toBeInTheDocument();
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = render(<RedactionChip kind="bearer token" />);

    expect(await seriousViolations(container)).toEqual([]);
  });
});
