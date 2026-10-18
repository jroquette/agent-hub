import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aProblem,
  anItemVersion,
  anItemVersionPage,
  renderWithApi,
  type ApiRoutes,
  type ItemVersionPage,
} from "../../testing/builders";
import { HistoryPanel } from ".";
import type { HistoryTarget } from "./queries";

const VERSIONS = "/api/v1/projects/demo/skills/hook/settings/settings-pretooluse-1/versions";
const OLD = "0199f0a1-0000-7000-8000-000000000001";
const RESTORE = `POST ${VERSIONS}/${OLD}/restore`;
const TARGET: HistoryTarget = {
  kind: "item",
  project: "demo",
  item: { kind: "hook", source: "settings", name: "settings-pretooluse-1" },
};
const S9 = "This file is managed by hub.lock: the next hub sync rewrites it. Restore anyway?";

const two = [
  anItemVersion({
    id: "0199f0a1-0000-7000-8000-000000000002",
    content_hash: `sha256:22222222${"0".repeat(56)}`,
  }),
  anItemVersion({
    id: OLD,
    origin: "external",
    first: true,
    author: null,
    content_hash: `sha256:11111111${"0".repeat(56)}`,
  }),
];

function hookPage(overrides: Partial<ItemVersionPage> = {}) {
  return anItemVersionPage({
    items: two,
    unit_kind: "hook",
    unit_path: ".claude/settings.json",
    shared_by: 3,
    ...overrides,
  });
}

function renderPanel(routes: ApiRoutes) {
  return renderWithApi(<HistoryPanel target={TARGET} />, { routes });
}

const posts = (requests: Request[]) => requests.filter((r) => r.method === "POST");

async function openRestore() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Show history" }));
  await user.click(await screen.findByRole("button", { name: /^Restore 11111111/ }));
  return { user, dialog: await screen.findByRole("alertdialog") };
}

describe("RestoreDialog", () => {
  it("managed_warning before any write and Cancel sends nothing", async () => {
    const { requests } = renderPanel({
      [VERSIONS]: hookPage({ managed: true }),
      [RESTORE]: { changed: true, versioned: true, reason: null, version: two[0] },
    });

    const { user, dialog } = await openRestore();
    expect(within(dialog).getByText(S9)).toBeInTheDocument();
    expect(posts(requests)).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(posts(requests)).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: /^Restore 11111111/ }));
    await user.click(await screen.findByRole("button", { name: "Restore anyway" }));

    await screen.findByText(/Restored 11111111/);
    const sent = posts(requests);
    expect(sent).toHaveLength(1);
    expect(await sent[0]?.clone().json()).toEqual({ confirm_managed: true });
  });

  it("managed_warning absent for a project-owned item which sends no confirmation", async () => {
    const { requests } = renderPanel({
      [VERSIONS]: hookPage({ managed: false }),
      [RESTORE]: { changed: true, versioned: true, reason: null, version: two[0] },
    });

    const { user, dialog } = await openRestore();
    expect(within(dialog).queryByText(/hub sync/)).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: "Restore" }));

    await screen.findByText(/Restored 11111111/);
    expect(await posts(requests)[0]?.clone().json()).toEqual({ confirm_managed: false });
  });

  it("managed_warning shows when the server asks for it and Restore anyway confirms", async () => {
    let calls = 0;
    const { requests } = renderPanel({
      [VERSIONS]: hookPage({ managed: false }),
      [RESTORE]: () =>
        ++calls === 1
          ? aProblem({
              status: 409,
              title: "Item write refused",
              code: "managed_confirmation_required",
              reason: "The item is managed: the next hub sync rewrites it",
            })
          : { changed: true, versioned: true, reason: null, version: two[0] },
    });

    const { user, dialog } = await openRestore();
    await user.click(within(dialog).getByRole("button", { name: "Restore" }));
    expect(await within(dialog).findByText(S9)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Restore anyway" }));

    await screen.findByText(/Restored 11111111/);
    const bodies = await Promise.all(posts(requests).map((r) => r.clone().json()));
    expect(bodies).toEqual([{ confirm_managed: false }, { confirm_managed: true }]);
  });

  it("hook_restore names the file and the hook count", async () => {
    renderPanel({ [VERSIONS]: hookPage() });

    const { dialog } = await openRestore();

    expect(dialog).toHaveTextContent(
      "Restores the whole file .claude/settings.json: every hook in it (3 hooks today).",
    );
  });

  it("secret disables Restore on every version", async () => {
    const user = userEvent.setup();
    renderPanel({ [VERSIONS]: hookPage({ state: "secret" }) });

    await user.click(screen.getByRole("button", { name: "Show history" }));
    await screen.findByText("Not versioned: secret");
    const buttons = screen.getAllByRole("button", { name: /^Restore / });
    expect(buttons).toHaveLength(2);
    for (const button of buttons) expect(button).toBeDisabled();
  });

  it("secret refusal from the server is shown in words", async () => {
    renderPanel({
      [VERSIONS]: hookPage(),
      [RESTORE]: aProblem({
        status: 409,
        title: "Item write refused",
        code: "secret_unversioned",
        reason: "The item on disk holds a secret match and has no version",
      }),
    });

    const { user, dialog } = await openRestore();
    await user.click(within(dialog).getByRole("button", { name: "Restore" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "holds a secret match and has no version",
    );
  });

  it("says when the item already holds the version and nothing was written", async () => {
    renderPanel({
      [VERSIONS]: hookPage(),
      [RESTORE]: { changed: false, versioned: true, reason: null, version: null },
    });

    const { user, dialog } = await openRestore();
    await user.click(within(dialog).getByRole("button", { name: "Restore" }));

    expect(
      await screen.findByText("The item already holds 11111111: nothing was written."),
    ).toBeInTheDocument();
  });

  it("a11y restore dialog has no serious violations and works from the keyboard", async () => {
    const { requests } = renderPanel({
      [VERSIONS]: hookPage({ managed: true }),
      [RESTORE]: { changed: true, versioned: true, reason: null, version: two[0] },
    });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Show history" }));
    const restore = await screen.findByRole("button", { name: /^Restore 11111111/ });
    restore.focus();
    await user.keyboard("{Enter}");
    const dialog = await screen.findByRole("alertdialog");
    expect(await seriousViolations(dialog)).toEqual([]);
    // Focus starts on Cancel; Escape closes without a request.
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(posts(requests)).toHaveLength(0);

    restore.focus();
    await user.keyboard("{Enter}");
    await screen.findByRole("alertdialog");
    await user.tab();
    expect(screen.getByRole("button", { name: "Restore anyway" })).toHaveFocus();
    await user.keyboard("{Enter}");
    await screen.findByText(/Restored 11111111/);
    expect(posts(requests)).toHaveLength(1);
  });
});
