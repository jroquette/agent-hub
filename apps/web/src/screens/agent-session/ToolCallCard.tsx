import { useId, useMemo, useRef, useState, type ReactNode } from "react";

import {
  Button,
  CopyButton,
  Icon,
  JsonViewer,
  TOOL_ICON,
  highlightable,
  useHighlight,
  type IconName,
} from "../../components";
import { cx } from "../../lib/cx";
import { useDiffSyntax } from "./diffSyntax";
import { StoredCopyLabel } from "./SessionStatus";
import {
  isRedacted,
  toolDiff,
  toolSummary,
  asArray,
  asObject,
  str,
  toolState,
  type PermissionView,
  type ToolResultView,
  type ToolState,
  type ToolView,
} from "./model";

/** Each state reads as an icon and a word, never colour alone (AC-234.24). */
export const TOOL_STATE: Record<ToolState, { icon: IconName; text: string }> = {
  running: { icon: "loader", text: "Running" },
  waiting: { icon: "hand", text: "Waiting for you" },
  done: { icon: "circle-check", text: "Done" },
  error: { icon: "circle-x", text: "Error" },
  denied: { icon: "shield-x", text: "Denied" },
};

type DiffKind = "head" | "hunk" | "add" | "del" | "ctx";

/** One line of a unified diff: its kind and, inside a hunk, its number in the old and new file. */
export interface DiffLine {
  kind: DiffKind;
  text: string;
  oldNo: number | null;
  newNo: number | null;
}

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

/** The lines of a unified diff, numbered from each hunk's header (`@@ -12,3 +12,4 @@`). */
export function diffLines(diff: string): DiffLine[] {
  let oldNo = 0;
  let newNo = 0;
  const text = diff.endsWith("\n") ? diff.slice(0, -1) : diff;
  return text.split("\n").map((line): DiffLine => {
    if (line.startsWith("+++") || line.startsWith("---"))
      return { kind: "head", text: line, oldNo: null, newNo: null };
    const hunk = HUNK.exec(line);
    if (hunk) {
      oldNo = Number(hunk[1]);
      newNo = Number(hunk[2]);
      return { kind: "hunk", text: line, oldNo: null, newNo: null };
    }
    if (line.startsWith("+")) return { kind: "add", text: line, oldNo: null, newNo: newNo++ };
    if (line.startsWith("-")) return { kind: "del", text: line, oldNo: oldNo++, newNo: null };
    if (line.startsWith(" ")) return { kind: "ctx", text: line, oldNo: oldNo++, newNo: newNo++ };
    // "... diff truncated", or a line outside any hunk.
    return { kind: "ctx", text: line, oldNo: null, newNo: null };
  });
}

/** A diff line's text as a pull request shows it: the sign in the line's colour, the code in
 * the syntax colours of its language (`code`, from `useDiffSyntax`) or plain. */
export function DiffLineText({
  line,
  code,
}: {
  line: DiffLine;
  code: ReactNode[] | null | undefined;
}) {
  if (!code) return <>{line.text}</>;
  return (
    <>
      <span className="as-diff-sign">{line.text.slice(0, 1)}</span>
      {code}
    </>
  );
}

/**
 * A unified diff as text (`<pre>`), each line tinted by its sign. `numbered`, for a diff with the
 * file's real line numbers, adds git's two gutters (old, new) and leaves the file headers out.
 * With the file's `path`, the code is coloured in its language.
 */
export function DiffText({
  diff,
  label,
  numbered = false,
  path,
}: {
  diff: string;
  label: string;
  numbered?: boolean;
  path?: string | undefined;
}) {
  const lines = useMemo(() => diffLines(diff), [diff]);
  const syntax = useDiffSyntax(lines, path);
  return (
    <pre
      className={cx("as-diff", numbered && "as-diff-numbered", syntax && "hljs as-diff-syntax")}
      // A diff can scroll sideways, so the keyboard must reach it.
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      aria-label={label}
    >
      {lines.map((line, i) =>
        numbered ? (
          line.kind === "head" ? null : (
            <span key={i} className={`as-diff-line as-diff-${line.kind}`}>
              <span className="as-diff-no" aria-hidden="true">
                {line.oldNo ?? ""}
              </span>
              <span className="as-diff-no" aria-hidden="true">
                {line.newNo ?? ""}
              </span>
              <span className="as-diff-code">
                <DiffLineText line={line} code={syntax?.[i]} />
                {"\n"}
              </span>
            </span>
          )
        ) : (
          <span key={i} className={`as-diff-${line.kind}`}>
            <DiffLineText line={line} code={syntax?.[i]} />
            {"\n"}
          </span>
        ),
      )}
    </pre>
  );
}

/** The text of a tool result: a string, or the `text` of its content blocks; null when neither. */
export function resultText(content: unknown): string | null {
  if (typeof content === "string") return content;
  const texts = asArray(content).flatMap((block) => {
    const text = asObject(block)?.text;
    return typeof text === "string" ? [text] : [];
  });
  return texts.length > 0 ? texts.join("\n") : null;
}

