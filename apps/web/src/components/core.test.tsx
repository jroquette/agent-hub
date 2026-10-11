import { act, fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PreferencesProvider } from "../lib/preferences";
import { seriousViolations } from "../testing/axe";
import {
  AppLink,
  Button,
  IconButton,
  IdChip,
  IssueLink,
  Kbd,
  OutsideLink,
  MenuItem,
  Money,
  PathText,
  PhaseTag,
  Popover,
  SegmentedControl,
  Tabs,
  Time,
  Tooltip,
  copyText,
  phaseTooltip,
} from "./core";

afterEach(() => {
  vi.useRealTimers();
  window.localStorage.clear();
});

function inRouter(ui: React.ReactElement) {
  const router = createMemoryRouter([{ path: "*", element: ui }]);
  return render(<RouterProvider router={router} />);
}

describe("Button", () => {
  it("renders the design's variant and size classes", () => {
    render(
      <Button variant="primary" size="sm" icon="check" iconRight="chevron-down">
        Save
      </Button>,
    );

    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toHaveClass("ah-btn", "ah-btn-primary", "ah-btn-sm");
    expect(button.querySelectorAll("svg")).toHaveLength(2);
  });

  it("is disabled with its phase tag and the read-only tooltip when its phase is later", () => {
    render(<Button phase="P4">Retry from verify</Button>);

    const button = screen.getByRole("button", { name: /Retry from verify/ });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Available in Phase 4. This version is read-only.");
    expect(screen.getByText("P4")).toHaveClass("ah-phase");
    expect(phaseTooltip("P3")).toBe("Available in Phase 3. This version is read-only.");
  });
});

describe("IconButton and Tooltip", () => {
  it("names the button by its label and shows it as a tooltip", () => {
    render(<IconButton icon="link" label="Copy link" />);

    expect(screen.getByRole("button", { name: "Copy link" })).toHaveClass(
      "ah-iconbtn",
      "ah-btn-ghost",
    );
    expect(screen.getByRole("tooltip")).toHaveTextContent("Copy link");
  });

  it("renders only its children when the label is empty", () => {
    const { container } = render(<Tooltip label="">x</Tooltip>);

    expect(container.innerHTML).toBe("x");
  });

  it("can be forced open", () => {
    render(
      <Tooltip label="tip" open block>
        x
      </Tooltip>,
    );

    expect(screen.getByRole("tooltip")).toHaveClass("ah-tip-open");
  });
});

describe("Popover and MenuItem", () => {
  it("renders nothing when closed and its items when open", () => {
    const onClick = vi.fn();
    const { rerender } = render(
      <Popover open={false} label="menu">
        <MenuItem>Hidden</MenuItem>
      </Popover>,
    );
    expect(screen.queryByText("Hidden")).not.toBeInTheDocument();

    rerender(
      <Popover open label="menu">
        <MenuItem icon="plus" selected danger onClick={onClick} hint={<Kbd>1</Kbd>}>
          Add
        </MenuItem>
      </Popover>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Add/ }));

    expect(screen.getByRole("dialog", { name: "menu" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add/ })).toHaveAttribute("aria-current", "true");
    expect(onClick).toHaveBeenCalled();
  });
});

describe("IdChip", () => {
  it("shows 8 characters and copies the full id when clicked", () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const id = "01923f1e-5091-7b98-8a6e-3f20c1d4a7b2";
    render(<IdChip id={id} kind="session" />);

    const chip = screen.getByRole("button", { name: `Copy session ${id}` });
    expect(chip).toHaveTextContent("session01923f1e");
    fireEvent.click(chip);

    expect(writeText).toHaveBeenCalledWith(id);
    expect(chip).toHaveClass("ah-id-copied");
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    expect(chip).not.toHaveClass("ah-id-copied");
    vi.unstubAllGlobals();
  });

  it("survives a browser without a clipboard", () => {
    vi.stubGlobal("navigator", {});
    expect(() => {
      copyText("x");
    }).not.toThrow();
    vi.unstubAllGlobals();
  });
});

describe("IssueLink", () => {
  it("links out when the issue has a URL", () => {
    render(<IssueLink id="AGH-48" title="Layered memory" href="https://linear.app/x" showTitle />);

    expect(screen.getByRole("link", { name: /AGH-48/ })).toHaveAttribute("target", "_blank");
    expect(screen.getByText("Layered memory")).toBeInTheDocument();
  });

  it("explains the missing link when Linear is not connected", () => {
    render(<IssueLink id="AGH-48" />);

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("AGH-48")).toHaveAttribute(
      "title",
      "AGH-48 · Linear is not connected in this version.",
    );
  });
});

describe("IssueLink with unsafe data", () => {
  it.each(["javascript:alert(1)", "data:text/html,x"])(
    "renders the key as plain text when the URL is %s",
    (href) => {
      render(<IssueLink id="AGH-48" href={href} />);

      expect(screen.queryByRole("link")).not.toBeInTheDocument();
      expect(screen.getByText("AGH-48")).toBeInTheDocument();
    },
  );
});

