import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { aSession, aSessionLabel, anAgentSession, anId } from "../../testing/builders";
import { DIGEST_MS, LiveDigest, type DigestSection } from "./LiveDigest";
import type { SectionId } from "./sections";

const named = (
  n: number,
  status: "waiting" | "live" | "idle" | "ended",
  outcome = null as null | "error",
) =>
  aSession({
    id: anId(n, "dddd0000"),
    status,
    outcome,
    label: aSessionLabel({ issue: null, workflow: `/s${String(n)}`, workflows: [] }),
  });

type Rows = Partial<Record<SectionId, ReturnType<typeof named>[]>>;

const sections = (rows: Rows): DigestSection[] =>
  (["waiting", "live", "idle", "ended"] as const).map((id) => ({ id, rows: rows[id] ?? [] }));

const region = () => screen.getByTestId("live-digest");

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-16T10:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("LiveDigest (digest)", () => {
  it("announces politely a session that starts waiting and a running one that ends", () => {
    const view = render(
      <LiveDigest sections={sections({ live: [named(1, "live"), named(2, "live")] })} settled />,
    );
    expect(region()).toHaveAttribute("aria-live", "polite");
    expect(region().textContent).toBe("");

    view.rerender(
      <LiveDigest
        sections={sections({ waiting: [named(1, "waiting")], ended: [named(2, "ended", "error")] })}
        settled
      />,
    );

    expect(region()).toHaveTextContent(
      "1 session waiting for approval: /s1. Session ended: /s2, error.",
    );
  });

  it("names a driven session without a twin by its title", () => {
    const driven = anAgentSession({
      id: anId(9, "0192a5e5"),
      title: "Build it",
      status: "running",
    });
    const view = render(<LiveDigest sections={sections({})} settled />);
    view.rerender(
      <LiveDigest
        sections={[
          { id: "waiting", rows: [{ ...driven, status: "waiting_permission" }] },
          { id: "live", rows: [] },
        ]}
        settled
      />,
    );

    expect(region()).toHaveTextContent("1 session waiting for approval: Build it.");
  });

  it("says nothing for the first rows, for ended rows it never saw running, or for a session that leaves", () => {
    const view = render(
      <LiveDigest sections={sections({ waiting: [named(1, "waiting")] })} settled />,
    );
    expect(region().textContent).toBe("");

    // Load more brings older ended rows; the waiting one is answered and goes live.
    view.rerender(
      <LiveDigest
        sections={sections({ live: [named(1, "live")], ended: [named(5, "ended")] })}
        settled
      />,
    );
    expect(region().textContent).toBe("");
  });

  it("takes the rows after an unsettled spell (loading, filter placeholder, Load more) as the new baseline", () => {
    const view = render(<LiveDigest sections={sections({ live: [named(1, "live")] })} settled />);
    view.rerender(<LiveDigest sections={sections({ live: [named(1, "live")] })} settled={false} />);
    view.rerender(
      <LiveDigest
        sections={sections({ waiting: [named(1, "waiting"), named(2, "waiting")] })}
        settled
      />,
    );
    expect(region().textContent).toBe("");

    view.rerender(
      <LiveDigest
        sections={sections({
          waiting: [named(1, "waiting"), named(2, "waiting"), named(3, "waiting")],
        })}
        settled
      />,
    );
    expect(region()).toHaveTextContent("1 session waiting for approval: /s3.");
  });

  it("announces at most once per 15 s, holding a change until the 15 s edge", () => {
    const view = render(
      <LiveDigest sections={sections({ live: [named(1, "live"), named(2, "live")] })} settled />,
    );
    view.rerender(
      <LiveDigest
        sections={sections({ waiting: [named(1, "waiting")], live: [named(2, "live")] })}
        settled
      />,
    );
    expect(region()).toHaveTextContent("/s1");

    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    view.rerender(
      <LiveDigest
        sections={sections({ waiting: [named(1, "waiting"), named(2, "waiting")] })}
        settled
      />,
    );
    expect(region()).toHaveTextContent("1 session waiting for approval: /s1.");

    act(() => {
      vi.advanceTimersByTime(DIGEST_MS - 1_000 - 1);
    });
    expect(region()).toHaveTextContent("1 session waiting for approval: /s1.");
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(region()).toHaveTextContent("1 session waiting for approval: /s2.");
    expect(DIGEST_MS).toBe(15_000);
  });

  it("drops a held change that is undone before the 15 s edge", () => {
    const view = render(
      <LiveDigest sections={sections({ live: [named(1, "live"), named(2, "live")] })} settled />,
    );
    view.rerender(
      <LiveDigest
        sections={sections({ waiting: [named(1, "waiting")], live: [named(2, "live")] })}
        settled
      />,
    );
    view.rerender(
      <LiveDigest
        sections={sections({ waiting: [named(1, "waiting"), named(2, "waiting")] })}
        settled
      />,
    );
    view.rerender(
      <LiveDigest
        sections={sections({ waiting: [named(1, "waiting")], live: [named(2, "live")] })}
        settled
      />,
    );

    act(() => {
      vi.advanceTimersByTime(DIGEST_MS);
    });
    expect(region()).toHaveTextContent("1 session waiting for approval: /s1.");
  });

  it("says a repeated message again: the same session waits, is answered, and waits again past 15 s", () => {
    const view = render(<LiveDigest sections={sections({ live: [named(1, "live")] })} settled />);
    view.rerender(<LiveDigest sections={sections({ waiting: [named(1, "waiting")] })} settled />);
    const first = region().firstElementChild;
    expect(first).toHaveTextContent("1 session waiting for approval: /s1.");

    view.rerender(<LiveDigest sections={sections({ live: [named(1, "live")] })} settled />);
    act(() => {
      vi.advanceTimersByTime(DIGEST_MS);
    });
    view.rerender(<LiveDigest sections={sections({ waiting: [named(1, "waiting")] })} settled />);

    const second = region().firstElementChild;
    expect(second).toHaveTextContent("1 session waiting for approval: /s1.");
    expect(second).not.toBe(first);
  });

  it("takes the rows of another query (resetKey) as the new baseline", () => {
    const view = render(
      <LiveDigest sections={sections({ live: [named(1, "live")] })} settled resetKey="a" />,
    );
    view.rerender(
      <LiveDigest sections={sections({ waiting: [named(1, "waiting")] })} settled resetKey="b" />,
    );
    expect(region().textContent).toBe("");

    view.rerender(
      <LiveDigest
        sections={sections({ waiting: [named(1, "waiting"), named(2, "waiting")] })}
        settled
        resetKey="b"
      />,
    );
    expect(region()).toHaveTextContent("1 session waiting for approval: /s2.");
  });
});