/** Output shown before "Show all", in characters (plan: inputs, bounds and budget). */
export const OUTPUT_SHOWN = 10_000;

/** The first `max` characters of `text` and how many it has, or null when it has no more.
 * Characters are code points, so an emoji counts once and is never cut in half. */
export function cutText(text: string, max: number): { shown: string; total: number } | null {
  if (text.length <= max) return null;
  let total = 0;
  let end = 0;
  for (const char of text) {
    if (total < max) end += char.length;
    total += 1;
  }
  return total > max ? { shown: text.slice(0, end), total } : null;
}

/** A result as text: its text, or its JSON when that is too long for the JSON viewer. */
function shownText(content: unknown): string | null {
  const text = resultText(content);
  if (text !== null) return text;
  const json = JSON.stringify(content, null, 2) as string | undefined;
  return json !== undefined && cutText(json, OUTPUT_SHOWN) ? json : null;
}

/** Text that is a JSON object or array (an MCP server's reply, often), parsed; else undefined. */
export function parsedJson(text: string): unknown {
  const trimmed = text.trim();
  const first = trimmed[0];
  if ((first !== "{" && first !== "[") || trimmed.length > MAX_JSON_CHARS) return undefined;
  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    return undefined;
  }
}
/** A longer JSON text stays as text: the viewer renders every node. */
const MAX_JSON_CHARS = 64 * 1024;

/** A line of grep/rg output: `path:line:text` (a match) or `path-line-text` (context, `-C`). */
const GREP_LINE = /^([^\s:][^:\n]*?)([:-])(\d+)([:-])(.*)$/;

/** True when most lines read as grep output, so their path and line number can be told apart. */
export function isGrepOutput(lines: readonly string[]): boolean {
  let total = 0;
  let matched = 0;
  for (const line of lines) {
    if (line === "" || line === "--") continue;
    total += 1;
    if (GREP_LINE.test(line)) matched += 1;
  }
  return total > 0 && matched / total >= 0.8;
}

function GrepText({ text }: { text: string }) {
  return text.split("\n").map((line, i) => {
    const match = GREP_LINE.exec(line);
    return (
      <span key={i}>
        {match ? (
          <>
            <span className="as-grep-path">{match[1]}</span>
            <span className="as-grep-sep">{match[2]}</span>
            <span className="as-grep-no">{match[3]}</span>
            <span className="as-grep-sep">{match[4]}</span>
            {match[5]}
          </>
        ) : (
          line
        )}
        {"\n"}
      </span>
    );
  });
}

function lineCount(text: string): number {
  if (text === "") return 0;
  const body = text.endsWith("\n") ? text.slice(0, -1) : text;
  return body.split("\n").length;
}

function ResultBody({ result }: { result: ToolResultView }) {
  const text = useMemo(() => shownText(result.content), [result.content]);
  // Only a text reply is parsed: structured content too long for the viewer stays text on purpose.
  const json = useMemo(() => {
    const reply = resultText(result.content);
    return reply === null || result.isError ? undefined : parsedJson(reply);
  }, [result.content, result.isError]);
  const [all, setAll] = useState(false);
  const pre = useRef<HTMLPreElement>(null);
  const cut = useMemo(() => (text === null ? null : cutText(text, OUTPUT_SHOWN)), [text]);
  const shown = text === null ? null : cut && !all ? cut.shown : text;
  const grep = useMemo(
    () => shown !== null && !result.isError && isGrepOutput(shown.split("\n")),
    [shown, result.isError],
  );
  const label = result.isError ? "Error" : "Result";
  return (
    <div className="as-tool-section">
      <div className="as-tool-label">
        {result.isError && <Icon name="circle-x" size="sm" />}
        {label}
        {json !== undefined && <span className="as-tool-meta"> · JSON</span>}
        {text !== null && text.trim() !== "" && json === undefined && (
          <span className="as-tool-meta">
            {" "}
            · {lineCount(text).toLocaleString("en-US")} {lineCount(text) === 1 ? "line" : "lines"}
          </span>
        )}
        {text !== null && isRedacted(text) && <StoredCopyLabel />}
        <span className="ah-grow" />
        {text !== null && text.trim() !== "" && (
          <CopyButton text={text} label={`Copy ${label.toLowerCase()}`} compact />
        )}
      </div>
      {text !== null && text.trim() === "" ? (
        <p className="ah-small ah-muted as-tool-empty">No output</p>
      ) : json !== undefined ? (
        <JsonViewer value={json} maxHeight={320} />
      ) : text !== null ? (
        <pre
          ref={pre}
          className={cx("as-pre", "as-pre-wrap", result.isError && "as-pre-error")}
          // A long output scrolls, so the keyboard must reach it.
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
          tabIndex={0}
          aria-label={result.isError ? "Error output" : "Result"}
        >
          {grep && shown !== null ? <GrepText text={shown} /> : shown}
        </pre>
      ) : (
        <JsonViewer value={result.content} maxHeight={240} />
      )}
      {cut && !all && json === undefined && (
        <Button
          size="sm"
          variant="ghost"
          className="as-show-all"
          onClick={() => {
            setAll(true);
            // The button goes away: the keyboard stays on the output it opened.
            pre.current?.focus({ preventScroll: true });
          }}
        >
          Show all ({cut.total.toLocaleString("en-US")} characters)
        </Button>
      )}
      {result.truncated && (
        <p className="ah-small ah-muted">
          Stored truncated
          {result.originalBytes !== null &&
            `: ${result.originalBytes.toLocaleString("en-US")} bytes in full`}
          .
        </p>
      )}
    </div>
  );
}

