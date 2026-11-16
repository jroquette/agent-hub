import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router";

import { FeatureChip, FeatureLabel } from "./FeatureChip";

describe("FeatureChip", () => {
  it("names the feature and opens its panel, with the fixed label's hover text (AC-425.7)", () => {
    render(
      <MemoryRouter>
        <FeatureChip project="demo" slug="csv-export" />
      </MemoryRouter>,
    );

    const chip = screen.getByRole("link", { name: /csv-export/ });
    expect(chip).toHaveAttribute("href", "/features/demo/csv-export");
    expect(chip).toHaveAttribute(
      "title",
      expect.stringMatching(/never changes.*Open its panel\.$/),
    );
  });

  it("AC-425.7 shows the fixed label on the feature's own page, without a link", () => {
    render(<FeatureLabel slug="csv-export" />);

    const label = screen.getByLabelText("Feature label csv-export");
    expect(label).toHaveTextContent("csv-export");
    expect(label).toHaveAttribute("title", expect.stringMatching(/never changes/));
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
