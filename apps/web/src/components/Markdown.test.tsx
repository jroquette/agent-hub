import { readFileSync } from "node:fs";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import { aFeatureShapedBody } from "../testing/builders";
import { MAX_HEADING_CHARS, MAX_MARKDOWN_BYTES, Markdown, plainHeadingText } from "./Markdown";

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

  it.each([
    ["# a #", "a"],
    ["# a#", "a#"],
    ["# #", ""],
    ["#   ", ""],
    ["# a ##  ", "a"],
    ["## a\t#\t", "a"],
    ["#" + " ".repeat(1000), ""],
  ])("strips the closing sequence when heading %j is read (as core's TOC)", (line, text) => {
    const { container } = render(<Markdown source={line} />);

    const headings = [...container.querySelectorAll("h1, h2")];
    expect(headings.map((heading) => heading.textContent)).toEqual([text]);
  });

  it("renders a line over the heading cap as text (as core's TOC)", () => {
    const atCap = "# " + "a".repeat(MAX_HEADING_CHARS - 2);
    const over = "# " + "b".repeat(MAX_HEADING_CHARS - 1);

    const { container } = render(<Markdown source={`${atCap}\n\n${over}`} />);

    expect(atCap).toHaveLength(MAX_HEADING_CHARS);
    expect([...container.querySelectorAll("h1")].map((h) => h.textContent)).toEqual([
      "a".repeat(MAX_HEADING_CHARS - 2),
    ]);
    expect(container.querySelector("p")?.textContent).toBe(over);
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

describe("Markdown unsafe skill bodies", () => {
  it("renders skill bodies' HTML, scripts, remote images and dynamic context as inert text (AC-164.29)", () => {
    const alert = vi.spyOn(window, "alert").mockImplementation(() => undefined);
    const open = vi.fn();
    const { container } = render(
      <Markdown
        stepAnchors
        localLink={(href) => {
          open(href);
          return null;
        }}
        source={[
          "<script>alert(1)</script>",
          "",
          "<img src=x onerror=alert(2)>",
          "",
          "A [x](javascript:alert(3)) link and ![r](https://evil.example/x.png).",
          "",
          "Context: !`rm -rf /` then ${CLAUDE_PROJECT_DIR}/scripts.",
          "",
          "```!",
          "git status",
          "```",
        ].join("\n")}
      />,
    );

    expect(container.querySelector("script, img, iframe, object, embed")).toBeNull();
    expect(attributesOf(container).filter((name) => name.startsWith("on"))).toEqual([]);
    expect(container.textContent).toContain("<script>alert(1)</script>");
    expect(container.textContent).toContain("<img src=x onerror=alert(2)>");
    expect(screen.getByText("x").closest("a")).toBeNull();
    expect(screen.getByText("rm -rf /").tagName).toBe("CODE");
    expect(container.textContent).toContain("${CLAUDE_PROJECT_DIR}/scripts");
    expect(container.querySelector("pre code")?.textContent).toBe("git status");
    expect(open).not.toHaveBeenCalled();
    expect(alert).not.toHaveBeenCalled();
  });
});

describe("Markdown step_anchors", () => {
  it("anchors each top-level numbered item as a step when the body is feature-shaped (P5)", () => {
    const { container } = render(<Markdown source={aFeatureShapedBody()} stepAnchors />);

    const steps = [...container.querySelectorAll("[id^='step-']")];
    expect(steps.map((step) => step.id)).toEqual([
      "step-1",
      "step-2",
      "step-3",
      "step-4",
      "step-5",
    ]);
    expect(steps.every((step) => step.tagName === "LI")).toBe(true);
    expect(container.querySelector("#step-2")?.textContent).toMatch(
      /^Gate: user approves the spec/,
    );
    expect(container.querySelector("#step-5")?.textContent).toContain("./hub doctor");
  });

  it("counts steps across lists and skips quoted ones", () => {
    const { container } = render(
      <Markdown stepAnchors source={"1. one\n\n## Next\n\n1. two\n2. three\n\n> 1. quoted"} />,
    );

    expect(
      [...container.querySelectorAll("[id^='step-']")].map((step) => step.textContent),
    ).toEqual(["one", "two", "three"]);
  });

  it("anchors only lists at column 0 when a list is indented 1 to 3 spaces (as core)", () => {
    const { container } = render(
      <Markdown stepAnchors source={" 1. one\n   2. two\n\n1. three"} />,
    );

    expect(
      [...container.querySelectorAll("[id^='step-']")].map((step) => step.textContent),
    ).toEqual(["three"]);
    expect(container.querySelectorAll("ol > li")).toHaveLength(3);
  });

  it("sets no step ids when step anchors are off", () => {
    const { container } = render(<Markdown source={aFeatureShapedBody()} />);

    expect(container.querySelector("[id^='step-']")).toBeNull();
  });
});

describe("Markdown local_link", () => {
  it("asks the local resolver first for relative links and opens what it resolves", () => {
    const open = vi.fn();
    const localLink = vi.fn((href: string) =>
      href.startsWith("references/") ? { href: "#skill-file-1", open } : null,
    );
    render(
      <Markdown
        localLink={localLink}
        source="See [r](references/r.md), [other](../x.md), [web](https://example.com) and [bad](javascript:x)."
      />,
    );

    const link = screen.getByRole("link", { name: "r" });
    expect(link).toHaveAttribute("href", "#skill-file-1");
    expect(fireEvent.click(link)).toBe(false);
    expect(open).toHaveBeenCalledTimes(1);
    expect(fireEvent.click(link, { metaKey: true })).toBe(true);
    expect(open).toHaveBeenCalledTimes(1);
    expect(screen.getByText("other").closest("a")).toBeNull();
    expect(screen.getByText("bad").closest("a")).toBeNull();
    expect(screen.getByRole("link", { name: /web/ })).toHaveAttribute("target", "_blank");
    expect(localLink.mock.calls.map(([href]) => href)).toEqual(["references/r.md", "../x.md"]);
  });
});

describe("plainHeadingText", () => {
  it("drops inline marks when given a heading's source text", () => {
    expect(plainHeadingText("Run `make check` **now** [here](x.md)")).toBe(
      "Run make check now here",
    );
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

describe("Markdown code blocks (AC-234.23)", () => {
  it("labels a fenced block with its language and copies exactly its code", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(
      <Markdown source={["Before", "", "```ts", "const a = 1;", "let b = a;", "```"].join("\n")} />,
    );

    const block = screen.getByRole("group", { name: "ts code" });
    expect(within(block).getByText("ts", { selector: ".ah-md-lang" })).toBeInTheDocument();
    fireEvent.click(within(block).getByRole("button", { name: "Copy code" }));

    expect(writeText).toHaveBeenCalledWith("const a = 1;\nlet b = a;");
    expect(await within(block).findByRole("button", { name: "Copied" })).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("shows no label but still a Copy button when the fence has no language", () => {
    const { container } = render(<Markdown source={["```", "plain", "```"].join("\n")} />);

    expect(container.querySelector(".ah-md-lang")).toBeNull();
    expect(screen.getByRole("group", { name: "Code" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy code" })).toBeInTheDocument();
  });

  it("shows an odd info string as plain text when it holds HTML", () => {
    const { container } = render(
      <Markdown source={["```<img/src=x/onerror=alert(1)>", "x", "```"].join("\n")} />,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(attributesOf(container).filter((name) => name.startsWith("on"))).toEqual([]);
    expect(container.querySelector(".ah-md-lang")?.textContent).toBe(
      "<img/src=x/onerror=alert(1)>",
    );
  });
});

describe("Markdown agent text (AC-234.23)", () => {
  it("keeps an <img onerror> in agent text as inert text", () => {
    const alert = vi.spyOn(window, "alert").mockImplementation(() => undefined);
    const { container } = render(
      <Markdown source={"Look: <img src=x onerror=alert(1)> done"} className="as-md" />,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(attributesOf(container).filter((name) => name.startsWith("on"))).toEqual([]);
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
    expect(alert).not.toHaveBeenCalled();
  });
});

describe("Markdown tables (AC-234.23)", () => {
  it("puts a wide table in a keyboard-scrollable, labelled region", () => {
    const head = Array.from({ length: 12 }, (_, i) => `Column ${String(i)} with a long title`);
    render(
      <Markdown
        source={[
          `| ${head.join(" | ")} |`,
          `|${head.map(() => "---").join("|")}|`,
          `| ${head.map((_, i) => `value ${String(i)}`).join(" | ")} |`,
        ].join("\n")}
      />,
    );

    const region = screen.getByRole("region", { name: "Table" });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(region).toHaveClass("ah-md-table");
    expect(within(region).getByRole("table")).toBeInTheDocument();
  });
});
