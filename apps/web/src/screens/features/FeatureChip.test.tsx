import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router";

import { FeatureChip, FeatureLabel } from "./FeatureChip";

describe("FeatureChip", () => {
  it("names the feature and opens its panel", () => {
    render(
      <MemoryRouter>
        <FeatureChip project="demo" slug="csv-export" />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: /csv-export/ })).toHaveAttribute(
      "href",
      "/features/demo/csv-export",
    );
  });

  it("shows the fixed label on the feature's own page, without a link", () => {
    render(<FeatureLabel slug="csv-export" />);

    const label = screen.getByLabelText("Feature label csv-export");
    expect(label).toHaveTextContent("csv-export");
    expect(label).toHaveAttribute("title", expect.stringMatching(/never changes/));
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
