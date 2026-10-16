import type { DiscussStarter, DiscussTarget } from "../../shell/discuss";

/** What makes a learning worth keeping: the /learn criteria the agents propose against. */
const CRITERIA =
  "Judge it by the /learn criteria: non-obvious (a competent agent reading the code would not infer it, and missing it causes a mistake), verified (backed by evidence: path:line, command output, a PR or ticket), and not a duplicate (search brain/ and each repo's AGENTS.md). Check its claims against the code in the sibling repos when you can.";

/** The first messages offered on a note of the brain, proposed or accepted. */
export const BRAIN_NOTE_STARTERS: readonly DiscussStarter[] = [
  {
    label: "Is this still true?",
    message:
      "Check this note against the current code and docs. Is it still true and useful to the agents? If not, propose an update or its removal, with the evidence.",
  },
  {
    label: "Improve the note",
    message:
      "Propose a better version of this note: a clearer title, a tighter body, the rule stated explicitly, the sources kept. Show me the change before editing the file.",
  },
  {
    label: "Duplicate or overlap?",
    message:
      "Search brain/ and the repos' AGENTS.md for this or something that overlaps. Is it a duplicate, or should it merge into an existing note?",
  },
];

const PROPOSAL_STARTERS: readonly DiscussStarter[] = [
  {
    label: "Is this worth keeping?",
    message:
      "Is this learning worth keeping in the brain? Check it against the criteria and the code, then give me one verdict, accept, accept with edits, or reject, and why.",
  },
  ...BRAIN_NOTE_STARTERS.slice(1),
];

export interface LearningForDiscuss {
  id: string;
  project: string;
  text: string;
  /** The note as the hub holds it now, relative to the hub folder; null when it is missing. */
  path: string | null;
  /** Where the agent recorded it (`brain/_inbox/…`), shown when the file is missing. */
  recordedPath: string | null;
  inBrain: boolean;
  /** The proposal waits for a decision here (accept or reject in the app). */
  proposed: boolean;
}

/** The Discuss panel's target for one learning: review it, improve it or drop it with Claude. */
export function learningDiscussTarget(l: LearningForDiscuss): DiscussTarget {
  const where = l.inBrain
    ? "It is already in the brain: it was accepted earlier. Help me judge whether it is still true and useful, or should be updated or removed."
    : l.proposed
      ? "An agent proposed it for the brain; it waits in brain/_inbox/ for my decision. Accepting or rejecting happens in the app, not here: give me your recommendation."
      : "It was decided earlier in the app.";
  const missing =
    l.path === null
      ? `Its note file is missing from the hub checkout${l.recordedPath ? ` (the agent recorded \`${l.recordedPath}\`)` : ""}: its title is all there is. Help me decide whether to write it again from the title and the code, or drop it.`
      : "When I ask for a change, edit the note file in place and keep its frontmatter.";
  return {
    key: `learning:${l.project}:${l.id}`,
    project: l.project,
    kind: "Learning",
    title: l.text,
    path: l.path,
    brief: [where, CRITERIA, missing].join("\n"),
    openOnArrive: l.proposed,
    starters: l.proposed ? PROPOSAL_STARTERS : BRAIN_NOTE_STARTERS,
  };
}
