import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router";

import { FeatureChip } from "./FeatureChip";

describe("FeatureChip", () => {
  it("names the feature and opens its panel", () => {
    render(
      <MemoryRouter>
        <FeatureChip project="tipple" slug="allianz-ecommerce-claim" />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: /allianz-ecommerce-claim/ })).toHaveAttribute(
      "href",
      "/features/tipple/allianz-ecommerce-claim",
    );
  });
});
