import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  T0,
  aHookDetail,
  aSkillDetail,
  anAgentDetail,
  renderWithApi,
} from "../../testing/builders";
import { DetailHeader, argumentLine, hookSentence } from "./DetailHeader";

const NOW = Date.parse(T0);

function header(detail = aSkillDetail()) {
  return renderWithApi(<DetailHeader detail={detail} now={NOW} usageDays={30} />);
}

describe("DetailHeader detail_header_raw", () => {
  it("says what a skill is, how to call it and its state (AC-164.17)", () => {
    header(aSkillDetail({ when_to_use: "When an idea needs a spec." }));

    expect(screen.getByRole("heading", { level: 1, name: "feature" })).toBeInTheDocument();
    expect(
      screen.getByText("Takes an idea or a tracker issue from spec to delivery."),
    ).toBeInTheDocument();
    expect(screen.getByText("When an idea needs a spec.", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("/feature <idea or tracker issue id>").tagName).toBe("CODE");
    expect(
      screen.getByRole("button", { name: "Copy /feature <idea or tracker issue id>" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Pass the idea or tracker issue id.")).toBeInTheDocument();
    expect(screen.getByText("User and model")).toBeInTheDocument();
    expect(screen.getByText("Managed")).toBeInTheDocument();
    expect(screen.getByText(/3 uses in 30 days/)).toBeInTheDocument();
    expect(screen.queryByText("Source", { selector: "dt" })).toBeNull();
  });

  it("links the diagnostics count to the Diagnostics card, or says there are none", () => {
    const { unmount } = header();

    expect(screen.getByRole("link", { name: "1 diagnostic" })).toHaveAttribute(
      "href",
      "#skill-diagnostics",
    );
    unmount();
    header(aSkillDetail({ diagnostics: [] }));

    expect(screen.getByText("No diagnostics")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /diagnostic/ })).toBeNull();
  });

  it("copies exactly the invocation when Copy is pressed", () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    header();

    fireEvent.click(screen.getByRole("button", { name: /^Copy/ }));

    expect(writeText).toHaveBeenCalledWith("/feature <idea or tracker issue id>");
    vi.unstubAllGlobals();
  });

  it("says how an agent is called and has no Copy", () => {
    header(anAgentDetail());

    expect(screen.getByRole("heading", { level: 1, name: "evaluator" })).toBeInTheDocument();
    expect(screen.getByText(/delegates to it as subagent/)).toHaveTextContent(
      "The main session delegates to it as subagent evaluator.",
    );
    expect(screen.queryByRole("button", { name: /^Copy/ })).toBeNull();
  });

  it("says when a hook runs in a sentence, with its state", () => {
    header(aHookDetail({ active: false }));

    const banner = screen.getByRole("banner");
    expect(within(banner).getByRole("heading", { level: 1 })).toHaveTextContent(
      "settings-pretooluse-1",
    );
    expect(banner).toHaveTextContent("Runs before every Bash tool call.");
    expect(banner).toHaveTextContent("Inactive");
    expect(banner).not.toHaveTextContent("uses in");
  });
});

describe("hookSentence", () => {
  it.each([
    [{ event: "PreToolUse", matcher: "Bash" }, "Runs before every Bash tool call."],
    [{ event: "PostToolUse", matcher: "Edit|Write" }, "Runs after every Edit or Write tool call."],
    [{ event: "PostToolUseFailure", matcher: null }, "Runs after every failed tool call."],
    [{ event: "SessionStart", matcher: null }, "Runs when a session starts."],
    [{ event: "Custom", matcher: null }, "Runs on Custom."],
  ])("words %o as a sentence", (hook, sentence) => {
    expect(hookSentence(hook)).toBe(sentence);
  });
});

describe("argumentLine", () => {
  it("reads one placeholder as what to pass, anything else as it is", () => {
    expect(argumentLine("<tracker issue id>")).toBe("Pass the tracker issue id.");
    expect(argumentLine("[screen | path]")).toBe("Arguments: [screen | path]");
  });
});

describe("DetailHeader a11y", () => {
  it("has no serious or critical axe violation", async () => {
    const { container } = header();

    expect(await seriousViolations(container)).toEqual([]);
  });
});
