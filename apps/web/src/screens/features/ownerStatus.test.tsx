import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { noteLaunchCookie } from "../../lib/launchCookie";
import {
  aFeature,
  aGoldenPath,
  aProblem,
  aShellView,
  renderWithApi,
  type ApiRoutes,
  type FeatureView,
} from "../../testing/builders";
import { OwnerStatusBanner, OwnerStatusMenu, fmtDay } from "./ownerStatus";

const STATUS = "/api/v1/features/demo/checkout/status";

const active = aFeature({
  slug: "checkout",
  project: "demo",
  repos: ["demo", "demo-api"],
  issues: ["DEM-3"],
});
const decided = (status: "shipped" | "closed" | "paused", note: string | null = null) =>
  aFeature({
    ...active,
    owner_status: { status, decided_at: "2026-11-02T10:00:00Z", note },
  });

function menu(feature: FeatureView, routes: ApiRoutes = {}) {
  return renderWithApi(<OwnerStatusMenu feature={feature} nameOf={() => null} />, { routes });
}

async function openMenu(): Promise<HTMLElement> {
  await userEvent.click(screen.getByRole("button", { name: "Status" }));
  return screen.getByRole("dialog", { name: "Feature status" });
}

const itemsOf = (popover: HTMLElement) =>
  within(popover)
    .getAllByRole("button")
    .map((b) => b.textContent);

describe("OwnerStatusMenu", () => {
  it("offers Mark shipped, Close without shipping and Pause on a feature with no decision", async () => {
    menu(active);

    expect(itemsOf(await openMenu())).toEqual(["Mark shipped", "Close without shipping", "Pause"]);
  });

  it.each([
    ["shipped", ["Reopen", "Close without shipping", "Pause"]],
    ["closed", ["Reopen", "Mark shipped", "Pause"]],
    ["paused", ["Reopen", "Mark shipped", "Close without shipping"]],
  ] as const)(
    "offers Reopen and the other decisions on a feature marked %s",
    async (status, items) => {
      menu(decided(status));

      expect(itemsOf(await openMenu())).toEqual(items);
    },
  );

  it("closes the menu with Escape and leaves it closed until asked", async () => {
    menu(active);

    await openMenu();
    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "Feature status" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Status" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("posts the chosen decision with its note for this feature, then closes the dialog", async () => {
    const { requests } = menu(active, { [`POST ${STATUS}`]: {} });

    await userEvent.click(within(await openMenu()).getByRole("button", { name: "Mark shipped" }));
    const dialog = screen.getByRole("dialog", { name: "Mark shipped checkout?" });
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "Why (optional)" }),
      "  Released to demo-shop ",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Mark shipped" }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /^Mark shipped/ })).not.toBeInTheDocument();
    });
    const posts = requests.filter((r) => r.method === "POST");
    expect(posts.map((r) => new URL(r.url).pathname)).toEqual([STATUS]);
    expect(await posts[0]?.json()).toEqual({ status: "shipped", note: "Released to demo-shop" });
  });

  it("reopens a decided feature with no note field and a null note", async () => {
    const { requests } = menu(decided("paused"), { [`POST ${STATUS}`]: {} });

    await userEvent.click(within(await openMenu()).getByRole("button", { name: "Reopen" }));
    const dialog = screen.getByRole("dialog", { name: "Reopen checkout?" });
    expect(within(dialog).queryByRole("textbox")).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Reopen" }));

    await waitFor(() => {
      expect(requests.some((r) => r.method === "POST")).toBe(true);
    });
    expect(await requests.find((r) => r.method === "POST")?.json()).toEqual({
      status: "active",
      note: null,
    });
  });

  it("names the feature by its nickname in the dialog's title", async () => {
    renderWithApi(<OwnerStatusMenu feature={active} nameOf={() => "Checkout"} />);

    await userEvent.click(within(await openMenu()).getByRole("button", { name: "Pause" }));

    expect(screen.getByRole("dialog", { name: "Pause Checkout?" })).toBeInTheDocument();
  });

  it("shows the server's refusal in the dialog and keeps it open", async () => {
    menu(active, {
      [`POST ${STATUS}`]: aProblem({
        status: 409,
        title: "Conflict",
        detail: "status.md of checkout is not readable",
      }),
    });

    await userEvent.click(within(await openMenu()).getByRole("button", { name: "Pause" }));
    const dialog = screen.getByRole("dialog", { name: "Pause checkout?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Pause" }));

    expect(await within(dialog).findByText("Could not pause")).toBeInTheDocument();
    expect(dialog).toHaveTextContent("status.md of checkout is not readable");
    expect(within(dialog).queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
  });

  it("locks the dialog, saying why, and sends nothing without the launch cookie", async () => {
    noteLaunchCookie("missing");
    const { requests } = menu(active, {
      "/api/v1/screens/shell": aShellView({ launch_cookie: "missing" }),
    });

    await userEvent.click(within(await openMenu()).getByRole("button", { name: "Pause" }));
    const dialog = screen.getByRole("dialog", { name: "Pause checkout?" });
    const confirm = within(dialog).getByRole("button", { name: "Pause" });

    expect(confirm).toBeDisabled();
    expect(confirm).toHaveAttribute("title", expect.stringMatching(/hub web printed/));
    expect(dialog).toHaveTextContent(
      /Changes are locked in this browser\. Open the link hub web printed/,
    );
    await userEvent.click(confirm);
    expect(requests.some((r) => r.method === "POST")).toBe(false);
  });
});

describe("OwnerStatusBanner", () => {
  it.each([
    ["shipped", "Shipped by you · 2 Nov"],
    ["closed", "Closed by you · 2 Nov"],
    ["paused", "Paused by you · 2 Nov"],
  ] as const)("says a feature was %s by you, when and why", (status, head) => {
    const feature = decided(status, "Replaced by refunds");
    renderWithApi(<OwnerStatusBanner feature={feature} />);

    const banner = screen.getByRole("note");
    expect(banner).toHaveAttribute("data-status", status);
    expect(banner).toHaveTextContent(
      `${head} · Replaced by refunds · Its records alone would put it at build.`,
    );
  });

  it("names the step its records show, in words", () => {
    const feature = aFeature({
      ...decided("closed"),
      golden_path: aGoldenPath({ phase: "ux_design" }),
    });
    renderWithApi(<OwnerStatusBanner feature={feature} />);

    expect(screen.getByRole("note")).toHaveTextContent(
      /^Closed by you · 2 Nov · Its records alone would put it at ux design\.$/,
    );
  });

  it("shows nothing while no decision holds", () => {
    const { container } = renderWithApi(<OwnerStatusBanner feature={active} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("writes a decision's day as day and short month, and keeps a date it cannot read", () => {
    expect(fmtDay("2026-11-14T08:00:00Z")).toBe("14 Nov");
    expect(fmtDay("someday")).toBe("someday");
  });
});