describe("OutsideLink", () => {
  it("opens a safe https URL in a new tab", () => {
    render(<OutsideLink href="https://github.com/acme/app/pull/7">PR</OutsideLink>);

    const link = screen.getByRole("link", { name: "PR" });
    expect(link).toHaveAttribute("href", "https://github.com/acme/app/pull/7");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  it.each(["javascript:alert(1)", "data:text/html,<b>x</b>", "//evil.example", null])(
    "renders the label as plain text when the URL is %j",
    (href) => {
      render(<OutsideLink href={href}>PR</OutsideLink>);

      expect(screen.queryByRole("link")).not.toBeInTheDocument();
      expect(screen.getByText("PR")).toBeInTheDocument();
    },
  );
});

describe("AppLink", () => {
  it.each(["javascript:alert(1)", "data:text/html,x", "//evil.example/x"])(
    "renders plain text when the href from API data is %s",
    (href) => {
      inRouter(<AppLink href={href}>Open</AppLink>);

      expect(screen.queryByRole("link")).not.toBeInTheDocument();
      expect(screen.getByText("Open")).toBeInTheDocument();
    },
  );

  it("routes in-app paths and leaves other links as anchors", () => {
    inRouter(
      <>
        <AppLink href="/sessions">Sessions</AppLink>
        <AppLink href="https://example.com">Out</AppLink>
      </>,
    );

    expect(screen.getByRole("link", { name: "Sessions" })).toHaveAttribute("href", "/sessions");
    expect(screen.getByRole("link", { name: "Out" })).toHaveAttribute(
      "href",
      "https://example.com",
    );
  });
});

describe("PathText, Money, PhaseTag", () => {
  it("middle-truncates a path and dims its folders", () => {
    const path = "packages/core/src/agent_hub/core/memory/brain_memory_rule.py";
    const { container } = render(<PathText path={path} max={40} dimDir />);

    expect(container.querySelector(".ah-path")).toHaveAttribute("title", path);
    expect(container.querySelector(".ah-path-dim")).toHaveTextContent("packages/…/memory/");
  });

  it("keeps a short path whole", () => {
    render(<PathText path="brain/now.md" />);

    expect(screen.getByText("brain/now.md")).toHaveClass("ah-path");
  });

  it("formats money with the precise value in the tooltip", () => {
    render(<Money value="2.1234" />);

    expect(screen.getByText("$2.12")).toHaveAttribute("title", "$2.1234 USD");
  });

  it("names the phase in its tooltip", () => {
    render(<PhaseTag phase="P3" />);

    expect(screen.getByText("P3")).toHaveAttribute("title", "Arrives in Phase 3");
  });
});

describe("Time", () => {
  it("shows an age with the absolute time on hover", () => {
    render(<Time iso="2026-10-11T14:02:00Z" ago={120} utc />);

    expect(screen.getByText("2 min ago")).toHaveAttribute("title", "2026-10-11 14:02 UTC");
  });

  it("follows the UTC preference when not forced", () => {
    window.localStorage.setItem("ah.tz", "utc");
    render(
      <PreferencesProvider>
        <Time iso="2026-10-11T14:02:00Z" absolute />
      </PreferencesProvider>,
    );

    expect(screen.getByText("2026-10-11 14:02 UTC")).toHaveClass("ah-num");
  });

  it("shows local time when the preference is local", () => {
    render(<Time iso="2026-10-11T14:02:00Z" />);

    expect(screen.getByRole("time")).toHaveTextContent(/11 Oct/);
  });
});

describe("Tabs and SegmentedControl", () => {
  it("selects the current tab and reports a change", () => {
    const onChange = vi.fn();
    render(
      <Tabs
        label="Session"
        value="timeline"
        onChange={onChange}
        tabs={[
          { id: "timeline", label: "Timeline", icon: "activity" },
          { id: "files", label: "Files", count: 3 },
          { id: "decisions", label: "Decisions", phase: "P3" },
        ]}
      />,
    );

    expect(screen.getByRole("tab", { name: "Timeline" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: /Files/ }));
    expect(onChange).toHaveBeenCalledWith("files");
  });

  it("presses the current option and reports a change", () => {
    const onChange = vi.fn();
    render(
      <SegmentedControl
        label="Density"
        value="a"
        onChange={onChange}
        options={["a", { id: "b", icon: "list", title: "List" }]}
      />,
    );

    expect(screen.getByRole("button", { name: "a" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "List" }));
    expect(onChange).toHaveBeenCalledWith("b");
  });
});

describe("a11y", () => {
  it("has no serious or critical a11y violation", async () => {
    const { container } = inRouter(
      <div>
        <Button icon="check">Save</Button>
        <IconButton icon="x" label="Close" />
        <IdChip id="01923f1e-5091-7b98-8a6e-3f20c1d4a7b2" />
        <IssueLink id="AGH-48" />
        <Tabs value="a" label="Tabs" tabs={[{ id: "a", label: "A" }]} />
        <SegmentedControl label="Zone" value="local" options={["local", "utc"]} />
      </div>,
    );

    expect(await seriousViolations(container)).toEqual([]);
  });
});
