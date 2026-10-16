import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import { Dialog } from "./Dialog";

afterEach(() => {
  document.body.style.overflow = "";
});

function stack(lower: ReactNode, upper: ReactNode = null) {
  return (
    <>
      {lower}
      {upper}
    </>
  );
}

describe("Dialog", () => {
  it("renders a labelled modal dialog in a portal, with a close X and a footer", async () => {
    const onClose = vi.fn();
    const { container } = render(
      <Dialog title="Rename hub" size="lg" onClose={onClose} footer={<button>Save</button>}>
        <input aria-label="Name" />
      </Dialog>,
    );

    const dialog = screen.getByRole("dialog", { name: "Rename hub" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveClass("ah-dialog-lg");
    expect(container).toBeEmptyDOMElement();
    expect(dialog.closest(".ah-scrim")?.parentElement).toBe(document.body);
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(await seriousViolations(document.body)).toEqual([]);
  });

  it("renders in place without locking scroll when inline", () => {
    const { container } = render(<Dialog title="Preview" inline />);

    expect(container.querySelector("[role=dialog]")).not.toBeNull();
    expect(document.body.style.overflow).toBe("");
  });

  it("focuses the first control after the header, or the one asked for", () => {
    const { unmount } = render(
      <Dialog title="Edit" onClose={vi.fn()} footer={<button>Save</button>}>
        <input aria-label="Name" />
        <input aria-label="Note" />
      </Dialog>,
    );
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveFocus();
    unmount();

    render(
      <Dialog title="Edit" onClose={vi.fn()} initialFocus="[aria-label=Note]">
        <input aria-label="Name" />
        <input aria-label="Note" />
      </Dialog>,
    );
    expect(screen.getByRole("textbox", { name: "Note" })).toHaveFocus();
  });

  it("keeps Tab inside the dialog", async () => {
    render(
      <>
        <button>Outside</button>
        <Dialog title="Edit" onClose={vi.fn()} footer={<button>Save</button>}>
          <input aria-label="Name" />
        </Dialog>
      </>,
    );
    const close = screen.getByRole("button", { name: "Close" });
    const save = screen.getByRole("button", { name: "Save" });

    save.focus();
    await userEvent.tab();
    expect(close).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(save).toHaveFocus();
  });

  it("closes only the topmost of two stacked dialogs on Escape", async () => {
    const lower = vi.fn();
    const upper = vi.fn();
    const lowerDialog = <Dialog key="lower" title="Lower" onClose={lower} />;
    const { rerender } = render(stack(lowerDialog));
    rerender(stack(lowerDialog, <Dialog key="upper" title="Upper" onClose={upper} />));

    await userEvent.keyboard("{Escape}");
    expect(upper).toHaveBeenCalledTimes(1);
    expect(lower).not.toHaveBeenCalled();

    rerender(stack(lowerDialog));
    await userEvent.keyboard("{Escape}");
    expect(lower).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape, the X and the scrim while pending", async () => {
    const lower = vi.fn();
    const upper = vi.fn();
    const lowerDialog = <Dialog key="lower" title="Lower" onClose={lower} />;
    const { rerender } = render(stack(lowerDialog));
    rerender(stack(lowerDialog, <Dialog key="upper" title="Upper" onClose={upper} pending />));

    await userEvent.keyboard("{Escape}");
    for (const top of screen.getAllByRole("presentation").slice(1)) {
      fireEvent.mouseDown(top);
      fireEvent.click(top);
    }

    expect(screen.getAllByRole("button", { name: "Close" })[1]).toBeDisabled();
    expect(upper).not.toHaveBeenCalled();
    expect(lower).not.toHaveBeenCalled();
  });

  it("moves focus to the dialog when the focused control turns disabled while pending", () => {
    const footer = (pending: boolean) => <button disabled={pending}>Save</button>;
    const { rerender } = render(<Dialog title="Edit" onClose={vi.fn()} footer={footer(false)} />);
    screen.getByRole("button", { name: "Save" }).focus();

    rerender(<Dialog title="Edit" onClose={vi.fn()} footer={footer(true)} pending />);

    expect(screen.getByRole("dialog")).toHaveFocus();
  });

  it("closes on the scrim only when the press also started on the scrim", () => {
    const onClose = vi.fn();
    render(
      <Dialog title="Edit" onClose={onClose}>
        <p>Body text</p>
      </Dialog>,
    );
    const scrim = screen.getByRole("presentation");

    fireEvent.mouseDown(screen.getByText("Body text"));
    fireEvent.click(scrim);
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.mouseDown(screen.getByText("Body text"));
    fireEvent.click(screen.getByText("Body text"));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.mouseDown(scrim);
    fireEvent.click(scrim);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("locks body scroll until the last dialog closes", () => {
    document.body.style.overflow = "scroll";
    const lowerDialog = <Dialog key="lower" title="Lower" />;
    const { rerender, unmount } = render(stack(lowerDialog));
    rerender(stack(lowerDialog, <Dialog key="upper" title="Upper" />));
    expect(document.body.style.overflow).toBe("hidden");

    rerender(stack(lowerDialog));
    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.body.style.overflow).toBe("scroll");
  });

  it("returns focus to the opener on close", async () => {
    function Opener() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button
            onClick={() => {
              setOpen(true);
            }}
          >
            Rename
          </button>
          {open && (
            <Dialog
              title="Rename hub"
              onClose={() => {
                setOpen(false);
              }}
            >
              <input aria-label="Name" />
            </Dialog>
          )}
        </>
      );
    }
    render(<Opener />);

    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Rename" })).toHaveFocus();
  });
});
