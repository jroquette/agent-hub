import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import { aPage, aSearchHit, renderWithApi } from "../testing/builders";
import { CommandPalette } from "./CommandPalette";

describe("CommandPalette", () => {
  it("lists screens when the query is empty", () => {
    renderWithApi(<CommandPalette onClose={vi.fn()} />);

    expect(screen.getByRole("option", { name: /Live sessions/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Portfolio/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("groups search hits by kind when the query matches", async () => {
    renderWithApi(<CommandPalette onClose={vi.fn()} initialQuery="5091" />, {
      routes: {
        "/api/v1/search": aPage([
          aSearchHit(),
          aSearchHit({ kind: "run", label: "Run a1b2c3d4", href: "/runs/a1b2c3d4e5f6" }),
        ]),
      },
    });

    expect(await screen.findByText("Session 5091b986")).toBeInTheDocument();
    expect(screen.getByText("Sessions")).toHaveClass("ah-palette-group");
    expect(screen.getByText("Workflow runs")).toHaveClass("ah-palette-group");
  });

  it("opens the selected result with Enter after moving with the arrows", async () => {
    const onClose = vi.fn();
    const { router } = renderWithApi(<CommandPalette onClose={onClose} initialQuery="run" />, {
      routes: {
        "/api/v1/search": aPage([
          aSearchHit(),
          aSearchHit({ kind: "run", label: "Run a1b2c3d4", href: "/runs/a1b2c3d4e5f6" }),
        ]),
      },
    });
    await screen.findByText("Run a1b2c3d4");
    const input = screen.getByRole("combobox");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(router.state.location.pathname).toBe("/runs/a1b2c3d4e5f6");
    expect(onClose).toHaveBeenCalled();
  });

  it("says what to try when nothing matches", async () => {
    renderWithApi(<CommandPalette onClose={vi.fn()} initialQuery="brain_memry" />, {
      routes: { "/api/v1/search": aPage([]) },
    });

    expect(
      await screen.findByText(/No match for "brain_memry". Try an issue key like AGH-48/),
    ).toBeInTheDocument();
  });

  it("debounces the search while typing", async () => {
    const { requests } = renderWithApi(<CommandPalette onClose={vi.fn()} />, {
      routes: { "/api/v1/search": aPage([]) },
    });
    const input = screen.getByRole("combobox");

    fireEvent.change(input, { target: { value: "ag" } });
    fireEvent.change(input, { target: { value: "agh" } });

    await waitFor(() => {
      expect(requests).toHaveLength(1);
    });
    expect(new URL(requests[0]?.url ?? "").searchParams.get("q")).toBe("agh");
  });

  it("closes on Escape and on a click outside", () => {
    const onClose = vi.fn();
    renderWithApi(<CommandPalette onClose={onClose} />);

    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    act(() => {
      fireEvent.click(screen.getByTestId("palette-scrim"));
    });

    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = renderWithApi(<CommandPalette onClose={vi.fn()} />);

    expect(await seriousViolations(container)).toEqual([]);
  });
});
