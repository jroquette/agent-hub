import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aCapabilities,
  aFeature,
  aPage,
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
  it("names only the fields the owner filled", () => {
    expect(composeFeatureMessage({ idea: IDEA, issue: "", size: "", slug: "" })).toBe(
      `Start a new feature in this hub.\n\nThe idea:\n${IDEA}`,
    );
  });
});

describe("NewFeatureScreen", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("says why it waits for an idea or an issue before Claude can be asked", async () => {
    const user = userEvent.setup();
    renderNew();

    const start = await ready();
    expect(start).toBeDisabled();
    expect(
      await screen.findByText("Write at least a sentence, or give an issue."),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText("Start from an issue"), "agh-12");
    await waitFor(() => {
      expect(start).toBeEnabled();
    });
  });

  it("refuses a slug that already names a feature", async () => {
    const user = userEvent.setup();
    renderNew();

    await user.type(await screen.findByLabelText("What do you want to build?"), IDEA);
    await user.type(screen.getByLabelText("Slug"), "control-plane");

    expect(await screen.findByText("A feature with this slug already exists.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start with Claude" })).toBeDisabled();
  });

  it("starts the conversation with the brief and its attachments, then opens the panel on it", async () => {
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
    await user.click(screen.getByRole("radio", { name: "Bounded" }));
    await waitFor(async () => {
      expect(await ready()).toBeEnabled();
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

  it("starts on Ctrl+Enter from the brief", async () => {
    const user = userEvent.setup();
    const view = renderNew();

    const idea = await screen.findByLabelText("What do you want to build?");
    await user.type(idea, IDEA);
    await waitFor(async () => {
      expect(await ready()).toBeEnabled();
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

  it("links to the new feature once its record appears", async () => {
    const user = userEvent.setup();
    let written = false;
    renderNew({
      "/api/v1/features": () =>
        aPage(written ? [aFeature(), aFeature({ slug: "orders-csv" })] : [aFeature()]),
    });

    await user.type(await screen.findByLabelText("What do you want to build?"), IDEA);
    await waitFor(async () => {
      expect(await ready()).toBeEnabled();
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
      expect(await ready()).toBeEnabled();
    });
    await user.click(screen.getByRole("button", { name: "Start with Claude" }));
    await screen.findByRole("region", { name: "Sent to Claude" });
    expect(await seriousViolations(container)).toEqual([]);
  });
});
