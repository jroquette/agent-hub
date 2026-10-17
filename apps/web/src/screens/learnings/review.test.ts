import { describe, expect, it } from "vitest";

import { initialTranscript, type JsonObject, type TranscriptState } from "../agent-session/model";
import { parseReview, reviewPrompt, reviewWrites, triageDraftId, triagePrompt } from "./review";

const DRAFT = "learning-abc123";
const DIR = `/home/owner/hubs/demo/.hub-drafts/${DRAFT}`;

function transcriptOf(
  calls: { name: string; input: JsonObject; done?: boolean }[],
): TranscriptState {
  const state = initialTranscript();
  calls.forEach((call, i) => {
    const id = `t${String(i)}`;
    state.entries.push({ kind: "tool", key: id, toolId: id });
    state.tools[id] = {
      id,
      name: call.name,
      input: call.input,
      parentId: null,
      diff: null,
      result:
        call.done === false
          ? null
          : { content: "", isError: false, truncated: false, originalBytes: null },
    };
  });
  return state;
}

const VERDICT = JSON.stringify({
  verdict: "needs_changes",
  summary: "True, but the command changed.",
  checks: [
    { name: "Verified", result: "fail", note: "Makefile:68 runs check-fast" },
    { name: "Non-obvious", result: "maybe" },
    { result: "pass" },
  ],
  target: "brain/learnings/gotchas/",
});

describe("parseReview", () => {
  it("reads the verdict, keeps named checks and drops brain/ from the target", () => {
    expect(parseReview(VERDICT)).toEqual({
      verdict: "needs_changes",
      summary: "True, but the command changed.",
      checks: [
        { name: "Verified", result: "fail", note: "Makefile:68 runs check-fast" },
        { name: "Non-obvious", result: "unknown", note: "" },
      ],
      target: "learnings/gotchas/",
    });
  });

  it("refuses text that is not a review", () => {
    expect(parseReview("not json")).toBeNull();
    expect(parseReview(JSON.stringify({ verdict: "maybe" }))).toBeNull();
    expect(parseReview("[]")).toBeNull();
  });
});

describe("reviewWrites", () => {
  it("returns the verdict and revision once both are written in the draft folder", () => {
    const state = transcriptOf([
      { name: "Write", input: { file_path: `${DIR}/note.md`, content: "# Fixed\n" } },
      { name: "Write", input: { file_path: `${DIR}/review.json`, content: VERDICT } },
      { name: "Write", input: { file_path: "/elsewhere/review.json", content: "{}" } },
    ]);

    const writes = reviewWrites(state, DRAFT);

    expect(writes.review?.verdict).toBe("needs_changes");
    expect(writes.revision).toBe("# Fixed\n");
    expect(writes.malformed).toBe(false);
  });

  it("waits for a write still running and flags a verdict it cannot read", () => {
    const running = transcriptOf([
      { name: "Write", input: { file_path: `${DIR}/review.json`, content: VERDICT }, done: false },
    ]);
    const broken = transcriptOf([
      { name: "Write", input: { file_path: `${DIR}/review.json`, content: "{" } },
    ]);

    expect(reviewWrites(running, DRAFT)).toEqual({
      review: null,
      malformed: false,
      revision: null,
    });
    expect(reviewWrites(broken, DRAFT).malformed).toBe(true);
  });
});

describe("reviewPrompt", () => {
  it("names the note, the bar, the draft folder and that the owner decides", () => {
    const prompt = reviewPrompt({
      project: "demo",
      notePath: "brain/_inbox/web-gates.md",
      draftId: DRAFT,
      targetChoices: ["learnings/", "playbooks/"],
      suggestedTarget: "learnings/",
    });

    expect(prompt).toContain("`brain/_inbox/web-gates.md` of project demo");
    expect(prompt).toContain("Not a duplicate");
    expect(prompt).toContain(`.hub-drafts/${DRAFT}/review.json`);
    expect(prompt).toContain("one of learnings/, playbooks/");
    expect(prompt).toContain("do not accept, reject, commit or push");
  });
});

describe("triagePrompt batch", () => {
  it("gives each learning its own draft folder and holds them to the /learn bar", () => {
    const prompt = triagePrompt({
      project: "tipple",
      batchId: "triage-abc123",
      items: [
        { learningId: "l-1", notePath: "brain/_inbox/a.md" },
        { learningId: "l-2", notePath: "brain/_inbox/b.md" },
      ],
    });

    expect(prompt).toContain("Triage the 2 proposed learnings of project tipple");
    expect(prompt).toContain("`brain/_inbox/a.md` → write in `.hub-drafts/triage-abc123/l-1/`");
    expect(prompt).toContain("`brain/_inbox/b.md` → write in `.hub-drafts/triage-abc123/l-2/`");
    expect(prompt).toContain("Hold it to the bar of the /learn skill");
    expect(triageDraftId("triage-abc123", "l-1")).toBe("triage-abc123/l-1");
  });
});
