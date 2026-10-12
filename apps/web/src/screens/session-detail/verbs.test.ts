import { describe, expect, it } from "vitest";

import {
  contentPhrase,
  gatePhrase,
  guardDeniedPhrase,
  learningPhrase,
  phraseText,
  skillName,
  toolPhrase,
} from "./verbs";

describe("verbs", () => {
  it("names the concrete object of each tool when the call carries it", () => {
    const rows = [
      toolPhrase("Read", { path: "packages/collector/src/x.py" }),
      toolPhrase("Edit", { path: "a/b.py", lines_added: 3, lines_removed: 1 }),
      toolPhrase("Write", { path: "brain/_inbox/n.md", lines_added: 12 }),
      toolPhrase("Bash", { command: "make check" }),
      toolPhrase("Grep", { pattern: "AC-48", path: "brain/" }),
      toolPhrase("Glob", { pattern: "**/*.py" }),
      toolPhrase("WebFetch", { url: "https://example.com/a" }),
      toolPhrase("mcp__linear__get_issue", { mcp_server: "linear", mcp_tool: "get_issue" }),
      toolPhrase("Skill", { skill: "hub-workflow:feature" }),
      toolPhrase("Agent", { subagent_type: "Explore", description: "map the collector" }),
      toolPhrase("SendMessage", { to: "reviewer" }),
      toolPhrase("SubagentHandback", {}),
      toolPhrase("TodoWrite", {}),
      toolPhrase("ToolSearch", {}),
      toolPhrase("WebSearch", {}),
      toolPhrase("NotebookEdit", { path: "n.ipynb" }),
      toolPhrase("Frobnicate", {}),
    ].map(phraseText);

    expect(rows).toEqual([
      "Read packages/collector/src/x.py",
      "Edited a/b.py (+3 −1)",
      "Wrote brain/_inbox/n.md (+12)",
      "Ran `make check`",
      'Searched for "AC-48" in brain/',
      'Listed files matching "**/*.py"',
      "Fetched https://example.com/a",
      "Called linear.get_issue",
      "Ran skill /feature",
      "Started subagent Explore: map the collector",
      "Sent a message to reviewer",
      "Handed back to the main agent",
      "Updated the to-do list",
      "Looked up tools",
      "Searched the web",
      "Edited notebook n.ipynb",
      "Used Frobnicate",
    ]);
  });

  it("falls back to a generic object when the call carries no detail", () => {
    expect(
      [
        toolPhrase("Read", {}),
        toolPhrase("Bash", {}),
        toolPhrase("Grep", { path: "src/" }),
        toolPhrase("Skill", {}),
        toolPhrase("Agent", {}),
        toolPhrase("Task", { subagent_type: "reviewer" }),
        toolPhrase("SendMessage", {}),
        toolPhrase("mcp__x__y", {}),
        toolPhrase("Frobnicate", { path: "a.txt" }),
      ].map(phraseText),
    ).toEqual([
      "Read a file",
      "Ran a command",
      "Searched in src/",
      "Ran a skill",
      "Started subagent subagent",
      "Started subagent reviewer",
      "Sent a message",
      "Called mcp.mcp__x__y",
      "Used Frobnicate a.txt",
    ]);
  });

  it("keeps only the first line of a long command when the verb table phrases Bash", () => {
    const phrase = toolPhrase("Bash", { command: `echo ${"x".repeat(200)}\nsecond line` });
    expect(phrase.object?.endsWith("…")).toBe(true);
    expect(phrase.object?.length).toBe(120);
    expect(phrase.object).not.toContain("second line");
  });

  it("phrases prompts, messages, gates, guards and learnings with plain verbs", () => {
    expect(
      [
        contentPhrase("prompt", 1240, "/feature"),
        contentPhrase("prompt", 12, undefined),
        contentPhrase("message", 300, undefined),
        contentPhrase("reasoning", null, undefined),
        gatePhrase("check", undefined),
        gatePhrase("check", "failed"),
        guardDeniedPhrase("Bash", "no-push-main"),
        guardDeniedPhrase(undefined, undefined),
        learningPhrase("learning.proposed", "Compare render impact"),
        learningPhrase("learning.accepted", undefined),
        learningPhrase("learning.rejected", "x"),
      ].map(phraseText),
    ).toEqual([
      "Prompted /feature (1,240 characters)",
      "Sent a prompt (12 characters)",
      "Replied (300 characters)",
      "Recorded a reasoning summary (size unknown)",
      "Requested gate check",
      "Gate check failed",
      "Guard blocked Bash (rule no-push-main)",
      "Guard blocked a tool call",
      "Proposed a learning: Compare render impact",
      "Accepted a learning",
      "Rejected a learning: x",
    ]);
  });

  it("shows a skill as a slash command without its plugin prefix", () => {
    expect(skillName("hub-workflow:feature")).toBe("/feature");
    expect(skillName("/kickoff")).toBe("/kickoff");
    expect(skillName("review")).toBe("/review");
  });
});
