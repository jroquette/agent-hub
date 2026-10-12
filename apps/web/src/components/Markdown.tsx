/**
 * The safe Markdown renderer of brain notes, feature records and learnings (AC-201.35, AC-201.36).
 *
 * In-house and small on purpose (no dependency): it builds React elements only, so raw HTML stays
 * text and no script or `on*` attribute can reach the page. Links go through `resolveBrainLink`:
 * notes of the same brain route inside the app (handed to `onBrainLink` when given), http(s) URLs
 * open in a new tab, paths leaving the brain and anything else render as plain text. Images render
 * as links, never as `<img>`. Inputs over the bounds render as text.
 */
import "./Markdown.css";

import type { MouseEvent, ReactNode } from "react";

import { anchorId, headingSlug, resolveBrainLink, type BrainLink } from "../lib/brainLinks";
import { cx } from "../lib/cx";

/** The largest note formatted; a larger one shows as plain text (the API's 256 KiB note bound). */
export const MAX_MARKDOWN_BYTES = 256 * 1024;
/** Lists nested deeper than this, and tables wider than MAX_TABLE_COLUMNS, render as text. */
export const MAX_LIST_DEPTH = 6;
export const MAX_TABLE_COLUMNS = 20;
const MAX_QUOTE_DEPTH = 6;
const MAX_INLINE_DEPTH = 8;
/** How far a link's label and destination may run before the `[` is taken as text. */
const LINK_WINDOW = 2000;

type Align = "left" | "center" | "right" | null;
type Block =
  | { t: "heading"; level: 1 | 2 | 3 | 4 | 5 | 6; text: string }
  | { t: "para"; text: string }
  | { t: "code"; lang: string; text: string }
  | { t: "quote"; blocks: Block[] }
  | { t: "list"; ordered: boolean; start: number; items: Block[][] }
  | { t: "table"; head: string[]; align: Align[]; rows: string[][] }
  | { t: "hr" }
  | { t: "text"; text: string };

type Inline =
  | { t: "text"; v: string }
  | { t: "code"; v: string }
  | { t: "strong" | "em" | "del"; c: Inline[] }
  | { t: "link"; href: string; c: Inline[] }
  | { t: "image"; src: string; alt: string };

interface Depth {
  list: number;
  quote: number;
}

/* ---------- Blocks ---------- */

const FENCE = /^ {0,3}(`{3,}|~{3,})[ \t]*([^`\s]*)/;
const HEADING = /^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$/;
const RULE = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
const ITEM = /^( *)([-*+]|\d{1,9}[.)])( +|$)(.*)$/;
const QUOTE = /^ {0,3}> ?(.*)$/;
const TABLE_RULE = /^ *\|? *:?-+:? *(\| *:?-+:? *)*\|? *$/;

const lead = (line: string) => line.length - line.trimStart().length;
const blank = (line: string) => line.trim() === "";

function startsBlock(line: string): boolean {
  return (
    FENCE.test(line) || HEADING.test(line) || RULE.test(line) || ITEM.test(line) || QUOTE.test(line)
  );
}

function startsTable(lines: string[], i: number): boolean {
  const next = lines[i + 1];
  return (
    (lines[i] ?? "").includes("|") &&
    next !== undefined &&
    next.includes("|") &&
    TABLE_RULE.test(next)
  );
}

function cellsOf(line: string): string[] {
  let row = line.trim();
  if (row.startsWith("|")) row = row.slice(1);
  if (row.endsWith("|") && !row.endsWith("\\|")) row = row.slice(0, -1);
  return row.split(/(?<!\\)\|/).map((cell) => cell.trim().replace(/\\\|/g, "|"));
}

function alignOf(cell: string): Align {
  const left = cell.startsWith(":");
  const right = cell.endsWith(":");
  if (left && right) return "center";
  if (right) return "right";
  return left ? "left" : null;
}

