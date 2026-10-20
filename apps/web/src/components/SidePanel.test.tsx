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
  delete document.documentElement.dataset.theme;
});

describe("SidePanel", () => {
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

  it.each(["light", "dark"])(
    "has no serious axe violation in the %s theme (a11y)",
    async (theme) => {
      document.documentElement.dataset.theme = theme;
      const { container } = render(<Page />);
      await userEvent.click(screen.getByRole("button", { name: "Open AGH-7" }));

      expect(await seriousViolations(container)).toEqual([]);
    },
  );
});
