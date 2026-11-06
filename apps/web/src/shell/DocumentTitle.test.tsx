import { render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";

import { DocumentTitle, documentTitle } from "./DocumentTitle";

describe("documentTitle", () => {
  it("joins the screen, the project and the app name", () => {
    expect(documentTitle("Environments", "demo-api")).toBe("Environments · demo-api · agent-hub");
  });

  it("falls back to the app name alone when the screen has no name yet", () => {
    expect(documentTitle(null, null)).toBe("agent-hub");
  });

  it("does not repeat a project the heading already names", () => {
    expect(documentTitle("demo-api", "demo-api")).toBe("demo-api · agent-hub");
  });
});

describe("DocumentTitle", () => {
  it("names the tab after the screen's heading", async () => {
    render(
      <MemoryRouter initialEntries={["/projects/demo-api/environments"]}>
        <Routes>
          <Route
            path="*"
            element={
              <>
                <DocumentTitle />
                <main id="main">
                  <h1>Environments</h1>
                </main>
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(document.title).toBe("Environments · demo-api · agent-hub");
    });
  });
});
