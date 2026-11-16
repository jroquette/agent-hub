/* The open questions of a feature record, read from its `## Open questions` section. */

export interface OpenQuestion {
  /** `Q1` (or `Q-1` as written); `Q<n>` by position when the item names no id. */
  id: string;
  /** The bold lead, else the first sentence, without its final period or colon. */
  title: string;
  /** The rest of the item, as markdown on one line. */
  body: string;
  /** What the record assumes or recommends, up to the end of that sentence; else null. */
  recommendation: string | null;
  /** The answers the record offers, from the item's nested list; none when it lists none. */
  options: QuestionOption[];
}

/** One answer a record offers to an open question (a nested list item under the question). */
export interface QuestionOption {
  label: string;
  description: string | null;
  /** Marked "(recommended)" in the record. */
  recommended: boolean;
}

const SECTION = /^##\s+open questions\s*$/i;
const ITEM = /^[-*]\s+/;
/** A nested list item under a question: one of its options. */
const OPTION_ITEM = /^\s+[-*]\s+/;
/** `**Label** (recommended): description` (the bold, the mark and the description optional). */
const OPTION_BOLD = /^\*\*(.+?)\*\*\s*(\(recommended\))?\s*(?:[:\u2014\u2013-]\s*)?(.*)$/i;
const OPTION_MARK = /\s*\(recommended\)/i;
/** `**Q-1 (title):** …` */
const BOLD_ID = /^\*\*(Q-?\d+)\s*\(([^)]+)\)\s*[.:]?\*\*\s*/;
/** `Q1. …` or `**Q1.** …` */
const ID = /^(?:\*\*)?(Q-?\d+)[.:)]?(?:\*\*)?\s+/;
const TITLE = /^\*\*(.+?)\*\*\s*/;
const LEAD = /(?:recommended|recommendation|default|assumed|proposed)\s*:\s*|\b[\w-]+ assumes:\s*/i;
const MAX_TITLE = 90;
const MAX_RECOMMENDATION = 240;

