import { useId, useState } from "react";

import { Icon, JsonViewer, TOOL_ICON, type IconName } from "../../components";
import { cx } from "../../lib/cx";
import { StoredCopyLabel } from "./SessionStatus";
import {
  isRedacted,
  toolDiff,
  toolSummary,
  asArray,
  asObject,
  type ToolResultView,
  type ToolView,
} from "./transcript";

/** A unified diff as text (`<pre>`), each line tinted by its sign. */
export function DiffText({ diff, label }: { diff: string; label: string }) {
  return (
    // A diff can scroll sideways, so the keyboard must reach it.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
    <pre className="as-diff" tabIndex={0} aria-label={label}>
      {diff.split("\n").map((line, i) => {
        const kind =
          line.startsWith("+++") || line.startsWith("---")
            ? "head"
            : line.startsWith("@@")
              ? "hunk"
              : line.startsWith("+")
                ? "add"
                : line.startsWith("-")
                  ? "del"
                  : "ctx";
        return (
          <span key={i} className={`as-diff-${kind}`}>
            {line}
            {"\n"}
          </span>
        );
      })}
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

function ResultBody({ result }: { result: ToolResultView }) {
  const text = resultText(result.content);
  return (
    <div className="as-tool-section">
      <div className="as-tool-label">
        {result.isError ? "Error" : "Result"}
        {text !== null && isRedacted(text) && <StoredCopyLabel />}
      </div>
      {text !== null ? (
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        <pre className={cx("as-pre", result.isError && "as-pre-error")} tabIndex={0}>
          {text}
        </pre>
      ) : (
        <JsonViewer value={result.content} maxHeight={240} />
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

function InputBody({ tool }: { tool: ToolView }) {
  const diff = toolDiff(tool);
  const command = typeof tool.input.command === "string" ? tool.input.command : null;
  return (
    <div className="as-tool-section">
      <div className="as-tool-label">{diff !== null ? "Diff" : "Input"}</div>
      {diff !== null ? (
        <DiffText diff={diff} label={`Diff of ${toolSummary(tool.input) || tool.name}`} />
      ) : command !== null ? (
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        <pre className="as-pre" tabIndex={0}>
          {command}
        </pre>
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
}

/** A collapsible tool call (D10): name, short input, status; input or diff and result on expand. */
export function ToolCallCard({ tool, tools, calls, defaultOpen = false }: ToolCallCardProps) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  const summary = toolSummary(tool.input);
  const icon: IconName = TOOL_ICON[tool.name] ?? (tool.name.startsWith("mcp__") ? "plug" : "box");
  const state = tool.result === null ? "running" : tool.result.isError ? "error" : "done";
  const stateText = state === "running" ? "Running" : state === "error" ? "Error" : "Done";
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
        <span className="as-tool-state ah-small">{stateText}</span>
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
              <ToolCallCard tool={child} tools={tools} calls={calls} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
