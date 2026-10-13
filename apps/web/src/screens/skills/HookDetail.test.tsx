import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aHookDetail } from "../../testing/builders";
import { HookDetail } from "./HookDetail";

const HOOK = aHookDetail().hook ?? {
  active: true,
  command: null,
  event: "Stop",
  matcher: null,
  state: "synced" as const,
  timeout: null,
  type: "command",
};

const fact = (term: string) =>
  screen.getByText(term, { selector: "dt" }).nextElementSibling as HTMLElement;

describe("HookDetail hook", () => {
  it("shows event, matcher, command as inert code, source and state (AC-164.22)", () => {
    const { container } = render(<HookDetail hook={HOOK} sourcePath=".claude/settings.json" />);

    expect(fact("Event")).toHaveTextContent("PreToolUse");
    expect(fact("Matcher")).toHaveTextContent("Bash");
    expect(fact("Type")).toHaveTextContent("command");
    expect(fact("Source file")).toHaveTextContent(".claude/settings.json");
    expect(fact("State")).toHaveTextContent("Active");
    expect(fact("State")).toHaveTextContent("Synced");
    const code = container.querySelector("pre code");
    expect(code?.textContent).toBe("python3 plugin/hub-workflow/hooks/guard.py");
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/never runs it/)).toBeInTheDocument();
  });

  it("says inactive and not synced, every tool and the timeout when the hook says so", () => {
    render(
      <HookDetail
        hook={{ ...HOOK, active: false, state: "not synced", matcher: null, timeout: 30 }}
        sourcePath=".claude/settings.project.json"
      />,
    );

    expect(fact("Matcher")).toHaveTextContent("Every tool (no matcher)");
    expect(fact("Timeout")).toHaveTextContent("30 s");
    expect(fact("State")).toHaveTextContent("Inactive");
    expect(fact("State")).toHaveTextContent("Not synced");
  });

  it("says when a hook has no command", () => {
    render(<HookDetail hook={{ ...HOOK, command: null, type: "prompt" }} sourcePath="x" />);

    expect(screen.getByText("No command: this hook is not a command hook.")).toBeInTheDocument();
  });
});

describe("HookDetail a11y", () => {
  it("has no serious or critical axe violation", async () => {
    const { container } = render(<HookDetail hook={HOOK} sourcePath=".claude/settings.json" />);

    expect(await seriousViolations(container)).toEqual([]);
  });
});
