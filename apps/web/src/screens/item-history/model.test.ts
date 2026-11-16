import { describe, expect, it } from "vitest";

import { anItemVersion, anItemVersionContent } from "../../testing/builders";
import {
  COMPARE_MAX_LINES,
  authorWords,
  compareChanges,
  folderDiff,
  originWords,
  shortHash,
  writeProblemWords,
} from "./model";
import { ApiProblem } from "../../lib/api";

const OLDER = anItemVersion({
  id: "0199f0a1-0000-7000-8000-00000000000a",
  origin: "external",
  first: true,
  author: null,
  content_hash: `sha256:0badc0de${"0".repeat(56)}`,
});

describe("item history model", () => {
  it("history_panel origin words name every origin", () => {
    const byId = new Map([[OLDER.id, OLDER]]);

    expect(originWords(anItemVersion({ origin: "publish" }), byId)).toBe("Published");
    expect(originWords(OLDER, byId)).toBe("First seen");
    expect(originWords(anItemVersion({ origin: "external", author: null }), byId)).toBe(
      "Changed outside the app",
    );
    expect(originWords(anItemVersion({ origin: "restore", restored_from: OLDER.id }), byId)).toBe(
      "Restored from 0badc0de",
    );
    expect(
      originWords(anItemVersion({ origin: "restore", restored_from: "0199f0a1-ffff" }), byId),
    ).toBe("Restored from an older version");
  });

  it("history_panel author words say Outside the app without an author", () => {
    expect(authorWords(anItemVersion({ origin: "external", author: null }))).toBe(
      "Outside the app",
    );
    expect(authorWords(anItemVersion())).toBe("Example Owner");
  });

  it("history_panel short hash keeps eight hex characters", () => {
    expect(shortHash(`sha256:1234abcd${"f".repeat(56)}`)).toBe("1234abcd");
    expect(shortHash("deadbeefcafe")).toBe("deadbeef");
  });

  it("compare_any_two folder diff lists added removed and bits", () => {
    const older = anItemVersionContent({
      files: [
        { path: "SKILL.md", executable: false, size: 3, text: "one" },
        { path: "references/old.md", executable: false, size: 3, text: "old" },
        { path: "scripts/run.sh", executable: false, size: 4, text: "echo" },
        { path: "same.md", executable: false, size: 4, text: "same" },
      ],
    });
    const newer = anItemVersionContent({
      files: [
        { path: "SKILL.md", executable: false, size: 3, text: "two" },
        { path: "references/new.md", executable: false, size: 3, text: "new" },
        { path: "same.md", executable: false, size: 4, text: "same" },
        { path: "scripts/run.sh", executable: true, size: 4, text: "echo" },
      ],
    });

    const changes = folderDiff(older.files, newer.files);

    expect(changes.map((c) => [c.path, c.status, c.textChanged, c.bitsChanged])).toEqual([
      ["SKILL.md", "changed", true, false],
      ["references/new.md", "added", true, false],
      ["references/old.md", "removed", true, false],
      ["scripts/run.sh", "changed", false, true],
    ]);
  });

  it("puts each refusal code in words", () => {
    const refused = (code: string, reason = "why") =>
      new ApiProblem({ status: 409, title: "Item write refused", detail: reason, code, reason });

    expect(writeProblemWords(refused("secret_unversioned"))).toContain("secret match");
    expect(writeProblemWords(refused("hub_read_only"))).toContain("read-only");
    expect(writeProblemWords(refused("no_author", "git user.email is not set"))).toContain(
      "git user.email is not set",
    );
    expect(writeProblemWords(refused("link_in_path"))).toContain("link");
    expect(writeProblemWords(refused("unit_unreadable"))).toContain("cannot be read");
    expect(writeProblemWords(new ApiProblem({ status: 401, title: "Unauthorized" }))).toContain(
      "?token=",
    );
    expect(
      writeProblemWords(
        new ApiProblem({ status: 503, title: "Busy", code: "written_not_recorded" }),
      ),
    ).toContain("not recorded");
  });

  it("compare_any_two keeps a diff whole at exactly the line budget", () => {
    // Three header lines and COMPARE_MAX_LINES - 3 added lines: the budget, not past it.
    const text = Array.from({ length: COMPARE_MAX_LINES - 3 }, () => "x").join("\n");
    const [change] = compareChanges([], [{ path: "a.md", executable: false, size: 1, text }]);

    expect(change?.diff?.split("\n")).toHaveLength(COMPARE_MAX_LINES);
    expect(change?.hiddenLines).toBe(0);
  });

  it("puts a failed write and a lost race in words", () => {
    const failed = (detail: string) =>
      new ApiProblem({ status: 500, title: "Item write failed", detail, code: "write_failed" });
    const rollback =
      "The write failed and the old folder could not be put back; hub doctor lists what was left beside it. Nothing was recorded.";

    expect(writeProblemWords(failed(rollback))).toBe(rollback);
    expect(
      writeProblemWords(new ApiProblem({ status: 500, title: "x", code: "write_failed" })),
    ).toBe("The write failed; the item is as it was.");
    expect(
      writeProblemWords(new ApiProblem({ status: 503, title: "Busy", code: "version_race" })),
    ).toBe("Another write took this item's next version first. Nothing was written; try again.");
  });
});
