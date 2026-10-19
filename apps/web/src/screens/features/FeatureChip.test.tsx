import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router";

import { FeatureChip } from "./FeatureChip";

describe("FeatureChip", () => {
  it("names the feature and opens its panel", () => {
    render(
      <MemoryRouter>
        <FeatureChip project="demo" slug="fraud-check-ecommerce-claim" />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: /fraud-check-ecommerce-claim/ })).toHaveAttribute(
      "href",
      "/features/demo/fraud-check-ecommerce-claim",
    );
  });
});
