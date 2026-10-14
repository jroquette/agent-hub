import { describe, expect, it } from "vitest";

import { bundledFileAnchor, resolveSkillLink } from "./skillLinks";

const FILES = [
  { id: "0123456789abcdef", path: "references/r.md" },
  { id: "fedcba9876543210", path: "scripts/s.sh" },
  { id: "00000000000000aa", path: "assets/a b.png" },
];

describe("resolveSkillLink local_link", () => {
  it("finds the bundled file when a relative link names it", () => {
    expect(resolveSkillLink("references/r.md", FILES)?.id).toBe("0123456789abcdef");
    expect(resolveSkillLink("./scripts/s.sh", FILES)?.id).toBe("fedcba9876543210");
    expect(resolveSkillLink("references/../scripts/s.sh", FILES)?.id).toBe("fedcba9876543210");
    expect(resolveSkillLink("references/r.md#usage", FILES)?.id).toBe("0123456789abcdef");
    expect(resolveSkillLink("assets/a%20b.png", FILES)?.id).toBe("00000000000000aa");
  });

  it("gives null when the link leaves the skill folder or names no issued file", () => {
    for (const href of [
      "../other/SKILL.md",
      "references/../../r.md",
      "/references/r.md",
      "https://example.com/references/r.md",
      "javascript:alert(1)",
      "references/r.md?x=1",
      "references/missing.md",
      "#steps",
      "",
      "SKILL.md",
      "references/%E0%A4%A.md",
    ]) {
      expect(resolveSkillLink(href, FILES)).toBeNull();
    }
  });
});

describe("bundledFileAnchor", () => {
  it("names the element of a bundled file by its id", () => {
    expect(bundledFileAnchor("0123456789abcdef")).toBe("skill-file-0123456789abcdef");
  });
});
