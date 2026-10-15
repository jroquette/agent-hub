import { fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import {
  CodeBlock,
  DiffViewer,
  FileTree,
  JsonViewer,
  Minimap,
  SubagentLane,
  TimelineEvent,
  ToolGroup,
} from "./trace";

describe("CodeBlock", () => {
  it("copies its command", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<CodeBlock code="hub web" label="Start" wrap />);

    fireEvent.click(screen.getByRole("button", { name: "Copy command" }));

    expect(writeText).toHaveBeenCalledWith("hub web");
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("can hide the prompt and the copy button", () => {
    const { container } = render(<CodeBlock code="x" prompt="" noCopy />);

    expect(container.querySelector(".ah-code-prompt")).toBeNull();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("lets the keyboard scroll a command that does not wrap", () => {
    const { container } = render(<CodeBlock code="cd /a/long/path && claude --resume s" />);

    expect(container.querySelector("pre")).toHaveAttribute("tabindex", "0");
  });

  it("leaves a wrapped command out of the tab order", () => {
    const { container } = render(<CodeBlock code="hub web" wrap />);

    expect(container.querySelector("pre")).not.toHaveAttribute("tabindex");
  });
});

describe("JsonViewer", () => {
  it("prints keys, strings, numbers, nulls, arrays and nested objects", () => {
    const { container } = render(
      <JsonViewer
        value={{ a: "x", n: 1, b: true, z: null, list: [1, { k: "v" }], u: undefined }}
      />,
    );

    const text = container.textContent;
    expect(text).toContain('"a": "x"');
    expect(text).toContain('"n": 1');
    expect(text).toContain('"z": null');
    expect(text).toContain('"k": "v"');
    expect(text).toContain('"u": undefined');
  });
});

describe("DiffViewer", () => {
  it("marks added, removed and hunk lines", () => {
    const { container } = render(
      <DiffViewer
        file="src/a.ts"
        plus={1}
        minus={1}
        lines={[
          { t: "@", s: "@@ -1 +1 @@" },
          { t: "-", a: 1, s: "old" },
          { t: "+", b: 1, s: "new" },
          { t: " ", a: 2, b: 2, s: "same" },
        ]}
      />,
    );

    expect(container.querySelector(".ah-diff-hunk")).toHaveTextContent("@@ -1 +1 @@");
    expect(container.querySelector(".ah-diff-del")).toHaveTextContent("−old");
    expect(container.querySelector(".ah-diff-add")).toHaveTextContent("+new");
  });
});

describe("FileTree", () => {
  it("lists touched files by repo and selects a file", () => {
    const onSelect = vi.fn();
    render(
      <FileTree
        label="Files"
        selected="a/x.py"
        onSelect={onSelect}
        nodes={[
          {
            name: "agent-hub",
            repo: true,
            children: [
              { name: "x.py", path: "a/x.py", status: "edited", plus: 3, minus: 1 },
              { name: "y.py", path: "a/y.py", status: "created" },
              { name: "z.py", status: "read" },
            ],
          },
        ]}
      />,
    );

    expect(screen.getByRole("tree", { name: "Files" })).toBeInTheDocument();
    expect(screen.getAllByRole("treeitem")[1]).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("button", { name: /y\.py/ }));
    expect(onSelect).toHaveBeenCalledWith("a/y.py");
  });
});

describe("TimelineEvent", () => {
  const ev = {
    id: "e1",
    time: "14:02:11",
    cat: "tool" as const,
    tool: "Bash",
    text: "make check-fast",
    mono: true,
    exit: 2,
    duration: 192,
    plus: 4,
    minus: 1,
    derived: true,
    detail: <span>first error line</span>,
    raw: { tool: "Bash" },
  };

  it("shows tool, exit code, duration and the derived label", () => {
    render(<TimelineEvent ev={ev} current />);

    expect(screen.getByText("exit 2")).toHaveClass("ah-exit-bad");
    expect(screen.getByText("3 min 12 s")).toBeInTheDocument();
    expect(screen.getByText("Extracted from transcript")).toBeInTheDocument();
    expect(document.getElementById("ev-e1")).toHaveAttribute("aria-current", "true");
  });

  it("names its actor in place of the kind and tool when an actor is given", () => {
    render(
      <TimelineEvent
        ev={{ ...ev, kind: "Tool call", actor: { kind: "subagent", label: "Subagent · Explore" } }}
      />,
    );

    const row = document.getElementById("ev-e1");
    expect(row?.textContent).toContain("Subagent · Explore · make check-fast");
    expect(screen.getByText("Subagent · Explore")).toHaveAttribute("data-actor", "subagent");
    expect(screen.queryByText("Tool call")).not.toBeInTheDocument();
  });

  it("expands its detail and its raw JSON", () => {
    const onToggle = vi.fn();
    render(<TimelineEvent ev={ev} onToggle={onToggle} />);

    fireEvent.click(screen.getByRole("button", { name: /make check-fast/ }));
    expect(screen.getByText("first error line")).toBeInTheDocument();
    expect(onToggle).toHaveBeenCalledWith(true);
    fireEvent.click(screen.getByRole("button", { name: "Show raw event (redacted JSON)" }));
    expect(screen.getByText('"Bash"')).toBeInTheDocument();
  });

  it("copies its permalink and id", () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(
      <TimelineEvent ev={{ ...ev, raw: undefined }} permalink="http://x/sessions/s?event=e1" />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Copy permalink to this event" }));
    fireEvent.click(screen.getByRole("button", { name: "Copy event id e1" }));

    expect(writeText).toHaveBeenNthCalledWith(1, "http://x/sessions/s?event=e1");
    expect(writeText).toHaveBeenNthCalledWith(2, "e1");
    vi.unstubAllGlobals();
  });

  it("shows expired content when expanded", () => {
    render(
      <TimelineEvent
        ev={{ id: "e2", time: "t", cat: "message", text: "Agent said", expired: "2026-11-10" }}
        expanded
      />,
    );

    expect(screen.getByRole("note")).toHaveTextContent("Content expired 2026-11-10.");
  });
});

describe("ToolGroup and SubagentLane", () => {
  it("expands a group of reads", () => {
    render(
      <ToolGroup
        time="14:00"
        count={2}
        summary="2 files read"
        items={[
          { time: "14:00", path: "a/b.py" },
          { time: "14:01", path: "a/c.py", tool: "Grep", note: "3 matches" },
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /2 files read/ }));
    expect(screen.getByText("3 matches")).toBeInTheDocument();
  });

  it("collapses a subagent lane and links its session", () => {
    const router = createMemoryRouter([
      {
        path: "*",
        element: (
          <SubagentLane
            agent="quality-reviewer"
            sessionId="9c4e12aa-0000"
            duration={60}
            cost="$0.20"
            summary="Reviewed"
          >
            <p>inner</p>
          </SubagentLane>
        ),
      },
    ]);
    render(<RouterProvider router={router} />);

    expect(screen.getByRole("link", { name: "Open session 9c4e12aa" })).toHaveAttribute(
      "href",
      "/sessions/9c4e12aa-0000",
    );
    fireEvent.click(screen.getByRole("button", { name: /quality-reviewer/ }));
    expect(screen.queryByText("inner")).not.toBeInTheDocument();
  });
});

describe("Minimap", () => {
  it("jumps with clicks and keys", () => {
    const onJump = vi.fn();
    render(
      <Minimap
        bins={[
          { cat: "tool", n: 3 },
          { cat: "error", n: 1 },
        ]}
        marks={[{ at: 0.5, kind: "error", label: "exit 2" }]}
        view={{ top: 0.5, height: 0.2 }}
        onJump={onJump}
      />,
    );
    const slider = screen.getByRole("slider");

    fireEvent.keyDown(slider, { key: "ArrowDown" });
    fireEvent.keyDown(slider, { key: "x" });
    fireEvent.click(slider, { clientY: 0 });

    expect(onJump).toHaveBeenNthCalledWith(1, 0.6);
    expect(onJump).toHaveBeenCalledTimes(2);
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = render(
      <div>
        <TimelineEvent ev={{ id: "e", time: "t", cat: "guard", text: "Denied", detail: "x" }} />
        <JsonViewer value={{ a: 1 }} />
        <FileTree
          nodes={[{ name: "x.py", path: "x.py", status: "read" }]}
          label="Files"
          onSelect={vi.fn()}
        />
        <Minimap />
      </div>,
    );

    expect(await seriousViolations(container)).toEqual([]);
  });
});