/** The record's open questions, in order; none when it has no `## Open questions` section. */
export function openQuestions(markdown: string): OpenQuestion[] {
  const lines = markdown.split(/\r?\n/);
  const start = lines.findIndex((line) => SECTION.test(line.trim()));
  if (start < 0) return [];
  const items: { text: string; options: string[] }[] = [];
  let inItem = false;
  for (const line of lines.slice(start + 1)) {
    if (/^#{1,2}\s/.test(line)) break;
    const last = items[items.length - 1];
    if (ITEM.test(line)) {
      items.push({ text: line.replace(ITEM, ""), options: [] });
      inItem = true;
    } else if (inItem && last && OPTION_ITEM.test(line)) {
      last.options.push(line.replace(OPTION_ITEM, ""));
    } else if (inItem && last && /^\s+\S/.test(line)) {
      // A wrapped line continues the last option, else the question.
      const option = last.options.length - 1;
      if (option >= 0) {
        last.options[option] = `${last.options[option] ?? ""} ${line.trim()}`;
      } else {
        last.text = `${last.text} ${line.trim()}`;
      }
    } else {
      inItem = false; // A paragraph between items is not part of a question.
    }
  }
  return items
    .map((item) => ({ ...item, text: item.text.trim() }))
    .filter(({ text }) => !/^none open\b/i.test(text) && !/\(resolved\b/i.test(text))
    .map((item, index) => withOptions(parseItem(item.text, index), item.options));
}

function withOptions(
  question: Omit<OpenQuestion, "options">,
  lines: readonly string[],
): OpenQuestion {
  const options = lines.map(parseOption).filter((option) => option.label);
  const recommended = options.find((option) => option.recommended);
  return {
    ...question,
    options,
    // An option marked recommended is the recommendation when the prose names none.
    recommendation: question.recommendation ?? recommended?.label ?? null,
  };
}

function parseOption(line: string): QuestionOption {
  const text = line.trim();
  const bold = OPTION_BOLD.exec(text);
  if (bold) {
    const [, label = "", mark, rest = ""] = bold;
    const restMarked = OPTION_MARK.test(rest);
    const description = rest
      .replace(OPTION_MARK, "")
      .replace(/^[:\u2014\u2013-]\s*/, "")
      .trim();
    return {
      label: label.replace(OPTION_MARK, "").trim(),
      description: description || null,
      recommended: Boolean(mark) || OPTION_MARK.test(label) || restMarked,
    };
  }
  const recommended = OPTION_MARK.test(text);
  const plain = text.replace(OPTION_MARK, "");
  const split = /\s+[\u2014\u2013]\s+|:\s+/.exec(plain);
  return {
    label: (split ? plain.slice(0, split.index) : plain).trim(),
    description: split ? plain.slice(split.index + split[0].length).trim() || null : null,
    recommended,
  };
}

function parseItem(item: string, index: number): Omit<OpenQuestion, "options"> {
  let rest = item;
  let id: string | undefined;
  let title: string | undefined;
  const boldId = BOLD_ID.exec(rest);
  if (boldId) {
    [, id, title] = boldId;
    rest = rest.slice(boldId[0].length);
  } else {
    const plainId = ID.exec(rest);
    if (plainId) {
      id = plainId[1];
      rest = rest.slice(plainId[0].length);
    }
    const bold = TITLE.exec(rest);
    if (bold) {
      title = bold[1];
      rest = rest.slice(bold[0].length);
    }
  }
  return {
    id: id ?? `Q${String(index + 1)}`,
    title: clip((title ?? firstSentence(rest)).replace(/[.:]$/, ""), MAX_TITLE),
    body: rest.trim(),
    recommendation: recommendationOf(rest),
  };
}

function firstSentence(text: string): string {
  return /^.*?[.?!](?=\s|$)/.exec(text)?.[0] ?? text;
}

function clip(text: string, max: number): string {
  const line = text.trim();
  return line.length > max ? `${line.slice(0, max - 1).trimEnd()}…` : line;
}

/** A sentence that marks itself "(assumed)": the sentence, without the mark. */
function markedSentence(text: string): string | null {
  const sentences = text.split(/(?<=[.?!])\s+(?=[A-Z])/);
  const marked = sentences.find((sentence) => /\(assumed\)/i.test(sentence));
  return marked ? marked.replace(/\s*\(assumed\)/i, "").trim() : null;
}

function recommendationOf(text: string): string | null {
  const lead = LEAD.exec(text);
  if (!lead) {
    const marked = markedSentence(text);
    return marked ? clip(marked, MAX_RECOMMENDATION) : null;
  }
  if (/\bnot\s+$/i.test(text.slice(0, lead.index))) return null;
  const after = text.slice(lead.index + lead[0].length);
  // Up to the end of its sentence: a period that is not inside a code span or a parenthesis.
  let depth = 0;
  let code = false;
  let end = after.length;
  for (let i = 0; i < after.length; i += 1) {
    const c = after[i];
    if (c === "`") code = !code;
    else if (!code && c === "(") depth += 1;
    else if (!code && c === ")") depth = Math.max(0, depth - 1);
    else if (
      !code &&
      depth === 0 &&
      c === "." &&
      (i + 1 === after.length || after[i + 1] === " ")
    ) {
      end = i + 1;
      break;
    }
  }
  const sentence = after.slice(0, end).trim();
  return sentence ? clip(sentence, MAX_RECOMMENDATION) : null;
}

/** One answer per question id; blank means "take the recommendation" (or Claude's own call). */
export type Answers = Readonly<Record<string, string>>;

/** How a question will be answered when the approval is sent. */
export type Outcome = "answered" | "recommended" | "claude";

export function outcomeOf(question: OpenQuestion, answers: Answers): Outcome {
  if ((answers[question.id] ?? "").trim()) return "answered";
  return question.recommendation ? "recommended" : "claude";
}

/** "1 answered · 3 take the recommendation · 9 left to Claude", zero parts dropped. */
export function countLine(questions: readonly OpenQuestion[], answers: Answers): string {
  const count = (outcome: Outcome) =>
    questions.filter((q) => outcomeOf(q, answers) === outcome).length;
  const answered = count("answered");
  const recommended = count("recommended");
  const claude = count("claude");
  if (answered === 0 && claude === 0) return "No answers: every question takes the recommendation.";
  return [
    answered ? `${String(answered)} answered` : "No answers yet",
    recommended
      ? `${String(recommended)} take${recommended === 1 ? "s" : ""} the recommendation`
      : "",
    claude ? `${String(claude)} left to Claude` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * The questions the owner answers: the summary's, written in plain words with their context, when
 * it names every question the record has (same ids); else the record's own, so none goes missing.
 */
export function questionsToShow(
  record: readonly OpenQuestion[],
  summary: readonly OpenQuestion[] | null,
): readonly OpenQuestion[] {
  if (!summary || summary.length === 0) return record;
  const ids = new Set(summary.map((q) => q.id));
  return record.every((q) => ids.has(q.id)) ? summary : record;
}

/** The approval message; with open questions, each one's answer or what a blank answer means. */
export function approvalMessage(
  record: string,
  path: string,
  questions: readonly OpenQuestion[] = [],
  answers: Answers = {},
): string {
  if (questions.length === 0) {
    return [
      `I approve the ${record} (\`${path}\`) as it is now.`,
      "Treat it as approved and go on with the next step of the feature.",
    ].join(" ");
  }
  const lines = questions.map((q) => {
    const name = `${q.id} (${q.title})`;
    const outcome = outcomeOf(q, answers);
    if (outcome === "answered") {
      const [first = "", ...more] = (answers[q.id] ?? "").trim().split(/\r?\n/);
      return [`- ${name}: ${first}`, ...more.map((line) => `  ${line}`)].join("\n");
    }
    return outcome === "recommended"
      ? `- ${name}: accept the recommendation.`
      : `- ${name}: no answer, use your own recommendation.`;
  });
  return [
    `I approve the ${record} (\`${path}\`) as it is now, with these answers to its open questions:`,
    ...lines,
    `Record the answers in the ${record}, then go on with the next step of the feature.`,
  ].join("\n");
}
