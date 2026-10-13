import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aBundledFileText, aProblem, aSkillDetail, renderWithApi } from "../../testing/builders";
import { BundledFiles } from "./BundledFiles";

const ITEM = { kind: "skill", source: "hub-workflow", name: "feature" } as const;
const FILES = "/api/v1/projects/demo/skills/skill/hub-workflow/feature/files";
const ALL = [
  ...aSkillDetail().files,
  {
    id: "00000000000000aa",
    link: false,
    path: "assets/logo.png",
    role: "assets",
    size: 2048,
    too_large: false,
  },
  {
    id: "00000000000000bb",
    link: true,
    path: "notes.md",
    role: "other",
    size: 0,
    too_large: false,
  },
  {
    id: "00000000000000cc",
    link: false,
    path: "references/big.md",
    role: "references",
    size: 400_000,
    too_large: true,
  },
] as const;

function files(routes = {}, props: Partial<Parameters<typeof BundledFiles>[0]> = {}) {
  return renderWithApi(<BundledFiles project="demo" item={ITEM} files={[...ALL]} {...props} />, {
    routes,
  });
}

describe("BundledFiles bundled_files", () => {
  it("groups files by role and says what each role means (AC-164.21)", () => {
    files();

    const scripts = screen.getByRole("list", { name: /Scripts/ });
    expect(scripts.closest("section")).toHaveTextContent("executed at invocation");
    expect(within(scripts).getByText("scripts/check.sh")).toBeInTheDocument();
    const references = screen.getByRole("list", { name: /References/ });
    expect(references.closest("section")).toHaveTextContent("read on demand");
    expect(within(references).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("list", { name: /Assets/ })).toHaveTextContent("assets/logo.png");
    expect(screen.getByRole("list", { name: /Other/ })).toHaveTextContent("Link: not read");
    expect(references).toHaveTextContent("Too large to show");
    expect(screen.getAllByRole("button", { name: /^View/ })).toHaveLength(3);
  });

  it("shows a file's text inert when opened", async () => {
    files({ [`${FILES}/0123456789abcdef`]: aBundledFileText() });

    fireEvent.click(screen.getByRole("button", { name: "View references/checklist.md" }));

    const text = await screen.findByText(/The spec is approved/);
    expect(text.tagName).toBe("PRE");
    expect(text.textContent).toBe(aBundledFileText().text);
    expect(screen.getByRole("button", { name: "Hide references/checklist.md" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(document.querySelector("script, iframe, img")).toBeNull();
  });

  it("shows a script as text, never run", async () => {
    files({
      [`${FILES}/fedcba9876543210`]: aBundledFileText({
        id: "fedcba9876543210",
        path: "scripts/check.sh",
        role: "scripts",
        text: "#!/bin/sh\nmake check\n",
      }),
    });

    fireEvent.click(screen.getByRole("button", { name: "View scripts/check.sh" }));

    expect(await screen.findByText(/make check/)).toHaveTextContent("#!/bin/sh make check");
    expect(screen.getByText(/never run/)).toBeInTheDocument();
  });

  it("says a binary file is not shown", async () => {
    files({
      [`${FILES}/00000000000000aa`]: aBundledFileText({
        id: "00000000000000aa",
        binary: true,
        text: null,
      }),
    });

    fireEvent.click(screen.getByRole("button", { name: "View assets/logo.png" }));

    expect(await screen.findByText(/Binary file: not shown/)).toBeInTheDocument();
  });

  it("says a file over the cap is not shown when the API answers 413", async () => {
    files({
      [`${FILES}/0123456789abcdef`]: aProblem({ status: 413, title: "Skill file too large" }),
    });

    fireEvent.click(screen.getByRole("button", { name: "View references/checklist.md" }));

    expect(await screen.findByText(/over 256 KiB/)).toBeInTheDocument();
  });

  it("shows the problem when the file cannot be read", async () => {
    files({ [`${FILES}/0123456789abcdef`]: aProblem({ status: 404, title: "Not found" }) });

    fireEvent.click(screen.getByRole("button", { name: "View references/checklist.md" }));

    expect(await screen.findByText("Not found")).toBeInTheDocument();
  });

  it("opens the file the page asks for and reports toggles when controlled", async () => {
    const onOpenChange = vi.fn();
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    files(
      { [`${FILES}/0123456789abcdef`]: aBundledFileText() },
      { openId: "0123456789abcdef", onOpenChange },
    );

    expect(await screen.findByText(/The spec is approved/)).toBeInTheDocument();
    expect(document.getElementById("skill-file-0123456789abcdef")).not.toBeNull();
    expect(scroll).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Hide references/checklist.md" }));
    expect(onOpenChange).toHaveBeenCalledWith(null);
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
  });

  it("says when a skill has no other files", () => {
    renderWithApi(<BundledFiles project="demo" item={ITEM} files={[]} />);

    expect(screen.getByText(/No files besides SKILL.md/)).toBeInTheDocument();
  });
});

describe("BundledFiles a11y", () => {
  it("has no serious or critical axe violation with a file open", async () => {
    const { container } = files({ [`${FILES}/0123456789abcdef`]: aBundledFileText() });
    fireEvent.click(screen.getByRole("button", { name: "View references/checklist.md" }));
    await screen.findByText(/The spec is approved/);

    expect(await seriousViolations(container)).toEqual([]);
  });
});
