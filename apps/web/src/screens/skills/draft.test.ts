import { describe, expect, it } from "vitest";

import { aCatalogItem } from "../../testing/builders";
import { initialTranscript, type JsonObject, type TranscriptState } from "../agent-session/model";
import {
  destination,
  draftKind,
  draftWrites,
  editDestination,
  editMainFile,
  editPrompt,
  hookFileText,
  insideDraft,
  newDraftId,
  projectPluginDir,
  publishEditPrompt,
  publishPrompt,
  readDocument,
  readHooks,
  skillMode,
  studioPrompt,
  summarize,
} from "./draft";

const HUB = "/home/owner/hubs/demo";
const DRAFT = "skill-abc123";

interface Call {
  name: string;
  input: JsonObject;
  result?: "ok" | "error" | null;
}

function transcriptOf(calls: Call[]): TranscriptState {
  const state = initialTranscript();
  calls.forEach((call, i) => {
    const id = `t${String(i)}`;
    state.entries.push({ kind: "tool", key: id, toolId: id });
    const result = call.result === undefined ? "ok" : call.result;
    state.tools[id] = {
      id,
      name: call.name,
      input: call.input,
      parentId: null,
      diff: null,
      result:
        result === null
          ? null
          : { content: "", isError: result === "error", truncated: false, originalBytes: null },
    };
  });
  return state;
}

const SKILL = `---
name: changelog
description: Writes release notes from the merged PRs. Use when cutting a release.
argument-hint: "[version]"
disable-model-invocation: true
---

# Changelog

1. Read the merged PRs.
`;

describe("draft ids", () => {
  it("issues an id that names its kind and reads it back", () => {
    const id = newDraftId("agent", () => 0.5);
    expect(id).toMatch(/^agent-[a-z0-9]{6}$/);
    expect(draftKind(id)).toBe("agent");
    expect(draftKind("../etc")).toBeNull();
  });
});

describe("insideDraft", () => {
  it("keeps paths under the draft folder, absolute or relative", () => {
    expect(insideDraft(`${HUB}/.hub-drafts/${DRAFT}/SKILL.md`, DRAFT)).toBe("SKILL.md");
    expect(insideDraft(`.hub-drafts/${DRAFT}/references/a.md`, DRAFT)).toBe("references/a.md");
  });

  it("rejects other folders, other drafts and climbing out", () => {
    expect(insideDraft(`${HUB}/plugin/demo/skills/x/SKILL.md`, DRAFT)).toBeNull();
    expect(insideDraft(`${HUB}/.hub-drafts/skill-other/SKILL.md`, DRAFT)).toBeNull();
    expect(insideDraft(`${HUB}/.hub-drafts/${DRAFT}/../x.md`, DRAFT)).toBeNull();
  });
});

describe("draftWrites", () => {
  it("rebuilds files from Write then Edit, in order, and lists writes elsewhere", () => {
    const path = `${HUB}/.hub-drafts/${DRAFT}/SKILL.md`;
    const writes = draftWrites(
      transcriptOf([
        { name: "Write", input: { file_path: path, content: "a b a" } },
        { name: "Edit", input: { file_path: path, old_string: "a", new_string: "c" } },
        {
          name: "MultiEdit",
          input: {
            file_path: path,
            edits: [{ old_string: "a", new_string: "d", replace_all: true }],
          },
        },
        { name: "Write", input: { file_path: `${HUB}/AGENTS.md`, content: "x" } },
        { name: "Read", input: { file_path: path } },
      ]),
      DRAFT,
    );
    expect(writes.files).toEqual([
      { path: "SKILL.md", content: "c b d", partial: false, pending: false },
    ]);
    expect(writes.outside).toEqual([`${HUB}/AGENTS.md`]);
  });

  it("ignores failed calls, marks running ones pending and blind edits partial", () => {
    const dir = `${HUB}/.hub-drafts/${DRAFT}`;
    const writes = draftWrites(
      transcriptOf([
        { name: "Write", input: { file_path: `${dir}/SKILL.md`, content: "x" }, result: "error" },
        {
          name: "Write",
          input: { file_path: `${dir}/scripts/run.sh`, content: "echo" },
          result: null,
        },
        { name: "Edit", input: { file_path: `${dir}/notes.md`, old_string: "a", new_string: "b" } },
      ]),
      DRAFT,
    );
    expect(writes.files.map((f) => [f.path, f.pending, f.partial])).toEqual([
      ["notes.md", false, true],
      ["scripts/run.sh", true, false],
    ]);
  });
});

