import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import { SidePanel } from "./SidePanel";

/** A page with an opener before the panel and a control after it, outside it. */
function Page() {
  const opener = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        ref={opener}
        onClick={() => {
          setOpen(true);
        }}
      >
        Open AGH-7
      </button>
      {open && (
        <SidePanel
          title="Ticket AGH-7 · Load the layers"
          closeLabel="Close ticket AGH-7"
          openerRef={opener}
          onClose={() => {
            setOpen(false);
          }}
        >
          <button type="button">Inside</button>
        </SidePanel>
      )}
      <button type="button">After</button>
    </>
  );
}

/** Answers `(min-width: 1600px)` as a screen `width` px wide would. */
function screenWidth(width: number) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query === "(min-width: 1600px)" && width >= 1600,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SidePanel (AC-1.10)", () => {
  it("renders a labelled aside region, not a dialog (no focus trap, no scrim)", async () => {
    render(<Page />);
    await userEvent.click(screen.getByRole("button", { name: "Open AGH-7" }));

    const panel = screen.getByRole("complementary", { name: "Ticket AGH-7 · Load the layers" });
    expect(panel.tagName).toBe("ASIDE");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.querySelector(".ah-scrim")).toBeNull();
    // Tab leaves the panel: its last control is followed by the page's next one.
    screen.getByRole("button", { name: "Inside" }).focus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "After" })).toHaveFocus();
  });

  it("moves focus to its heading on open", async () => {
    render(<Page />);
    await userEvent.click(screen.getByRole("button", { name: "Open AGH-7" }));

    expect(screen.getByRole("heading", { name: "Ticket AGH-7 · Load the layers" })).toHaveFocus();
  });

  it("Esc closes and returns focus to the opener", async () => {
    render(<Page />);
    await userEvent.click(screen.getByRole("button", { name: "Open AGH-7" }));

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("complementary")).toBeNull();
    expect(screen.getByRole("button", { name: "Open AGH-7" })).toHaveFocus();
    await userEvent.click(screen.getByRole("button", { name: "Open AGH-7" }));
    await userEvent.click(screen.getByRole("button", { name: "Close ticket AGH-7" }));
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(screen.getByRole("button", { name: "Open AGH-7" })).toHaveFocus();
  });

  // AGH-330 R2: a reader who moved focus elsewhere on the page keeps it when the panel closes.
  it("leaves focus where the reader put it when the panel closes", async () => {
    render(<Page />);
    await userEvent.click(screen.getByRole("button", { name: "Open AGH-7" }));
    screen.getByRole("button", { name: "After" }).focus();

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("complementary")).toBeNull();
    expect(screen.getByRole("button", { name: "After" })).toHaveFocus();
  });

  it("overlays at 1280 and docks at 1600", async () => {
    screenWidth(1280);
    const { unmount } = render(<Page />);
    await userEvent.click(screen.getByRole("button", { name: "Open AGH-7" }));
    expect(screen.getByRole("complementary")).toHaveAttribute("data-layout", "overlay");
    unmount();

    screenWidth(1600);
    render(<Page />);
    await userEvent.click(screen.getByRole("button", { name: "Open AGH-7" }));
    expect(screen.getByRole("complementary")).toHaveAttribute("data-layout", "docked");
  });

  // Structure, names and roles (A16): theme contrast is tokens.test.ts's.
  it("has no serious axe violation (a11y)", async () => {
    const { container } = render(<Page />);
    await userEvent.click(screen.getByRole("button", { name: "Open AGH-7" }));

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("SidePanel footer and initial focus (AC-417.8)", () => {
  it("keeps the footer's actions below the body and focuses the control it names", () => {
    const opener = { current: null };
    render(
      <SidePanel
        title="demo-api › api"
        closeLabel="Close demo-api › api"
        openerRef={opener}
        onClose={vi.fn()}
        initialFocus="#address-staging"
        footer={<button type="button">Save changes</button>}
      >
        <input aria-label="Address in local" />
        <input id="address-staging" aria-label="Address in staging" />
      </SidePanel>,
    );

    expect(screen.getByRole("textbox", { name: "Address in staging" })).toHaveFocus();
    const footer = screen.getByRole("button", { name: "Save changes" }).parentElement;
    expect(footer).toHaveClass("ah-side-panel-foot");
    expect(footer?.previousElementSibling).toHaveClass("ah-side-panel-body");
  });

  it("focuses the heading when the named control is not there", () => {
    render(
      <SidePanel
        title="demo-api › api"
        closeLabel="Close demo-api › api"
        openerRef={{ current: null }}
        onClose={vi.fn()}
        initialFocus="#nowhere"
      />,
    );

    expect(screen.getByRole("heading", { name: "demo-api › api" })).toHaveFocus();
    expect(document.querySelector(".ah-side-panel-foot")).toBeNull();
  });
});
