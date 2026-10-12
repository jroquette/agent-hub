import { describe, expect, it } from "vitest";

import {
  OUTSIDE_BRAIN,
  anchorId,
  brainRoute,
  headingSlug,
  resolveBrainLink,
  type BrainLink,
} from "./brainLinks";

const NOTE = "playbooks/cloud-and-local.md";
const resolve = (href: string): BrainLink => resolveBrainLink(href, NOTE, "agent-hub");

describe("resolveBrainLink", () => {
  it("routes a relative note link inside the app when it stays in the brain", () => {
    expect(resolve("../features/x/plan.md")).toEqual({
      kind: "brain",
      path: "features/x/plan.md",
      anchor: null,
      route: "/projects/agent-hub/brain/features/x/plan.md",
    });
    expect(resolve("./notes.md")).toMatchObject({ kind: "brain", path: "playbooks/notes.md" });
  });

  it("keeps the anchor when the link has a fragment", () => {
    expect(resolve("../decisions/index.md#d3")).toEqual({
      kind: "brain",
      path: "decisions/index.md",
      anchor: "d3",
      route: "/projects/agent-hub/brain/decisions/index.md#d3",
    });
    expect(resolve("#steps")).toEqual({
      kind: "brain",
      path: NOTE,
      anchor: "steps",
      route: "/projects/agent-hub/brain/playbooks/cloud-and-local.md#steps",
    });
  });

  it("decodes percent escapes and encodes the route when a name has spaces", () => {
    expect(resolve("my%20note.md")).toMatchObject({
      path: "playbooks/my note.md",
      route: "/projects/agent-hub/brain/playbooks/my%20note.md",
    });
  });

  it("marks a link outside the brain when it climbs above brain/ or is absolute", () => {
    expect(resolve("../../agent-hub/docs/SPEC.md")).toEqual({
      kind: "outside",
      title: OUTSIDE_BRAIN,
    });
    expect(resolve("/etc/passwd")).toEqual({ kind: "outside", title: OUTSIDE_BRAIN });
  });

  it("opens an http(s) link outside the app when it is absolute", () => {
    expect(resolve("https://example.com/a?b=1")).toEqual({
      kind: "external",
      href: "https://example.com/a?b=1",
    });
  });

  it.each([
    "javascript:alert(1)",
    "JAVASCRIPT:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "mailto:a@b.c",
    "//evil.example/x.md",
    "notes\\x.md",
    "java\nscript:alert(1)",
    "",
    "bad%zz.md",
    "x.md?raw=1",
  ])("renders %j as text when it is not a safe link", (href) => {
    expect(resolve(href).kind).toBe("text");
  });

  it("renders a relative link as text when it is not a Markdown note or is hidden", () => {
    expect(resolve("diagram.png").kind).toBe("text");
    expect(resolve("../auto/me.md").kind).toBe("text");
    expect(resolve("../Auto/me.md").kind).toBe("text");
    expect(resolve("../AUTO/workspace/me.md").kind).toBe("text");
    expect(resolve(".secret.md").kind).toBe("text");
  });

  it("renders a relative link as text when the note's place is unknown", () => {
    expect(resolveBrainLink("x.md", null, null).kind).toBe("text");
    expect(resolveBrainLink("https://example.com", null, null).kind).toBe("external");
  });

  it("renders a link as text when its path is over the bounds", () => {
    expect(resolve(`${"a/".repeat(20)}x.md`).kind).toBe("text");
    expect(resolve(`${"a".repeat(600)}.md`).kind).toBe("text");
  });
});

describe("brainRoute", () => {
  it("encodes the project and each path segment when building the route", () => {
    expect(brainRoute("my project", "a b/c.md", "x y")).toBe(
      "/projects/my%20project/brain/a%20b/c.md#x%20y",
    );
  });
});

describe("headingSlug", () => {
  it("makes GitHub-style slugs when given heading text", () => {
    expect(headingSlug("D3: Use the hub's PR!")).toBe("d3-use-the-hubs-pr");
    expect(headingSlug("  Ação rápida  ")).toBe("ação-rápida");
  });

  it("prefixes ids so a note cannot clobber page globals when building anchor ids", () => {
    expect(anchorId("D3")).toBe("md-d3");
  });
});
