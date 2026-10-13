import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, onTestFinished, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aSkillDetail } from "../../testing/builders";
import { BodyView, scrollToAnchor } from "./BodyView";

const DETAIL = aSkillDetail();

function view(overrides: Partial<Parameters<typeof BodyView>[0]> = {}) {
  return render(
    <BodyView
      body={DETAIL.body ?? null}
      raw={DETAIL.raw ?? null}
      toc={DETAIL.toc}
      {...overrides}
    />,
  );
}

describe("BodyView detail_header_raw", () => {
  it("lists the headings and scrolls to each one's anchor when an entry is chosen (AC-164.17)", () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    onTestFinished(() => {
      Reflect.deleteProperty(Element.prototype, "scrollIntoView");
    });
    const { container } = view();

    const toc = screen.getByRole("navigation", { name: "Contents" });
    const links = within(toc).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(["Feature", "Steps", "Notes"]);
    for (const link of links) {
      const id = (link.getAttribute("href") ?? "").slice(1);
      expect(container.querySelector(`[id="${id}"]`)?.tagName).toMatch(/^H[1-6]$/);
    }
    const [, steps] = links;
    if (steps) fireEvent.click(steps);
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(scroll.mock.contexts[0]).toBe(container.querySelector("#md-steps"));
  });

  it("renders the body with step anchors and no raw HTML", () => {
    const { container } = view();

    expect(container.querySelector("#step-1")?.tagName).toBe("LI");
    expect(container.querySelector("#step-5")).not.toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: "Steps" })).toBeInTheDocument();
  });

  it("shows the exact file text when Raw is chosen and back when Rendered is", () => {
    const { container } = view();

    fireEvent.click(screen.getByRole("button", { name: "Raw" }));

    const raw = container.querySelector("pre.ah-skill-raw");
    expect(raw?.textContent).toBe(DETAIL.raw);
    expect(screen.getByRole("button", { name: "Raw" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("navigation", { name: "Contents" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Rendered" }));
    expect(container.querySelector("pre.ah-skill-raw")).toBeNull();
  });

  it("follows a controlled view when the page owns it", () => {
    const onViewChange = vi.fn();
    view({ view: "raw", onViewChange });

    expect(
      screen.getByRole("region", { name: "Text" }).querySelector("pre.ah-skill-raw"),
    ).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Rendered" }));
    expect(onViewChange).toHaveBeenCalledWith("rendered");
  });

  it("hands relative links to the page's resolver", () => {
    const open = vi.fn();
    render(
      <BodyView
        body="See [the checklist](references/checklist.md)."
        raw={null}
        toc={[]}
        localLink={() => ({ href: "#skill-file-1", open })}
      />,
    );

    fireEvent.click(screen.getByRole("link", { name: "the checklist" }));
    expect(open).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Raw" })).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Contents" })).toBeNull();
  });

  it("explains an unread file when there is no body", () => {
    view({ body: null, raw: null });

    expect(screen.getByText(/was not read/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Raw" })).toBeNull();
  });

  it("does nothing when asked to scroll to a missing anchor", () => {
    expect(() => {
      scrollToAnchor("md-nowhere");
    }).not.toThrow();
  });
});

describe("BodyView a11y", () => {
  it("has no serious or critical axe violation in either view", async () => {
    const { container } = view();
    expect(await seriousViolations(container)).toEqual([]);

    fireEvent.click(screen.getByRole("button", { name: "Raw" }));
    expect(await seriousViolations(container)).toEqual([]);
  });
});