describe("readDocument", () => {
  it("reads scalars, quoted values, lists and block scalars, and flags unknown keys", () => {
    const doc = readDocument(
      `---\nname: x\nargument-hint: "[v]"\nallowed-tools: [Read, Grep]\ntools:\n  - Bash\ndescription: >\n  one\n  two\nflavour: odd\n---\nBody\n`,
      "skill",
    );
    expect(doc.pairs).toEqual([
      { key: "name", value: "x", known: true },
      { key: "argument-hint", value: "[v]", known: true },
      { key: "allowed-tools", value: ["Read", "Grep"], known: true },
      { key: "tools", value: ["Bash"], known: false },
      { key: "description", value: "one two", known: true },
      { key: "flavour", value: "odd", known: false },
    ]);
    expect(doc.body).toBe("Body\n");
  });

  it("says when the block does not close, and keeps text without frontmatter as body", () => {
    expect(readDocument("---\nname: x\n", "agent").unclosed).toBe(true);
    expect(readDocument("# Only body", "agent")).toEqual({
      pairs: [],
      body: "# Only body",
      unclosed: false,
    });
  });
});

describe("skillMode", () => {
  it("derives who can invoke a skill from its two flags", () => {
    const pair = (key: string, value: string) => ({ key, value, known: true });
    expect(skillMode([])).toBe("both");
    expect(skillMode([pair("disable-model-invocation", "true")])).toBe("user-only");
    expect(skillMode([pair("user-invocable", "false")])).toBe("model-only");
    expect(
      skillMode([pair("disable-model-invocation", "true"), pair("user-invocable", "false")]),
    ).toBe("neither");
  });
});

describe("readHooks", () => {
  it("lists each hook with its event and matcher", () => {
    const read = readHooks(
      JSON.stringify({
        hooks: {
          PreToolUse: [
            { matcher: "Bash", hooks: [{ type: "command", command: "guard.sh", timeout: 5 }] },
          ],
          Stop: [{ hooks: [{ type: "command", command: "log.sh" }] }],
        },
      }),
    );
    expect(read.error).toBeNull();
    expect(read.hooks).toEqual([
      { event: "PreToolUse", matcher: "Bash", type: "command", command: "guard.sh", timeout: 5 },
      { event: "Stop", matcher: null, type: "command", command: "log.sh", timeout: null },
    ]);
  });

  it("says why a file does not read", () => {
    expect(readHooks("{").error).not.toBeNull();
    expect(readHooks("{}").error).toBe('No "hooks" object at the top level.');
  });
});

describe("summarize", () => {
  const file = (path: string, content: string) => ({
    path,
    content,
    partial: false,
    pending: false,
  });

  it("turns a skill draft into its catalog card and passes the checks", () => {
    const summary = summarize("skill", [file("SKILL.md", SKILL)]);
    expect(summary.name).toBe("changelog");
    expect(summary.card).toMatchObject({
      kind: "skill",
      name: "changelog",
      origin: "project-owned",
      mode: "user-only",
      invocation: "/changelog [version]",
      diagnostics_count: 0,
    });
    expect(summary.checks.every((c) => c.state === "ok")).toBe(true);
    expect(summary.publishable).toBe(true);
  });

  it("warns on a taken name and a missing description, and waits while Claude writes", () => {
    const text = "---\nname: changelog\n---\nBody";
    const summary = summarize(
      "skill",
      [{ ...file("SKILL.md", text), pending: true }],
      new Set(["changelog"]),
    );
    const states = Object.fromEntries(summary.checks.map((c) => [c.id, c.state]));
    expect(states).toMatchObject({ name: "warn", description: "warn", pending: "todo" });
    expect(summary.publishable).toBe(false);
  });

  it("has nothing to publish before the main file exists", () => {
    const summary = summarize("agent", [file("notes/x.txt", "x")]);
    expect(summary.card).toBeNull();
    expect(summary.publishable).toBe(false);
  });

  it("reads an agent's name from the frontmatter or the file name", () => {
    expect(
      summarize("agent", [file("reviewer.md", "---\ndescription: d\n---\nYou review.")]).name,
    ).toBe("reviewer");
  });

  it("describes a hook draft by its first hook", () => {
    const json = JSON.stringify({
      hooks: { PreToolUse: [{ matcher: "Bash", hooks: [{ type: "command", command: "g.sh" }] }] },
    });
    const summary = summarize("hook", [file("hooks.json", json)]);
    expect(summary.description).toBe("PreToolUse (Bash): g.sh");
    expect(summary.publishable).toBe(true);
  });
});

describe("where it is published", () => {
  it("picks the plugin most project-owned items come from", () => {
    const items = [
      aCatalogItem({ origin: "project-owned", source_path: "plugin/demo/skills/a/SKILL.md" }),
      aCatalogItem({ origin: "project-owned", source_path: "plugin/demo/agents/b.md" }),
      aCatalogItem({ origin: "managed", source_path: "plugin/hub-workflow/skills/c/SKILL.md" }),
    ];
    expect(projectPluginDir(items)).toBe("plugin/demo");
    expect(projectPluginDir([])).toBeNull();
  });

  it("names the destination of each kind", () => {
    expect(destination("skill", "x", "plugin/demo")).toBe("plugin/demo/skills/x/");
    expect(destination("agent", "x", "plugin/demo")).toBe("plugin/demo/agents/x.md");
    expect(destination("hook", null, null)).toBe("plugin/<project plugin>/hooks/hooks.json");
  });
});

