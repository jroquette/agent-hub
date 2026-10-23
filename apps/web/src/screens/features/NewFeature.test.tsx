import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aCapabilities,
  aFeature,
  aPage,
  aProblem,
  aProjectSummary,
  aWorkdir,
  anAgentSession,
  anId,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { DiscussProvider, useDiscuss } from "../../shell/discuss";
import { NewFeatureScreen, composeFeatureMessage } from "./NewFeature";

const ID = anId(4, "0192a5e5");

function Probe() {
  const { target, open } = useDiscuss();
  return (
    <output aria-label="discuss">
      {open ? "open" : "closed"}|{target?.kind ?? ""}
    </output>
  );
}

const IDEA = "Owners export the orders of a period as CSV.";

function renderNew(routes: ApiRoutes = {}) {
  return renderWithApi(
    <DiscussProvider>
      <NewFeatureScreen />
      <Probe />
    </DiscussProvider>,
    {
      routes: {
        "/api/v1/projects": aPage([aProjectSummary()]),
        "/api/v1/features": aPage([aFeature()]),
        "/api/v1/agent-sessions/capabilities": aCapabilities(),
        "/api/v1/agent-sessions/workdirs": { items: [aWorkdir()], warnings: [] },
        "POST /api/v1/agent-sessions": anAgentSession({ id: ID, status: "running" }),
        ...routes,
      },
      path: "/features/new",
    },
  );
}

async function ready() {
  const start = await screen.findByRole("button", { name: "Start with Claude" });
  return start;
}

describe("composeFeatureMessage", () => {
  it("names only the fields the owner filled (AC-420.6)", () => {
    expect(composeFeatureMessage({ idea: IDEA, issue: "", size: "", slug: "" })).toBe(
      `Start a new feature in this hub.\n\nThe idea:\n${IDEA}`,
    );
    expect(
      composeFeatureMessage({ idea: ` ${IDEA} `, issue: "AGH-12", size: "spike", slug: "orders" }),
    ).toBe(
      [
        "Start a new feature in this hub.",
        "Tracker issue: AGH-12 (read its brief first).",
        "Slug: orders",
        "Size: spike",
        "",
        "The idea:",
        IDEA,
      ].join("\n"),
    );
  });
});