/** A shell command as a terminal line: `$`, then the command coloured as bash, wrapped. */
function CommandText({ command, description }: { command: string; description: string | null }) {
  const nodes = useHighlight(command, "bash", highlightable(command));
  return (
    <>
      {description && <p className="as-tool-description">{description}</p>}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <pre className="as-pre as-pre-wrap as-command" tabIndex={0} aria-label="Command">
        <span className="as-command-prompt" aria-hidden="true">
          ${" "}
        </span>
        <code className={nodes ? "hljs" : undefined}>{nodes ?? command}</code>
      </pre>
    </>
  );
}

function InputBody({ tool }: { tool: ToolView }) {
  // Claude's own report of the change, once it ran, carries the file's line numbers.
  const reported = tool.result?.diff ?? null;
  const diff = reported ?? toolDiff(tool);
  const command = typeof tool.input.command === "string" ? tool.input.command : null;
  const description =
    typeof tool.input.description === "string" && tool.input.description.trim() !== ""
      ? tool.input.description
      : null;
  return (
    <div className="as-tool-section">
      <div className="as-tool-label">
        {diff !== null ? "Diff" : command !== null ? "Command" : "Input"}
        <span className="ah-grow" />
        {diff === null && command !== null && (
          <CopyButton text={command} label="Copy command" compact />
        )}
      </div>
      {diff !== null ? (
        <DiffText
          diff={diff}
          label={`Diff of ${toolSummary(tool.input) || tool.name}`}
          numbered={reported !== null}
          path={str(tool.input, "file_path") ?? undefined}
        />
      ) : command !== null ? (
        <CommandText command={command} description={description} />
      ) : (
        <JsonViewer value={tool.input} maxHeight={240} />
      )}
    </div>
  );
}

export interface ToolCallCardProps {
  tool: ToolView;
  /** Every tool of the session, to render the calls a subagent made inside this one. */
  tools: Readonly<Record<string, ToolView>>;
  /** Tool ids by the calling tool's id. */
  calls: Readonly<Record<string, readonly string[]>>;
  defaultOpen?: boolean | undefined;
  /** The permission asked for this call, when one was. */
  request?: PermissionView | undefined;
  /** Every permission by request id (= the call's id): a subagent's call reads Waiting for you
   * while its permission is open; its card stays where it arrived. */
  requests?: Readonly<Record<string, PermissionView>> | undefined;
}

/** A collapsible tool call (D10): name, short input, status; input or diff and result on expand. */
export function ToolCallCard({
  tool,
  tools,
  calls,
  defaultOpen = false,
  request,
  requests,
}: ToolCallCardProps) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  const summary = toolSummary(tool.input);
  const icon: IconName = TOOL_ICON[tool.name] ?? (tool.name.startsWith("mcp__") ? "plug" : "box");
  const state = toolState(tool, request);
  const { icon: stateIcon, text: stateText } = TOOL_STATE[state];
  const nested = (calls[tool.id] ?? []).flatMap((id) => {
    const child = tools[id];
    return child ? [child] : [];
  });
  return (
    <div className={cx("as-tool", `as-tool-${state}`)}>
      <button
        type="button"
        className="as-tool-head"
        aria-expanded={open}
        aria-controls={open ? bodyId : undefined}
        aria-label={[tool.name, summary, `(${stateText})`].filter(Boolean).join(" ")}
        onClick={() => {
          setOpen((value) => !value);
        }}
      >
        <Icon name={open ? "chevron-down" : "chevron-right"} size="sm" />
        <Icon name={icon} size="sm" />
        <span className="as-tool-name">{tool.name}</span>
        {summary && <span className="as-tool-summary ah-mono">{summary}</span>}
        <span className="ah-grow" />
        <span className="as-tool-state ah-small">
          <Icon name={stateIcon} size="sm" data-icon={stateIcon} />
          {stateText}
        </span>
      </button>
      {open && (
        <div id={bodyId} className="as-tool-body">
          <InputBody tool={tool} />
          {tool.result !== null && <ResultBody result={tool.result} />}
        </div>
      )}
      {nested.length > 0 && (
        <ul className="as-tool-nested" aria-label={`Calls made by ${tool.name}`}>
          {nested.map((child) => (
            <li key={child.id}>
              <ToolCallCard
                tool={child}
                tools={tools}
                calls={calls}
                request={requests?.[child.id]}
                requests={requests}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
