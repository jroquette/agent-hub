import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OptionRow } from "./OptionRow";

describe("OptionRow (AC-417.7)", () => {
  it("puts its icon between the input and the label, hidden from assistive tech", () => {
    const { container } = render(
      <OptionRow
        type="radio"
        name="kind"
        label="API or backend"
        description="A server agents call over HTTP."
        checked={false}
        onToggle={vi.fn()}
        icon="plug"
      />,
    );

    const box = container.querySelector(".ah-option-icon");
    expect(box).toHaveAttribute("aria-hidden", "true");
    expect(box?.previousElementSibling).toBe(screen.getByRole("radio", { name: "API or backend" }));
  });

  it("turns its input off when disabled, so a click does not pick it", async () => {
    const onToggle = vi.fn();
    const { container } = render(
      <OptionRow
        type="radio"
        name="access"
        label="Can change data"
        description="Stricter than the team's only."
        checked={false}
        onToggle={onToggle}
        disabled
      />,
    );

    const radio = screen.getByRole("radio", { name: "Can change data" });
    expect(radio).toBeDisabled();
    expect(radio).toHaveAccessibleDescription("Stricter than the team's only.");
    await userEvent.click(radio);
    expect(onToggle).not.toHaveBeenCalled();
    expect(container.querySelector(".ah-option-disabled")).not.toBeNull();
  });
});