describe("NewFeatureScreen", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("says why it waits for an idea or an issue before Claude can be asked (AC-420.4)", async () => {
    const user = userEvent.setup();
    renderNew();

    const start = await ready();
    expect(start).toHaveAttribute("aria-disabled", "true");
    expect(
      await screen.findByText("Write at least a sentence, or give an issue."),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText("Start from an issue"), "agh-12");
    await waitFor(() => {
      expect(start).not.toHaveAttribute("aria-disabled");
    });
  });

  it("sends focus to the field at fault when Start is pressed before it is ready (AC-420.4)", async () => {
    const user = userEvent.setup();
    renderNew();

    const idea = await screen.findByLabelText("What do you want to build?");
    await user.click(await ready());
    expect(idea).toHaveFocus();

    await user.type(idea, IDEA);
    await user.type(screen.getByLabelText("Start from an issue"), "nope");
    await user.click(screen.getByRole("button", { name: "Start with Claude" }));
    expect(screen.getByLabelText("Start from an issue")).toHaveFocus();
    expect(screen.getByText("Fix the issue id in Options.")).toBeInTheDocument();
  });

  it("shows a failed start even after a refused file (AC-420.8)", async () => {
    const user = userEvent.setup();
    renderNew({
      "POST /api/v1/agent-sessions": aProblem({
        status: 409,
        title: "Busy",
        detail: "The hub is busy.",
      }),
    });

    const idea = await screen.findByLabelText("What do you want to build?");
    fireEvent.paste(idea, {
      clipboardData: { files: [new File([new Uint8Array([0, 1, 2])], "app.bin")] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("“app.bin” is neither");
    await user.type(idea, IDEA);
    await waitFor(async () => {
      expect(await ready()).not.toHaveAttribute("aria-disabled");
    });
    await user.click(screen.getByRole("button", { name: "Start with Claude" }));

    expect(await screen.findByText("The hub is busy.")).toBeInTheDocument();
    expect(screen.queryByText(/app\.bin/)).not.toBeInTheDocument();
  });

  it("refuses a slug that already names a feature (AC-420.5)", async () => {
    const user = userEvent.setup();
    renderNew();

    await user.type(await screen.findByLabelText("What do you want to build?"), IDEA);
    await user.type(screen.getByLabelText("Slug"), "control-plane");

    expect(await screen.findByText("A feature with this slug already exists.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start with Claude" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("starts the conversation with the brief and its attachments, then opens the panel on it (AC-420.3, AC-420.6)", async () => {
    const user = userEvent.setup();
    const view = renderNew();

    const idea = await screen.findByLabelText("What do you want to build?");
    fireEvent.paste(idea, {
      clipboardData: { files: [new File(["id,total\n1,9\n"], "orders.csv", { type: "text/csv" })] },
    });
    const strip = await screen.findByRole("list", { name: "Attached to this request" });
    expect(await within(strip).findByText("orders.csv")).toBeInTheDocument();
    await user.type(idea, IDEA);
    await user.type(screen.getByLabelText("Start from an issue"), "AGH-12");
    await user.type(screen.getByLabelText("Slug"), "orders-csv");
    await user.selectOptions(screen.getByLabelText("Size"), "Bounded");
    await waitFor(async () => {
      expect(await ready()).not.toHaveAttribute("aria-disabled");
    });
    await user.click(screen.getByRole("button", { name: "Start with Claude" }));

    const created = await waitFor(() => {
      const found = view.requests.find(
        (r) => r.method === "POST" && new URL(r.url).pathname === "/api/v1/agent-sessions",
      );
      expect(found).toBeDefined();
      return found;
    });
    const body = JSON.parse((await created?.clone().text()) ?? "{}") as {
      prompt: string;
      mode: string;
      files?: { name: string; media_type: string }[];
    };
    expect(body.mode).toBe("default");
    expect(body.prompt).toContain("Tracker issue: AGH-12");
    expect(body.prompt).toContain("Slug: orders-csv");
    expect(body.prompt).toContain("Size: bounded");
    expect(body.prompt).toContain(IDEA);
    expect(body.files?.map((file) => [file.name, file.media_type])).toEqual([
      ["orders.csv", "text/plain"],
    ]);

    const sent = await screen.findByRole("region", { name: "Sent to Claude" });
    expect(within(sent).getByText(IDEA)).toBeInTheDocument();
    expect(within(sent).getByText("orders.csv")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "discuss" })).toHaveTextContent("open|New feature");
    const kept = Object.keys(window.localStorage).find((key) =>
      key.startsWith("ah.discuss.session.feature-new:agent-hub:"),
    );
    expect(window.localStorage.getItem(kept ?? "")).toBe(ID);
  });

  it("starts on Ctrl+Enter from the brief (AC-420.6)", async () => {
    const user = userEvent.setup();
    const view = renderNew();

    const idea = await screen.findByLabelText("What do you want to build?");
    await user.type(idea, IDEA);
    await waitFor(async () => {
      expect(await ready()).not.toHaveAttribute("aria-disabled");
    });
    await user.keyboard("{Control>}{Enter}{/Control}");

    await waitFor(() => {
      expect(
        view.requests.some(
          (r) => r.method === "POST" && new URL(r.url).pathname === "/api/v1/agent-sessions",
        ),
      ).toBe(true);
    });
  });

  it("links to the new feature once its record appears (AC-420.7)", async () => {
    const user = userEvent.setup();
    let written = false;
    renderNew({
      "/api/v1/features": () =>
        aPage(written ? [aFeature(), aFeature({ slug: "orders-csv" })] : [aFeature()]),
    });

    await user.type(await screen.findByLabelText("What do you want to build?"), IDEA);
    await waitFor(async () => {
      expect(await ready()).not.toHaveAttribute("aria-disabled");
    });
    await user.click(screen.getByRole("button", { name: "Start with Claude" }));
    expect(
      await screen.findByText("Claude is working on the brief with you in the panel."),
    ).toBeInTheDocument();
    written = true;

    expect(
      await screen.findByRole("link", { name: "Open orders-csv" }, { timeout: 5_000 }),
    ).toHaveAttribute("href", "/features/agent-hub/orders-csv");
  }, 10_000);

  it("shows the project as a pill on the title row and keeps each project's brief (AC-420.2)", async () => {
    const user = userEvent.setup();
    renderNew({
      "/api/v1/projects": aPage([aProjectSummary(), aProjectSummary({ name: "demo-shop" })]),
    });

    expect(
      await screen.findByRole("heading", { level: 1, name: "New feature" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Features" })).toHaveAttribute("href", "/features");
    const project = await screen.findByRole("combobox", { name: "Project" });
    expect(project).toHaveValue("agent-hub");
    expect(project.closest(".as-pill")).toHaveTextContent("agent-hub");
    await user.type(screen.getByLabelText("What do you want to build?"), IDEA);
    await user.type(screen.getByLabelText("Slug"), "orders");

    await user.selectOptions(project, "demo-shop");
    expect(screen.getByLabelText("What do you want to build?")).toHaveValue("");
    expect(screen.getByLabelText("Slug")).toHaveValue("");
    expect(project.closest(".as-pill")).toHaveTextContent("demo-shop");

    await user.selectOptions(project, "agent-hub");
    expect(screen.getByLabelText("What do you want to build?")).toHaveValue(IDEA);
  });

  it("offers Welcome when there is no project (AC-420.2)", async () => {
    renderNew({ "/api/v1/projects": aPage([]) });

    expect(await screen.findByText("No project yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Welcome" })).toHaveAttribute("href", "/welcome");
  });

  it("asks what the attachment is for and puts the caret in the text on a press of the box (AC-420.3)", async () => {
    renderNew();

    const idea = await screen.findByLabelText("What do you want to build?");
    expect(idea).toHaveAttribute(
      "placeholder",
      "Describe the feature: who it is for, what they should be able to do, and why.",
    );
    fireEvent.paste(idea, {
      clipboardData: { files: [new File(["# Notes"], "notes.md", { type: "text/markdown" })] },
    });
    expect(await screen.findByText("notes.md")).toBeInTheDocument();
    expect(idea).toHaveAttribute(
      "placeholder",
      "Say what to build, and what Claude should take from the file.",
    );
    expect(
      screen.getByText("Add a sentence on what to build with the attachments."),
    ).toBeInTheDocument();

    const box = idea.closest(".ft-new-brief");
    if (!box) throw new Error("no brief box");
    fireEvent.mouseDown(box);
    expect(idea).toHaveFocus();
  });

  it("says why sessions cannot start by the reason's own title (AC-420.4)", async () => {
    renderNew({
      "/api/v1/agent-sessions/capabilities": aCapabilities({
        available: false,
        reason: "claude is not on PATH.",
      }),
    });

    expect(
      await screen.findByText("Sessions cannot start here.", { selector: "p" }),
    ).toHaveAttribute("aria-live", "polite");
    expect(await ready()).toHaveAttribute("aria-disabled", "true");
  });

  it("shows the options as one field shape with their defaults, the ids in mono (AC-420.5)", async () => {
    const user = userEvent.setup();
    renderNew();

    const issue = await screen.findByLabelText("Start from an issue");
    const slug = screen.getByLabelText("Slug");
    const size = screen.getByLabelText("Size");
    expect(issue).toHaveAttribute("placeholder", "None");
    expect(slug).toHaveAttribute("placeholder", "Claude picks one");
    expect(size).toHaveValue("");
    expect(screen.getByText("Claude proposes a size and asks you.")).toBeInTheDocument();
    for (const field of [issue, slug, size]) expect(field).toHaveClass("ah-input");
    expect(issue).toHaveClass("ah-mono");
    expect(slug).toHaveClass("ah-mono");
    // Issue, Slug, Size in that order.
    const order = [issue, slug, size].map((field) =>
      Array.from(document.querySelectorAll("input, select")).indexOf(field),
    );
    expect(order).toEqual([...order].sort((a, b) => a - b));

    await user.selectOptions(size, "Spike");
    await user.type(screen.getByLabelText("What do you want to build?"), IDEA);
    expect(screen.getByText("Throwaway learning, nothing merged.")).toBeInTheDocument();
    await user.type(slug, "Orders CSV");
    expect(
      screen.getByText("Lowercase letters, digits and dashes, starting with a letter."),
    ).toBeInTheDocument();
    expect(screen.getByText("Fix the slug in Options.")).toBeInTheDocument();
  });

  it("never starts on Enter in a one-line field (AC-420.6)", async () => {
    const user = userEvent.setup();
    const view = renderNew();

    await user.type(await screen.findByLabelText("What do you want to build?"), IDEA);
    await waitFor(async () => {
      expect(await ready()).not.toHaveAttribute("aria-disabled");
    });
    await user.type(screen.getByLabelText("Start from an issue"), "AGH-12{Enter}");

    expect(
      view.requests.some(
        (r) => r.method === "POST" && new URL(r.url).pathname === "/api/v1/agent-sessions",
      ),
    ).toBe(false);
  });

  it("starts another feature on an empty form, the panel closed and the brief focused (AC-420.7)", async () => {
    const user = userEvent.setup();
    renderNew();

    await user.type(await screen.findByLabelText("What do you want to build?"), IDEA);
    await waitFor(async () => {
      expect(await ready()).not.toHaveAttribute("aria-disabled");
    });
    await user.click(screen.getByRole("button", { name: "Start with Claude" }));
    const sent = await screen.findByRole("region", { name: "Sent to Claude" });
    expect(
      within(sent).getByText(/Issue: none · Slug: Claude picks · Size: Let Claude ask/),
    ).toBeInTheDocument();
    expect(within(sent).getByRole("link", { name: "Open the full chat" })).toHaveAttribute(
      "href",
      `/agent-sessions/${ID}`,
    );

    await user.click(screen.getByRole("button", { name: "Start another feature" }));
    const idea = await screen.findByLabelText("What do you want to build?");
    expect(idea).toHaveValue("");
    await waitFor(() => {
      expect(idea).toHaveFocus();
    });
    expect(screen.getByRole("status", { name: "discuss" })).toHaveTextContent("closed|");
  });

  it("clears a refusal when its attachment is removed (AC-420.8)", async () => {
    const user = userEvent.setup();
    renderNew();

    const idea = await screen.findByLabelText("What do you want to build?");
    fireEvent.paste(idea, {
      clipboardData: {
        files: [
          new File(["# Notes"], "notes.md", { type: "text/markdown" }),
          new File([new Uint8Array([0, 1, 2])], "app.bin"),
        ],
      },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("“app.bin” is neither");
    await user.click(await screen.findByRole("button", { name: /Remove notes\.md/ }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = renderNew();

    await ready();
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("has no serious a11y violations with an attachment and a refused file (a11y)", async () => {
    const { container } = renderNew();

    const idea = await screen.findByLabelText("What do you want to build?");
    fireEvent.paste(idea, {
      clipboardData: {
        files: [
          new File(["# Notes"], "notes.md", { type: "text/markdown" }),
          new File([new Uint8Array([0, 1, 2])], "app.bin"),
        ],
      },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("“app.bin” is neither");
    expect(await screen.findByText("notes.md")).toBeInTheDocument();
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("has no serious a11y violations on the sent card (a11y)", async () => {
    const user = userEvent.setup();
    const { container } = renderNew();

    await user.type(await screen.findByLabelText("What do you want to build?"), IDEA);
    await waitFor(async () => {
      expect(await ready()).not.toHaveAttribute("aria-disabled");
    });
    await user.click(screen.getByRole("button", { name: "Start with Claude" }));
    await screen.findByRole("region", { name: "Sent to Claude" });
    expect(await seriousViolations(container)).toEqual([]);
  });
});
