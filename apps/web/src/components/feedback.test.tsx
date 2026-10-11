import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import { Banner, ConfirmDialog, EmptyState, ProblemError, Skeleton, Toast } from "./feedback";

afterEach(() => {
  vi.useRealTimers();
});

describe("Skeleton", () => {
  it("shows only after 300 ms so fast answers never flash it", () => {
    vi.useFakeTimers();
    const { container } = render(<Skeleton width={40} />);
    expect(container.querySelector(".ah-skel")).toBeNull();

    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(container.querySelector(".ah-skel")).not.toBeNull();
  });

  it("shows at once with lines when the delay is 0", () => {
    const { container } = render(<Skeleton lines={3} delay={0} />);

    expect(container.querySelectorAll(".ah-skel")).toHaveLength(3);
  });
});

describe("EmptyState", () => {
  it("explains why and gives the next command", () => {
    render(
      <EmptyState
        icon="radio"
        title="No live sessions"
        command="hub web"
        action={<button type="button">Go</button>}
      >
        Start a Claude Code session in the hub.
      </EmptyState>,
    );

    expect(screen.getByRole("heading", { name: "No live sessions" })).toBeInTheDocument();
    expect(screen.getByText("hub web")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy command" })).toBeInTheDocument();
  });
});

describe("ProblemError", () => {
  it("shows the problem's title, detail and Try again in a region alert", () => {
    const onRetry = vi.fn();
    render(
      <ProblemError
        title="Could not load sessions"
        detail="Collector database busy"
        status={503}
        type="https://agent-hub/problems/busy"
        instance="/api/v1/sessions"
        onRetry={onRetry}
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Could not load sessions");
    expect(alert).toHaveTextContent("Collector database busy");
    expect(alert).toHaveTextContent(
      "HTTP 503 · https://agent-hub/problems/busy · /api/v1/sessions",
    );
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("hides the metadata when compact and the button without a retry", () => {
    render(<ProblemError status={500} compact />);

    expect(screen.queryByText(/HTTP/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("Banner and Toast", () => {
  it("uses an alert for errors and a status otherwise, with dismiss", () => {
    const onDismiss = vi.fn();
    render(
      <>
        <Banner tone="error">Broken</Banner>
        <Banner tone="warning" boxed onDismiss={onDismiss}>
          Careful
        </Banner>
      </>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Broken");
    expect(screen.getByRole("status")).toHaveClass("ah-banner-boxed");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalled();
  });

  it("offers undo on a toast", () => {
    const onUndo = vi.fn();
    render(
      <Toast tone="error" onUndo={onUndo}>
        Hub removed
      </Toast>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(onUndo).toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveClass("ah-toast-error");
  });
});

describe("ConfirmDialog", () => {
  it("enables the verb only after the required text is typed", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        title="Remove hub agent-hub?"
        confirmLabel="Remove hub"
        consequences={["Its events stay in the database."]}
        requireText="agent-hub"
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      >
        The hub stops showing in every view.
      </ConfirmDialog>,
    );

    const confirm = screen.getByRole("button", { name: "Remove hub" });
    expect(screen.getByRole("alertdialog", { name: "Remove hub agent-hub?" })).toBeInTheDocument();
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "agent-hub" } });
    fireEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalled();
  });

  it("disables a later phase's confirmation", () => {
    render(
      <ConfirmDialog title="Approve?" confirmLabel="Approve" tone="primary" phase="P4" inline />,
    );

    expect(screen.getByRole("button", { name: /Approve/ })).toBeDisabled();
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = render(
      <div>
        <ProblemError title="Could not load" detail="x" onRetry={vi.fn()} />
        <EmptyState title="Nothing yet" />
        <Banner tone="offline">Offline</Banner>
      </div>,
    );

    expect(await seriousViolations(container)).toEqual([]);
  });
});
