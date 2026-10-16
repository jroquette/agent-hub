import { describe, expect, it } from "vitest";

import { codeReference, readableFields, readableNote } from "./readable";

const NOTE = [
  "# Spec",
  "",
  "Path shorthand:",
  "",
  "- `TA/` = `Tipple_API/Lambdas/Dependencies/`",
  "- `OCS` = `TA/tipple-services/order_cover_service.py`",
  "",
  "The issuer is a Tipple entity (research 1.2, 3). It is read at `OCS:157-165` (verified",
  "for this spec).",
  "",
  'Facts are marked "(verified for this spec)".',
  "",
  "```",
  "(research 9) stays in code",
  "```",
].join("\n");

describe("readableNote", () => {
  it("drops the path shorthand legend and keeps its pairs for expansion", () => {
    const { source, shorthand } = readableNote(NOTE);

    expect(source).not.toContain("Path shorthand");
    expect(source).not.toContain("`TA/` =");
    expect(new Map(shorthand).get("OCS")).toBe("TA/tipple-services/order_cover_service.py");
  });

  it("drops the research and verified markers outside code blocks", () => {
    const { source } = readableNote(NOTE);

    expect(source).toContain("The issuer is a Tipple entity. It is read at `OCS:157-165`.");
    expect(source).toContain("(research 9) stays in code");
    expect(source).toContain('marked "(verified for this spec)".');
  });

  it("reads an inline legend paragraph, as a plan writes it", () => {
    const { source, shorthand } = readableNote(
      "Path shorthand (as in the spec): `TM/` = `tipple-medusa/src/`,\n`MC` = `TM/client.py`.\n\nBody.",
    );

    expect(source.trim()).toBe("Body.");
    expect(shorthand).toHaveLength(2);
  });
});

describe("codeReference", () => {
  const { shorthand } = readableNote(NOTE);

  it("names a shorthand reference by its file, the full path and lines on hover", () => {
    expect(codeReference("OCS:157-165", shorthand)).toEqual({
      label: "order_cover_service.py",
      title: "Tipple_API/Lambdas/Dependencies/tipple-services/order_cover_service.py:157-165",
    });
  });

  it("reads a file with several ranges, a bare range and a path without lines", () => {
    expect(codeReference("constants.py:2, :40-42", [])?.label).toBe("constants.py");
    expect(codeReference(":223-235", [])?.label).toBe("lines 223-235");
    expect(codeReference("apps/admin/store-section.tsx", [])?.label).toBe("store-section.tsx");
  });

  it("leaves code that is not a reference as written", () => {
    for (const code of [
      "webshop.sales_mode",
      "TIPPLE_AS_3PL",
      "POST /admin/x",
      "/webshops/{id}",
      "host:8361",
    ]) {
      expect(codeReference(code, [])).toBeNull();
    }
  });
});

describe("readableFields", () => {
  it("hides what the page already says and labels the rest in words", () => {
    expect(
      readableFields({
        type: "spec",
        feature: "x",
        status: "approved",
        last_verified: "2026-10-12",
      }),
    ).toEqual([
      ["Status", "approved"],
      ["Last checked", "2026-10-12"],
    ]);
  });
});