/** The list starting at `start`: its items' lines (children unindented) and where it ends. */
function listAt(lines: string[], start: number) {
  const first = ITEM.exec(lines[start] ?? "");
  const indent = first?.[1]?.length ?? 0;
  const ordered = /\d/.test(first?.[2] ?? "");
  const items: string[][] = [];
  let i = start;
  while (i < lines.length) {
    const item = ITEM.exec(lines[i] ?? "");
    if (!item || (item[1] ?? "").length !== indent || /\d/.test(item[2] ?? "") !== ordered) break;
    const content = indent + (item[2] ?? "").length + Math.max(1, (item[3] ?? "").length);
    const body = [item[4] ?? ""];
    i++;
    let afterBlank = false;
    while (i < lines.length) {
      const line = lines[i] ?? "";
      if (blank(line)) {
        let next = i;
        while (next < lines.length && blank(lines[next] ?? "")) next++;
        if (next >= lines.length || lead(lines[next] ?? "") <= indent) break;
        body.push("");
        i++;
        afterBlank = true;
        continue;
      }
      if (lead(line) > indent) {
        body.push(line.slice(Math.min(lead(line), content)));
      } else if (!afterBlank && !startsBlock(line)) {
        body.push(line.trim());
      } else break;
      afterBlank = false;
      i++;
    }
    items.push(body);
    if (i < lines.length && blank(lines[i] ?? "")) {
      let next = i;
      while (next < lines.length && blank(lines[next] ?? "")) next++;
      const sibling = ITEM.exec(lines[next] ?? "");
      if (sibling && (sibling[1] ?? "").length === indent) i = next;
    }
  }
  return { ordered, start: ordered ? Number.parseInt(first?.[2] ?? "1", 10) : 1, items, end: i };
}

