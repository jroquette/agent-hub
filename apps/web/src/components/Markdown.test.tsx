import { readFileSync } from "node:fs";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import { MAX_MARKDOWN_BYTES, Markdown } from "./Markdown";

const NOTE = { project: "agent-hub", path: "playbooks/cloud-and-local.md" };

function attributesOf(container: HTMLElement): string[] {
  return [...container.querySelectorAll("*")].flatMap((element) =>
    [...element.attributes].map((attribute) => attribute.name),
  );
}

describe("Markdown blocks", () => {
  it("renders headings, paragraphs, quotes, code, rules and inline marks when given a note", () => {
    const { container } = render(
      <Markdown
        source={[
          "# Title",
          "",
          "Some **bold**, *italic*, __strong__, _em_, ~~gone~~ and `code` text",
          "on two lines with a \\*literal\\* star.",
          "",
          "> quoted **line**",
          "> second line",
          "",
          "```python",
          "print('<b>hi</b>')",
          "```",
          "",
          "---",
          "",
          "###### Small",
        ].join("\n")}
      />,
    );

    expect(screen.getByRole("heading", { level: 1, name: "Title" })).toHaveAttribute(
      "id",
      "md-title",
    );
    expect(screen.getByRole("heading", { level: 6, name: "Small" })).toBeInTheDocument();
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.getByText("strong").tagName).toBe("STRONG");
    expect(screen.getByText("italic").tagName).toBe("EM");
    expect(screen.getByText("em").tagName).toBe("EM");
    expect(screen.getByText("gone").tagName).toBe("DEL");
    expect(screen.getByText("code").tagName).toBe("CODE");
    expect(container.querySelector("p")?.textContent).toContain("with a *literal* star.");
    expect(container.querySelector("blockquote")?.textContent).toBe("quoted line second line");
    expect(container.querySelector("pre code")?.textContent).toBe("print('<b>hi</b>')");
    expect(container.querySelector("pre code")).toHaveAttribute("data-lang", "python");
    expect(container.querySelector("hr")).not.toBeNull();
  });

  it("renders nested ordered and unordered lists when items are indented", () => {
    const { container } = render(
      <Markdown
        source={[
          "3. three",
          "4. four",
          "   - nested a",
          "   - nested b",
          "     lazy",
          "- other",
        ].join("\n")}
      />,
    );

    const ol = container.querySelector("ol");
    expect(ol).toHaveAttribute("start", "3");
    expect(ol?.querySelectorAll(":scope > li")).toHaveLength(2);
    expect(ol?.querySelector("li ul")?.querySelectorAll("li")).toHaveLength(2);
    expect(screen.getByText(/nested b/).textContent).toBe("nested b lazy");
    expect(container.querySelectorAll(":scope > div > ul")).toHaveLength(1);
  });

  it("renders a table with a header row and aligned cells when given a pipe table", () => {
    render(
      <Markdown
        source={["| AC | State |", "|:---|---:|", "| AC-1 | **passes** |", "| AC-2 |"].join("\n")}
      />,
    );

    const table = screen.getByRole("table");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((th) => th.textContent),
    ).toEqual(["AC", "State"]);
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("passes").tagName).toBe("STRONG");
    expect(within(table).getAllByRole("cell")[1]).toHaveStyle({ textAlign: "right" });
  });

  it("numbers repeated headings when two share a title", () => {
    render(<Markdown source={"## Steps\n\n## Steps"} />);

    const ids = screen.getAllByRole("heading", { level: 2 }).map((h) => h.id);
    expect(ids).toEqual(["md-steps", "md-steps-1"]);
  });
});

describe("Markdown safe", () => {
  it("runs no script and keeps raw HTML as text when a note holds HTML and unsafe links (AC-201.35)", () => {
    const alert = vi.spyOn(window, "alert").mockImplementation(() => undefined);
    const { container } = render(
      <Markdown
        note={NOTE}
        source={[
          "<script>alert(1)</script>",
          "",
          '<img src=x onerror="alert(2)">',
          "",
          "A <b onclick=alert(3)>raw</b> tag and a [bad link](javascript:alert(4)).",
          "",
          "![logo](https://example.com/logo.png) and ![local](diagram.png)",
          "",
          "[data](data:text/html,<script>alert(5)</script>)",
        ].join("\n")}
      />,
    );

    expect(container.querySelector("script, img, iframe, object, embed, b")).toBeNull();
    expect(attributesOf(container).filter((name) => name.startsWith("on"))).toEqual([]);
    expect(container.textContent).toContain("<script>alert(1)</script>");
    expect(container.textContent).toContain('<img src=x onerror="alert(2)">');
    expect(container.textContent).toContain("<b onclick=alert(3)>raw</b>");
    expect(screen.getByText("bad link").closest("a")).toBeNull();
    expect(screen.getByText("data").closest("a")).toBeNull();
    const image = screen.getByRole("link", { name: /Image: logo/ });
    expect(image).toHaveAttribute("href", "https://example.com/logo.png");
    expect(image).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText("Image: local").closest("a")).toBeNull();
    expect(alert).not.toHaveBeenCalled();
  });

  it("never sets inner HTML when rendering", () => {
    // Read as a file: Vitest runs from apps/web.
    const code = readFileSync("src/components/Markdown.tsx", "utf8");
    expect(code).not.toMatch(/dangerouslySetInnerHTML|innerHTML|createElement\(\s*[a-z]/);
  });
});

