import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { DiscussProvider, useDiscuss, useDiscussTarget, type DiscussTarget } from "./discuss";
import { DiscussSelection, quoteLabel } from "./DiscussSelection";

describe("quoteLabel", () => {
  it("reads as the quote's first words on one line", () => {
    expect(quoteLabel("Only the live\n  DataMode")).toBe("“Only the live DataMode”");
    expect(quoteLabel("x".repeat(60))).toBe(`“${"x".repeat(39)}…”`);
  });
});

const target: DiscussTarget = {
  key: "feature:demo:x",
  project: "demo",
  kind: "Feature spec",
  title: "x",
};

function Page() {
  useDiscussTarget(target);
  const { references } = useDiscuss();
  return (
    <>
      <main id="main">
        <p>Only the live DataMode selects the source.</p>
        <textarea aria-label="Notes" defaultValue="A note typed on the page." />
      </main>
      <aside>
        <p>Text outside the main column.</p>
      </aside>
      <output>{references.map((r) => r.label).join(",")}</output>
      <DiscussSelection />
    </>
  );
}

/** Selects the contents of `node`, then releases the mouse as a drag-select would. */
function select(node: Node) {
  const range = document.createRange();
  range.selectNodeContents(node);
  act(() => {
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    fireEvent.mouseUp(document);
  });
}

describe("DiscussSelection", () => {
  beforeEach(() => {
    window.localStorage.clear();
    // jsdom lays nothing out and gives a range no box at all.
    Object.defineProperty(Range.prototype, "getBoundingClientRect", {
      configurable: true,
      value: () => new DOMRect(0, 0, 10, 10),
    });
  });
  afterEach(() => {
    window.getSelection()?.removeAllRanges();
    Reflect.deleteProperty(Range.prototype, "getBoundingClientRect");
  });

  it("quotes a selection inside the main column", () => {
    render(
      <DiscussProvider>
        <Page />
      </DiscussProvider>,
    );

    select(screen.getByText("Only the live DataMode selects the source."));
    fireEvent.click(screen.getByRole("button", { name: "Discuss selection" }));

    expect(screen.getByRole("status").textContent).toBe(
      quoteLabel("Only the live DataMode selects the source."),
    );
  });

  it("offers nothing for a selection in a text box or outside the main column", () => {
    render(
      <DiscussProvider>
        <Page />
      </DiscussProvider>,
    );

    select(screen.getByRole("textbox", { name: "Notes" }));
    expect(screen.queryByRole("button", { name: "Discuss selection" })).toBeNull();

    select(screen.getByText("Text outside the main column."));
    expect(screen.queryByRole("button", { name: "Discuss selection" })).toBeNull();
  });
});