function parseBlocks(lines: string[], depth: Depth): Block[] {
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    if (blank(line)) {
      i++;
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence) {
      const marker = fence[1] ?? "```";
      const body: string[] = [];
      i++;
      while (i < lines.length) {
        const close = lines[i] ?? "";
        const trimmed = close.trim();
        if (trimmed.startsWith(marker) && /^([`~])\1*$/.test(trimmed)) break;
        body.push(close);
        i++;
      }
      i++;
      blocks.push({ t: "code", lang: (fence[2] ?? "").slice(0, 40), text: body.join("\n") });
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      const level = Math.min(6, Math.max(1, (heading[1] ?? "#").length)) as 1 | 2 | 3 | 4 | 5 | 6;
      blocks.push({ t: "heading", level, text: heading[2] ?? "" });
      i++;
      continue;
    }
    if (RULE.test(line)) {
      blocks.push({ t: "hr" });
      i++;
      continue;
    }
    if (QUOTE.test(line)) {
      const raw: string[] = [];
      while (i < lines.length) {
        const current = lines[i] ?? "";
        if (QUOTE.test(current)) raw.push(current);
        else if (!blank(current) && raw.length > 0 && !startsBlock(current)) raw.push(current);
        else break;
        i++;
      }
      if (depth.quote >= MAX_QUOTE_DEPTH) blocks.push({ t: "text", text: raw.join("\n") });
      else {
        const inner = raw.map((current) => QUOTE.exec(current)?.[1] ?? current.trim());
        blocks.push({
          t: "quote",
          blocks: parseBlocks(inner, { ...depth, quote: depth.quote + 1 }),
        });
      }
      continue;
    }
    if (ITEM.test(line)) {
      const list = listAt(lines, i);
      if (depth.list >= MAX_LIST_DEPTH) {
        blocks.push({ t: "text", text: lines.slice(i, list.end).join("\n").trimEnd() });
      } else {
        const inner = { ...depth, list: depth.list + 1 };
        blocks.push({
          t: "list",
          ordered: list.ordered,
          start: list.start,
          items: list.items.map((item) => parseBlocks(item, inner)),
        });
      }
      i = list.end;
      continue;
    }
    if (startsTable(lines, i)) {
      const raw: string[] = [];
      while (i < lines.length && !blank(lines[i] ?? "") && (lines[i] ?? "").includes("|")) {
        raw.push(lines[i] ?? "");
        i++;
      }
      const head = cellsOf(raw[0] ?? "");
      if (head.length > MAX_TABLE_COLUMNS) blocks.push({ t: "text", text: raw.join("\n") });
      else {
        const align = cellsOf(raw[1] ?? "").map(alignOf);
        const rows = raw.slice(2).map((row) => head.map((_, column) => cellsOf(row)[column] ?? ""));
        blocks.push({ t: "table", head, align, rows });
      }
      continue;
    }
    const para: string[] = [];
    while (
      i < lines.length &&
      !blank(lines[i] ?? "") &&
      (para.length === 0 || (!startsBlock(lines[i] ?? "") && !startsTable(lines, i)))
    ) {
      para.push((lines[i] ?? "").trim());
      i++;
    }
    blocks.push({ t: "para", text: para.join(" ") });
  }
  return blocks;
}

/* ---------- Inlines ---------- */

const ESCAPABLE = /[!-/:-@[-`{-~]/;
const SPECIAL = /[\\`![*_~]/g;

/** `[label](destination "title")` at `start` (on the `[`), or null when it is not one. */
function linkAt(
  s: string,
  start: number,
  lastParen: number,
): { label: string; href: string; end: number } | null {
  const limit = Math.min(s.length, start + LINK_WINDOW, lastParen + 1);
  let nesting = 0;
  let close = -1;
  for (let j = start + 1; j < limit; j++) {
    const ch = s[j];
    if (ch === "\\") j++;
    else if (ch === "[") nesting++;
    else if (ch === "]") {
      if (nesting === 0) {
        close = j;
        break;
      }
      nesting--;
    }
  }
  if (close === -1 || s[close + 1] !== "(") return null;
  let j = close + 2;
  while (s[j] === " ") j++;
  let href = "";
  if (s[j] === "<") {
    const end = s.indexOf(">", j);
    if (end === -1 || end > limit) return null;
    href = s.slice(j + 1, end);
    j = end + 1;
  } else {
    let parens = 0;
    const from = j;
    while (j < limit) {
      const ch = s[j] ?? "";
      if (ch === "(") parens++;
      else if (ch === ")") {
        if (parens === 0) break;
        parens--;
      } else if (/\s/.test(ch)) break;
      j++;
    }
    href = s.slice(from, j);
  }
  while (s[j] === " ") j++;
  const quote = s[j];
  if (quote === '"' || quote === "'") {
    const end = s.indexOf(quote, j + 1);
    if (end === -1 || end > limit) return null;
    j = end + 1;
    while (s[j] === " ") j++;
  }
  if (s[j] !== ")") return null;
  return { label: s.slice(start + 1, close), href, end: j + 1 };
}

const wordChar = (ch: string | undefined) => ch !== undefined && /[\p{L}\p{N}]/u.test(ch);
const space = (ch: string | undefined) => ch === undefined || /\s/.test(ch);

function parseInline(s: string, depth: number, links = true): Inline[] {
  const out: Inline[] = [];
  let text = "";
  const flush = () => {
    if (text) out.push({ t: "text", v: text });
    text = "";
  };
  // Bounds the work on hostile input: a delimiter known absent after a point is never searched again.
  const absent = new Set<string>();
  const find = (delim: string, from: number) => {
    if (absent.has(delim)) return -1;
    const at = s.indexOf(delim, from);
    if (at === -1) absent.add(delim);
    return at;
  };
  const lastParen = s.lastIndexOf(")");
  let i = 0;
  while (i < s.length) {
    SPECIAL.lastIndex = i;
    const next = SPECIAL.exec(s)?.index ?? s.length;
    if (next > i) {
      text += s.slice(i, next);
      i = next;
      continue;
    }
    const ch = s[i] ?? "";
    if (ch === "\\" && ESCAPABLE.test(s[i + 1] ?? "")) {
      text += s[i + 1] ?? "";
      i += 2;
      continue;
    }
    if (ch === "`") {
      let run = 1;
      while (s[i + run] === "`") run++;
      const ticks = "`".repeat(run);
      let close = find(ticks, i + run);
      while (close !== -1 && s[close + run] === "`") {
        let after = close;
        while (s[after] === "`") after++;
        close = s.indexOf(ticks, after);
      }
      if (close === -1) {
        text += ticks;
        i += run;
        continue;
      }
      flush();
      let code = s.slice(i + run, close);
      if (code.length > 2 && code.startsWith(" ") && code.endsWith(" ")) code = code.slice(1, -1);
      out.push({ t: "code", v: code });
      i = close + run;
      continue;
    }
    if ((ch === "!" && s[i + 1] === "[") || (ch === "[" && links)) {
      const at = ch === "!" ? i + 1 : i;
      const link =
        depth < MAX_INLINE_DEPTH && find("](", at) !== -1 ? linkAt(s, at, lastParen) : null;
      if (link) {
        flush();
        if (ch === "!")
          out.push({
            t: "image",
            src: link.href,
            alt: plainText(parseInline(link.label, depth + 1, false)),
          });
        else out.push({ t: "link", href: link.href, c: parseInline(link.label, depth + 1, false) });
        i = link.end;
        continue;
      }
      text += ch;
      i++;
      continue;
    }
    if (ch === "*" || ch === "_" || ch === "~") {
      let run = 1;
      while (s[i + run] === ch) run++;
      const size = ch === "~" ? 2 : Math.min(run, 2);
      const delim = ch.repeat(size);
      const open =
        (ch !== "~" || run >= 2) && !space(s[i + size]) && !(ch === "_" && wordChar(s[i - 1]));
      const close = open && depth < MAX_INLINE_DEPTH ? find(delim, i + size + 1) : -1;
      if (close !== -1 && !space(s[close - 1]) && !(ch === "_" && wordChar(s[close + size]))) {
        flush();
        const kind = ch === "~" ? "del" : size === 2 ? "strong" : "em";
        out.push({ t: kind, c: parseInline(s.slice(i + size, close), depth + 1, links) });
        i = close + size;
        continue;
      }
      text += s.slice(i, i + run);
      i += run;
      continue;
    }
    text += ch;
    i++;
  }
  flush();
  return out;
}

function plainText(nodes: Inline[]): string {
  return nodes
    .map((node) => {
      switch (node.t) {
        case "text":
        case "code":
          return node.v;
        case "image":
          return node.alt;
        default:
          return plainText(node.c);
      }
    })
    .join("");
}

/* ---------- Rendering ---------- */

/** Where the note lives: its relative links resolve against this brain-relative path. */
export interface NotePlace {
  project: string;
  path: string;
}

export interface MarkdownProps {
  source: string;
  note?: NotePlace | undefined;
  /** Opens a note of the same brain in the app; without it the link is a plain in-app href. */
  onBrainLink?: ((link: Extract<BrainLink, { kind: "brain" }>) => void) | undefined;
  className?: string | undefined;
}

interface Ctx {
  note: NotePlace | undefined;
  onBrainLink: MarkdownProps["onBrainLink"];
  ids: Map<string, number>;
}

const NEW_TAB = "(opens in a new tab)";

function linkNode(href: string, children: ReactNode, key: number, ctx: Ctx): ReactNode {
  const link = resolveBrainLink(href, ctx.note?.path ?? null, ctx.note?.project ?? null);
  switch (link.kind) {
    case "external":
      return (
        <a key={key} href={link.href} target="_blank" rel="noopener noreferrer">
          {children} <span className="ah-sr">{NEW_TAB}</span>
        </a>
      );
    case "brain": {
      const open = ctx.onBrainLink;
      return (
        <a
          key={key}
          href={link.route}
          onClick={(event: MouseEvent<HTMLAnchorElement>) => {
            if (
              !open ||
              event.button !== 0 ||
              event.metaKey ||
              event.ctrlKey ||
              event.shiftKey ||
              event.altKey
            )
              return;
            event.preventDefault();
            open(link);
          }}
        >
          {children}
        </a>
      );
    }
    case "outside":
      return (
        <span key={key} className="ah-md-outside" title={link.title}>
          {children}
        </span>
      );
    case "text":
      return (
        <span key={key} title={link.title}>
          {children}
        </span>
      );
  }
}

function renderInline(nodes: Inline[], ctx: Ctx): ReactNode[] {
  return nodes.map((node, key) => {
    switch (node.t) {
      case "text":
        return node.v;
      case "code":
        return <code key={key}>{node.v}</code>;
      case "strong":
        return <strong key={key}>{renderInline(node.c, ctx)}</strong>;
      case "em":
        return <em key={key}>{renderInline(node.c, ctx)}</em>;
      case "del":
        return <del key={key}>{renderInline(node.c, ctx)}</del>;
      case "link":
        return linkNode(node.href, renderInline(node.c, ctx), key, ctx);
      case "image":
        return linkNode(node.src, `Image: ${node.alt || node.src}`, key, ctx);
    }
  });
}

function headingId(text: string, ctx: Ctx): string | undefined {
  const slug = headingSlug(text);
  if (!slug) return undefined;
  const seen = ctx.ids.get(slug) ?? 0;
  ctx.ids.set(slug, seen + 1);
  return anchorId(seen === 0 ? slug : `${slug}-${String(seen)}`);
}

const HEADINGS = { 1: "h1", 2: "h2", 3: "h3", 4: "h4", 5: "h5", 6: "h6" } as const;

function renderBlock(block: Block, key: number, ctx: Ctx, tight = false): ReactNode {
  switch (block.t) {
    case "heading": {
      const Tag = HEADINGS[block.level];
      const nodes = parseInline(block.text, 0);
      return (
        <Tag key={key} id={headingId(plainText(nodes), ctx)}>
          {renderInline(nodes, ctx)}
        </Tag>
      );
    }
    case "para":
      return tight ? (
        renderInline(parseInline(block.text, 0), ctx)
      ) : (
        <p key={key}>{renderInline(parseInline(block.text, 0), ctx)}</p>
      );
    case "code":
      return (
        <pre key={key} className="ah-md-pre">
          <code data-lang={block.lang || undefined}>{block.text}</code>
        </pre>
      );
    case "quote":
      return (
        <blockquote key={key}>
          {block.blocks.map((inner, i) => renderBlock(inner, i, ctx))}
        </blockquote>
      );
    case "list": {
      const items = block.items.map((item, i) => (
        <li key={i}>{item.map((inner, j) => renderBlock(inner, j, ctx, j === 0))}</li>
      ));
      return block.ordered ? (
        <ol key={key} start={block.start === 1 ? undefined : block.start}>
          {items}
        </ol>
      ) : (
        <ul key={key}>{items}</ul>
      );
    }
    case "table":
      return (
        <div key={key} className="ah-md-table">
          <table className="ah-table">
            <thead>
              <tr>
                {block.head.map((cell, i) => (
                  <th key={i} scope="col" style={{ textAlign: block.align[i] ?? undefined }}>
                    {renderInline(parseInline(cell, 0), ctx)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <td key={j} style={{ textAlign: block.align[j] ?? undefined }}>
                      {renderInline(parseInline(cell, 0), ctx)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "hr":
      return <hr key={key} />;
    case "text":
      return (
        <div key={key} className="ah-md-text">
          {block.text}
        </div>
      );
  }
}

/** Renders a Markdown note safely; see the module comment for what is and is not rendered. */
export function Markdown({ source, note, onBrainLink, className }: MarkdownProps) {
  if (new TextEncoder().encode(source).length > MAX_MARKDOWN_BYTES) {
    return (
      <div className={cx("ah-md", className)}>
        <p className="ah-small ah-muted">
          This note is too large to format (over 256 KiB): its start is shown as plain text.
        </p>
        <pre className="ah-md-pre">{source.slice(0, MAX_MARKDOWN_BYTES)}</pre>
      </div>
    );
  }
  const lines = source.replace(/\r\n?/g, "\n").replace(/\t/g, "    ").split("\n");
  const ctx: Ctx = { note, onBrainLink, ids: new Map() };
  return (
    <div className={cx("ah-md", className)}>
      {parseBlocks(lines, { list: 0, quote: 0 }).map((block, key) => renderBlock(block, key, ctx))}
    </div>
  );
}
