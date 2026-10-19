import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router";

import { FeatureChip } from "./FeatureChip";

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
});
