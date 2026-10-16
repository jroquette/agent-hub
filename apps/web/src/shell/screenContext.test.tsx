import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DiscussProvider, useDiscuss, useDiscussTarget, type DiscussTarget } from "./discuss";
import { readScreenText, readScreenTitle, screenDiscussTarget } from "./screenContext";

function column(html: string): HTMLElement {
  const main = document.createElement("main");
  main.innerHTML = html;
  return main;
}

describe("screenDiscussTarget", () => {
  it("keys one conversation per project and path whatever the filters", () => {
    const a = screenDiscussTarget({
      project: "agent-hub",
      pathname: "/sessions",
      search: "?status=live",
      title: "Sessions",
    });
    const b = screenDiscussTarget({
      project: "agent-hub",
      pathname: "/sessions",
      search: "",
      title: "Sessions",
    });
    expect(a.key).toBe("screen:agent-hub:/sessions");
    expect(b.key).toBe(a.key);
    expect(a).toMatchObject({ kind: "Screen", title: "Sessions", screen: true });
    expect(a.brief).toContain("`/sessions?status=live`");
  });

  it("names the screen by its path when it has no heading", () => {
    const target = screenDiscussTarget({
      project: "p",
      pathname: "/runs",
      search: "",
      title: null,
    });
    expect(target.title).toBe("/runs");
  });
});

describe("readScreenTitle", () => {
  it("reads the page heading, else the breadcrumb's current page", () => {
    expect(readScreenTitle(column("<h1> Sessions </h1>"))).toBe("Sessions");
    expect(readScreenTitle(column('<nav><span aria-current="page">Run 42</span></nav>'))).toBe(
      "Run 42",
    );
    expect(readScreenTitle(column("<p>no heading</p>"))).toBeNull();
  });
});

describe("readScreenText", () => {
  it("squeezes blank runs and cuts a long screen with a note", () => {
    const main = column("<p>a   b</p>");
    main.textContent = "  a   b  \n\n\n\n c ";
    expect(readScreenText(main)).toBe("a b\n\nc");
    expect(readScreenText(column("<p>abcdef</p>"), 3)).toBe(
      "abc\n[… the rest of the screen is cut]",
    );
  });

  it("is empty without a main column", () => {
    expect(readScreenText(null)).toBe("");
  });
});

function Probe() {
  const { target, setFallback } = useDiscuss();
  return (
    <>
      <span data-testid="target">{target?.key ?? "none"}</span>
      <button
        onClick={() => {
          setFallback(
            screenDiscussTarget({ project: "p", pathname: "/sessions", search: "", title: null }),
          );
        }}
      >
        fallback
      </button>
    </>
  );
}

function Registers({ target }: { target: DiscussTarget }) {
  useDiscussTarget(target);
  return null;
}

describe("the screen as fallback target", () => {
  it("talks about the screen until the screen registers its own target", () => {
    const skill: DiscussTarget = { key: "skill:p:x", project: "p", kind: "Skill", title: "x" };
    const { rerender } = render(
      <DiscussProvider>
        <Probe />
      </DiscussProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "fallback" }));
    expect(screen.getByTestId("target")).toHaveTextContent("screen:p:/sessions");

    rerender(
      <DiscussProvider>
        <Probe />
        <Registers target={skill} />
      </DiscussProvider>,
    );
    expect(screen.getByTestId("target")).toHaveTextContent("skill:p:x");
  });
});