describe("Markdown links", () => {
  const source = [
    "See [the playbook](../playbooks/x.md), [decision 3](decisions/index.md#d3),",
    "[the spec](../../agent-hub/docs/SPEC.md) and [example](https://example.com).",
  ].join("\n");

  it("routes brain notes in the app, keeps outside paths as text and opens the web in a new tab (AC-201.36)", () => {
    render(<Markdown note={{ project: "agent-hub", path: "features/x.md" }} source={source} />);

    expect(screen.getByRole("link", { name: "the playbook" })).toHaveAttribute(
      "href",
      "/projects/agent-hub/brain/playbooks/x.md",
    );
    expect(screen.getByRole("link", { name: "decision 3" })).toHaveAttribute(
      "href",
      "/projects/agent-hub/brain/features/decisions/index.md#d3",
    );
    const spec = screen.getByText("the spec");
    expect(spec.closest("a")).toBeNull();
    expect(spec).toHaveAttribute("title", "outside the brain");
    const web = screen.getByRole("link", { name: /example/ });
    expect(web).toHaveAttribute("href", "https://example.com");
    expect(web).toHaveAttribute("target", "_blank");
    expect(web).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("hands an in-app link to the callback when a brain link is clicked", () => {
    const onBrainLink = vi.fn();
    render(<Markdown note={NOTE} source={source} onBrainLink={onBrainLink} />);

    const link = screen.getByRole("link", { name: "the playbook" });
    const plain = fireEvent.click(link);
    expect(plain).toBe(false);
    expect(onBrainLink).toHaveBeenCalledWith({
      kind: "brain",
      path: "playbooks/x.md",
      anchor: null,
      route: "/projects/agent-hub/brain/playbooks/x.md",
    });
    expect(fireEvent.click(link, { ctrlKey: true })).toBe(true);
    expect(onBrainLink).toHaveBeenCalledTimes(1);
  });

  it("renders relative links as text when the note has no place", () => {
    render(<Markdown source="[a note](x.md)" />);

    expect(screen.getByText("a note").closest("a")).toBeNull();
  });
});

describe("Markdown bounds", () => {
  it("renders lists deeper than 6 levels as text", () => {
    const lines = Array.from(
      { length: 8 },
      (_, depth) => `${"  ".repeat(depth)}- level ${String(depth + 1)}`,
    );
    const { container } = render(<Markdown source={lines.join("\n")} />);

    expect(container.querySelectorAll("ul")).toHaveLength(6);
    expect(screen.getByText(/- level 7/)).toBeInTheDocument();
    expect(screen.getByText(/- level 8/)).toBeInTheDocument();
  });

  it("renders a table wider than 20 columns as text", () => {
    const cols = Array.from({ length: 21 }, (_, i) => `c${String(i)}`);
    const source = [`| ${cols.join(" | ")} |`, `|${cols.map(() => "---").join("|")}|`].join("\n");
    const { container } = render(<Markdown source={source} />);

    expect(container.querySelector("table")).toBeNull();
    expect(container.textContent).toContain("| c0 | c1 |");
  });

  it("shows plain text and a notice when the note is over 256 KiB", () => {
    const source = `# Big\n\n${"x".repeat(MAX_MARKDOWN_BYTES)}`;
    const { container } = render(<Markdown source={source} />);

    expect(screen.getByText(/too large to format/)).toBeInTheDocument();
    expect(container.querySelector("h1")).toBeNull();
    expect(container.querySelector("pre")?.textContent.length).toBe(MAX_MARKDOWN_BYTES);
  });

  it("renders quickly when given unmatched delimiters", () => {
    const started = performance.now();
    render(
      <Markdown
        source={`${"[".repeat(80_000)}${"[a](".repeat(30_000)}${"a_".repeat(20_000)}${"`".repeat(9)}`}
      />,
    );

    expect(performance.now() - started).toBeLessThan(1500);
  });
});

describe("Markdown a11y", () => {
  it("has no serious or critical a11y violation and names new-tab links", async () => {
    const { container } = render(
      <Markdown
        note={NOTE}
        source={[
          "# Note",
          "",
          "| A | B |",
          "|---|---|",
          "| 1 | 2 |",
          "",
          "- [web](https://example.com)",
          "- [note](x.md) and [outside](../../x.md)",
        ].join("\n")}
      />,
    );

    expect(screen.getByRole("link", { name: "web (opens in a new tab)" })).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader")[0]).toHaveAttribute("scope", "col");
    expect(await seriousViolations(container)).toEqual([]);
  });
});
