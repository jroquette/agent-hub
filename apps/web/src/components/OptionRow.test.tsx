import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OptionRow } from "./OptionRow";

describe("OptionRow", () => {
  it("turns its input off and ignores clicks when disabled", async () => {
    const onToggle = vi.fn();
    render(
      <div role="radiogroup" aria-label="Options">
        <OptionRow
          type="radio"
          name="options"
          label="o3 · Render the invoice PDF"
          description="Cannot be picked: draft action."
          checked={false}
          onToggle={onToggle}
          disabled
        />
      </div>,
    );

    const radio = screen.getByRole("radio", { name: "o3 · Render the invoice PDF" });
    expect(radio).toBeDisabled();
    expect(radio).toHaveAccessibleDescription("Cannot be picked: draft action.");
    await userEvent.click(radio);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("keeps its input on by default", () => {
    render(
      <OptionRow
        type="checkbox"
        name="options"
        label="Keep it"
        description={null}
        checked
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByRole("checkbox", { name: "Keep it" })).toBeEnabled();
  });
});
