import { readFileSync } from "node:fs";

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PreferencesProvider } from "../../lib/preferences";
import { at } from "../../testing/builders";
import { MessageMeta } from "./MessageMeta";

describe("MessageMeta (message-meta)", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("shows a relative time with the absolute time in its title, in UTC when chosen (AC-234.22)", () => {
    vi.useFakeTimers({ now: Date.parse(at(5 + 3 * 60)) });
    localStorage.setItem("ah.tz", "utc");
    render(
      <PreferencesProvider>
        <MessageMeta at={at(5)} text="x" />
      </PreferencesProvider>,
    );

    const time = screen.getByText("3 min ago");
    expect(time.tagName).toBe("TIME");
    expect(time).toHaveAttribute("datetime", at(5));
    expect(time).toHaveAttribute("title", "11 Oct 2026, 14:00:05 UTC");
  });

  it("gives the absolute time in the browser's zone by default", () => {
    vi.useFakeTimers({ now: Date.parse(at(5)) });
    render(<MessageMeta at={at(5)} text="x" />);

    const local = new Date(at(5));
    const hours = String(local.getHours()).padStart(2, "0");
    const minutes = String(local.getMinutes()).padStart(2, "0");
    expect(screen.getByText("just now")).toHaveAttribute(
      "title",
      expect.stringContaining(`${hours}:${minutes}:05`),
    );
  });

  it("says just now up to 59 s and 1 min ago from 60 s", () => {
    vi.useFakeTimers({ now: Date.parse(at(60)) });
    render(
      <>
        <MessageMeta at={at(1)} text="x" />
        <MessageMeta at={at(0)} text="y" />
      </>,
    );

    expect(screen.getByText("just now")).toHaveAttribute("datetime", at(1));
    expect(screen.getByText("1 min ago")).toHaveAttribute("datetime", at(0));
  });

  it("copies the raw markdown when Copy is pressed", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<MessageMeta at={at(0)} text={"Hello **bold**\n\n```ts\nx\n```"} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy message" }));

    expect(writeText).toHaveBeenCalledWith("Hello **bold**\n\n```ts\nx\n```");
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("shows only Copy when the message has no time yet", () => {
    const { container } = render(<MessageMeta at={null} text="x" />);

    expect(container.querySelector("time")).toBeNull();
    expect(screen.getByRole("button", { name: "Copy message" })).toBeInTheDocument();
  });

  it("refreshes every time on one shared minute timer, not one per message", () => {
    vi.useFakeTimers({ now: Date.parse(at(0)) });
    const setInterval = vi.spyOn(globalThis, "setInterval");
    render(
      <>
        <MessageMeta at={at(-5)} text="a" />
        <MessageMeta at={at(-3)} text="b" />
        <MessageMeta at={at(-1)} text="c" />
      </>,
    );
    expect(screen.getAllByText("just now")).toHaveLength(3);
    expect(setInterval).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(60_000);
    });

    expect(screen.getAllByText("1 min ago")).toHaveLength(3);
    expect(setInterval).toHaveBeenCalledTimes(1);
  });

  it("reveals the row on hover and focus, and always shows it without hover", () => {
    // Read as a file: Vitest runs from apps/web.
    const css = readFileSync("src/screens/agent-session/agent-session.css", "utf8");
    expect(css).toMatch(/\.as-meta\s*\{[^}]*opacity:\s*0/);
    expect(css).toMatch(
      /\.as-msg:hover \.as-meta,\s*\.as-msg:focus-within \.as-meta\s*\{[^}]*opacity:\s*1/,
    );
    expect(css).toMatch(/@media \(hover: none\)\s*\{\s*\.as-meta\s*\{[^}]*opacity:\s*1/);
  });
});
