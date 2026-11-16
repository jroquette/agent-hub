import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Icon } from "./Icon";
import { ICON_NAMES } from "./icons";

describe("Icon", () => {
  it("draws the Lucide nodes of the named icon on a 24 grid", () => {
    const { container } = render(<Icon name="activity" />);

    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("viewBox", "0 0 24 24");
    expect(svg).toHaveClass("ah-icon");
    expect(svg?.querySelectorAll("path")).toHaveLength(1);
  });

  it("is hidden from assistive technology when it has no title", () => {
    const { container } = render(<Icon name="search" />);

    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("is an image named by its title when it has one", () => {
    const { getByRole } = render(<Icon name="info" title="warning" />);

    expect(getByRole("img", { name: "warning" })).toBeInTheDocument();
  });

  it("adds the size class of sm and lg icons", () => {
    const { container } = render(
      <>
        <Icon name="check" size="sm" />
        <Icon name="check" size="lg" />
      </>,
    );

    const [small, large] = Array.from(container.querySelectorAll("svg"));
    expect(small).toHaveClass("ah-icon-sm");
    expect(large).toHaveClass("ah-icon-lg");
  });

  it("generates every icon the design uses", () => {
    expect(ICON_NAMES).toEqual(
      expect.arrayContaining(["layout-dashboard", "stamp", "radio", "eye-off"]),
    );
    expect(ICON_NAMES.length).toBeGreaterThan(120);
  });
});