describe("prompts", () => {
  it("tells Claude where to write the draft, ending with the owner's words", () => {
    const prompt = studioPrompt(
      { project: "demo", kind: "skill", draftId: DRAFT, pluginDir: "plugin/demo", taken: ["plan"] },
      "A changelog skill",
    );
    expect(prompt).toContain(`.hub-drafts/${DRAFT}/`);
    expect(prompt).toContain("plugin/demo/");
    expect(prompt).toContain("names are taken: plan");
    expect(prompt.endsWith("What I want:\nA changelog skill")).toBe(true);
  });

  it("asks to move the draft into place and delete it, without committing", () => {
    const prompt = publishPrompt("skill", DRAFT, "plugin/demo/skills/x/");
    expect(prompt).toContain(`Move the folder .hub-drafts/${DRAFT}/ to plugin/demo/skills/x/`);
    expect(prompt).toContain("do not commit");
  });
});

describe("an edit draft", () => {
  const file = (path: string, content: string) => ({
    path,
    content,
    partial: false,
    pending: false,
  });
  const baseline = { name: "changelog", original: SKILL, managed: false };

  it("is not publishable while the draft is the current version", () => {
    const summary = summarize("skill", [file("SKILL.md", SKILL)], new Set(["changelog"]), baseline);
    expect(summary.checks.find((c) => c.id === "changed")?.state).toBe("todo");
    expect(summary.checks.find((c) => c.id === "name")?.label).toBe('Name "changelog" unchanged');
    expect(summary.publishable).toBe(false);
  });

  it("counts the changed lines once the draft differs", () => {
    const changed = SKILL.replace(
      "1. Read the merged PRs.",
      "1. Read the merged PRs since the tag.",
    );
    const summary = summarize(
      "skill",
      [file("SKILL.md", changed)],
      new Set(["changelog"]),
      baseline,
    );
    expect(summary.checks.find((c) => c.id === "changed")).toMatchObject({
      state: "ok",
      label: "+1 −1 lines",
    });
    expect(summary.publishable).toBe(true);
  });

  it("warns on a rename and on a managed item", () => {
    const renamed = SKILL.replace("name: changelog", "name: release-notes");
    const summary = summarize("skill", [file("SKILL.md", renamed)], new Set(["changelog"]), {
      ...baseline,
      managed: true,
    });
    expect(summary.checks.find((c) => c.id === "name")?.label).toContain(
      'Renamed from "changelog"',
    );
    expect(summary.checks.find((c) => c.id === "managed")?.state).toBe("warn");
  });

  it("lands on the item's own folder or file", () => {
    expect(editDestination("skill", "plugin/demo/skills/changelog/SKILL.md")).toBe(
      "plugin/demo/skills/changelog/",
    );
    expect(editDestination("agent", "plugin/demo/agents/reviewer.md")).toBe(
      "plugin/demo/agents/reviewer.md",
    );
    expect(editMainFile("agent", "plugin/demo/agents/reviewer.md")).toBe("reviewer.md");
    expect(editMainFile("hook", ".claude/settings.json")).toBe("hooks.json");
  });

  it("starts a hook from a hooks.json of that hook alone", () => {
    const text = hookFileText({
      event: "PreToolUse",
      matcher: "Bash",
      type: "command",
      command: "./guard.sh",
      timeout: null,
    });
    expect(readHooks(text).hooks).toEqual([
      {
        event: "PreToolUse",
        matcher: "Bash",
        type: "command",
        command: "./guard.sh",
        timeout: null,
      },
    ]);
  });

  it("tells Claude to copy the item first and to leave the original alone", () => {
    const prompt = editPrompt(
      {
        project: "demo",
        kind: "skill",
        draftId: DRAFT,
        name: "changelog",
        sourcePath: "plugin/demo/skills/changelog/SKILL.md",
        managed: false,
        hookText: null,
      },
      "Shorten it",
    );
    expect(prompt).toContain(`writing it unchanged, whole, to .hub-drafts/${DRAFT}/SKILL.md`);
    expect(prompt).toContain("Do not touch the original");
    expect(prompt.endsWith("What I want to change:\nShorten it")).toBe(true);
  });

  it("publishes the draft's files over the item's", () => {
    const prompt = publishEditPrompt("skill", DRAFT, "plugin/demo/skills/changelog/SKILL.md", null);
    expect(prompt).toContain(
      `Copy every file of .hub-drafts/${DRAFT}/ over its counterpart in plugin/demo/skills/changelog/`,
    );
    expect(prompt).toContain(`Then delete .hub-drafts/${DRAFT}/`);
  });
});
