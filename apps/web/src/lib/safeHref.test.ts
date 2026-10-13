import { describe, expect, it } from "vitest";

import { isInAppPath, linearHref, safeHref } from "./safeHref";

describe("safeHref", () => {
  it.each([
    "https://github.com/acme/app/pull/7",
    "http://localhost:8000/x?y=1#z",
    "HTTPS://linear.app/acme/issue/AGH-1",
  ])("keeps an absolute http(s) URL when given %s", (value) => {
    expect(safeHref(value)).toBe(value);
  });

  it.each(["/sessions/s-1?event=e-1", "?event=e-2", "#po-repos", "docs/SPEC.md", "./a", "../b"])(
    "keeps a same-origin relative path when given %s",
    (value) => {
      expect(safeHref(value)).toBe(value);
    },
  );

  it.each([
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    " javascript:alert(1)",
    "java\tscript:alert(1)",
    "java\nscript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
    "mailto:a@b.c",
    "//evil.example/x",
    "/\\evil.example/x",
    "\\\\evil.example\\x",
    "https:evil.example",
    "",
  ])("returns null when given the unsafe value %j", (value) => {
    expect(safeHref(value)).toBeNull();
  });

  it("returns null when given no value", () => {
    expect(safeHref(null)).toBeNull();
    expect(safeHref(undefined)).toBeNull();
  });
});

describe("isInAppPath", () => {
  it("accepts a root-relative path and rejects outside or unsafe ones", () => {
    expect(isInAppPath("/runs/r-1")).toBe(true);
    expect(isInAppPath("//evil.example")).toBe(false);
    expect(isInAppPath("https://example.com")).toBe(false);
    expect(isInAppPath("javascript:alert(1)")).toBe(false);
  });
});

describe("linearHref", () => {
  it("keeps only an https URL on linear.app when given issue urls (linear-link)", () => {
    expect(linearHref("https://linear.app/acme/issue/TIP-1")).toBe(
      "https://linear.app/acme/issue/TIP-1",
    );
    expect(linearHref("https://evil.example/x")).toBeNull();
    expect(linearHref("javascript:x")).toBeNull();
    expect(linearHref("http://linear.app/x")).toBeNull();
  });

  it.each([
    "https://linear.app.evil.example/x",
    "https://user@linear.app/x",
    "https://linear.app:444/x",
    "https://evil.example/https://linear.app/x",
    "https://linear.app",
    "/acme/issue/TIP-1",
    null,
    undefined,
  ])("returns null when given the look-alike %j (linear-link)", (value) => {
    expect(linearHref(value)).toBeNull();
  });
});
