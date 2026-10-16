/* The Studio's draft (create a skill, agent or hook with Claude): the files Claude writes into a
 * draft folder of the hub, rebuilt from the session's Write and Edit calls, and what they read as. */
import type { components } from "../../api/schema";
import type { JsonObject, TranscriptState } from "../agent-session/model";
import type { ItemKind, Mode } from "./filters";

type Schemas = components["schemas"];
type CatalogItem = Schemas["CatalogItem"];
type FrontmatterPair = Schemas["FrontmatterPair"];

/** Where drafts live in the hub folder: outside `plugin/` and `.claude/`, so nothing loads them. */
export const DRAFTS_DIR = ".hub-drafts";
/** The name rule the catalog addresses items by (`ITEM_NAME` on the server), kebab-case advised. */
export const NAME_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;
const KEBAB = /^[a-z0-9]+(-[a-z0-9]+)*$/;
/** Claude Code reads only so much of a description when it picks a skill (advice, not a limit). */
export const DESCRIPTION_ADVISED_CHARS = 1024;

/** The frontmatter keys Claude Code understands, as the server lists them (`KNOWN_*_KEYS`). */
const KNOWN_KEYS: Record<"skill" | "agent", ReadonlySet<string>> = {
  skill: new Set([
    "name",
    "description",
    "when_to_use",
    "argument-hint",
    "arguments",
    "disable-model-invocation",
    "user-invocable",
    "allowed-tools",
    "disallowed-tools",
    "model",
    "effort",
    "context",
    "agent",
    "background",
    "hooks",
    "paths",
    "shell",
    "metadata",
    "license",
    "compatibility",
  ]),
  agent: new Set([
    "name",
    "description",
    "tools",
    "model",
    "skills",
    "hooks",
    "memory",
    "background",
    "effort",
    "isolation",
    "color",
  ]),
};

/** A new draft's id: the kind, then a short random suffix (a folder name, so URL-safe). */
export function newDraftId(kind: ItemKind, random: () => number = Math.random): string {
  const suffix = Math.floor(random() * 36 ** 6)
    .toString(36)
    .padStart(6, "0");
  return `${kind}-${suffix}`;
}

/** The kind a draft id names, or null for an id this app did not issue. */
export function draftKind(draftId: string): ItemKind | null {
  const match = /^(skill|agent|hook)-[a-z0-9]{1,12}$/.exec(draftId);
  return match ? (match[1] as ItemKind) : null;
}

export function draftDir(draftId: string): string {
  return `${DRAFTS_DIR}/${draftId}`;
}

export interface DraftFile {
  /** Relative to the draft folder: `SKILL.md`, `references/api.md`… */
  path: string;
  content: string;
  /** An Edit was applied to a file this session never wrote whole: the text is only the edits. */
  partial: boolean;
  /** Its last write has not finished (or is waiting for a permission answer). */
  pending: boolean;
}

export interface DraftWrites {
  files: DraftFile[];
  /** Files Claude wrote or edited outside the draft folder, as it named them. */
  outside: string[];
}

function text(input: JsonObject, key: string): string | null {
  const value = input[key];
  return typeof value === "string" ? value : null;
}

/** The path inside the draft folder `file_path` names, or null when it is elsewhere. */
export function insideDraft(filePath: string, draftId: string): string | null {
  const dir = `${draftDir(draftId)}/`;
  const normal = filePath.replace(/\\/g, "/");
  const at = normal.startsWith(dir) ? 0 : normal.indexOf(`/${dir}`);
  if (at < 0) return null;
  const rest = normal.slice(at + (at === 0 ? 0 : 1) + dir.length);
  if (rest === "" || rest.split("/").some((part) => part === ".." || part === "")) return null;
  return rest;
}

function replaceText(content: string, before: string, after: string, all: boolean): string {
  if (before === "") return content;
  return all ? content.split(before).join(after) : content.replace(before, () => after);
}

/**
 * The draft as the session wrote it: each Write sets a file, each Edit or MultiEdit replaces text
 * in it, in transcript order. A failed or denied call changes nothing.
 */
export function draftWrites(state: TranscriptState, draftId: string): DraftWrites {
  const files = new Map<string, DraftFile>();
  const outside = new Set<string>();
  for (const entry of state.entries) {
    if (entry.kind !== "tool") continue;
    const tool = state.tools[entry.toolId];
    if (!tool || !["Write", "Edit", "MultiEdit"].includes(tool.name)) continue;
    if (tool.result?.isError) continue;
    const filePath = text(tool.input, "file_path");
    if (filePath === null) continue;
    const path = insideDraft(filePath, draftId);
    if (path === null) {
      outside.add(filePath);
      continue;
    }
    const pending = tool.result === null;
    const known = files.get(path);
    if (tool.name === "Write") {
      files.set(path, {
        path,
        content: text(tool.input, "content") ?? "",
        partial: false,
        pending,
      });
      continue;
    }
    const edits =
      tool.name === "Edit"
        ? [tool.input]
        : (Array.isArray(tool.input.edits) ? tool.input.edits : []).filter(
            (edit): edit is JsonObject => typeof edit === "object" && edit !== null,
          );
    let content = known?.content ?? "";
    for (const edit of edits) {
      const before = text(edit, "old_string") ?? "";
      const after = text(edit, "new_string") ?? "";
      content = known
        ? replaceText(content, before, after, edit.replace_all === true)
        : `${content}${after}\n`;
    }
    files.set(path, { path, content, partial: known ? known.partial : true, pending });
  }
  return {
    files: [...files.values()].sort(
      (a, b) => fileOrder(a.path) - fileOrder(b.path) || (a.path < b.path ? -1 : 1),
    ),
    outside: [...outside],
  };
}

function fileOrder(path: string): number {
  if (path === "SKILL.md" || path === "hooks.json") return 0;
  if (!path.includes("/") && path.endsWith(".md")) return 1;
  return 2;
}

/* ---------- Frontmatter ---------- */

export interface ReadDocument {
  pairs: FrontmatterPair[];
  body: string;
  /** The file starts with `---` but the block does not close. */
  unclosed: boolean;
}

function unquote(value: string): string {
  const v = value.trim();
  if (
    v.length >= 2 &&
    ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'")))
  ) {
    return v.slice(1, -1);
  }
  return v;
}

/**
 * A light read of a Markdown file's YAML frontmatter for the preview: top-level `key: value`,
 * `|` and `>` blocks, `- item` lists and `[a, b]` lists. The server's reader stays the reference
 * once the item is published.
 */
export function readDocument(source: string, kind: "skill" | "agent"): ReadDocument {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  if (lines[0]?.trim() !== "---") return { pairs: [], body: source, unclosed: false };
  const end = lines.findIndex((line, i) => i > 0 && line.trim() === "---");
  if (end < 0) return { pairs: [], body: source, unclosed: true };
  const pairs: FrontmatterPair[] = [];
  const known = KNOWN_KEYS[kind];
  let i = 1;
  while (i < end) {
    const line = lines[i] ?? "";
    const match = /^([A-Za-z0-9_-]+):\s*(.*)$/.exec(line);
    i += 1;
    if (!match) continue;
    const key = match[1] ?? "";
    const rest = (match[2] ?? "").trim();
    const nested: string[] = [];
    while (i < end && /^(\s+|$)/.test(lines[i] ?? "") && (lines[i] ?? "").trim() !== "---") {
      nested.push(lines[i] ?? "");
      i += 1;
    }
    let value: FrontmatterPair["value"];
    if (rest === "|" || rest === ">" || rest === "|-" || rest === ">-") {
      const block = nested.map((l) => l.trim());
      value = rest.startsWith("|")
        ? block.join("\n").trim()
        : block.join(" ").replace(/\s+/g, " ").trim();
    } else if (rest === "" && nested.some((l) => l.trim().startsWith("- "))) {
      value = nested
        .filter((l) => l.trim().startsWith("- "))
        .map((l) => unquote(l.trim().slice(2)));
    } else if (rest.startsWith("[") && rest.endsWith("]")) {
      value = rest
        .slice(1, -1)
        .split(",")
        .map(unquote)
        .filter((v) => v !== "");
    } else {
      value = [unquote(rest), ...nested.map((l) => l.trim())].filter((v) => v !== "").join(" ");
    }
    pairs.push({ key, value, known: known.has(key) });
  }
  return {
    pairs,
    body: lines
      .slice(end + 1)
      .join("\n")
      .replace(/^\n+/, ""),
    unclosed: false,
  };
}

function pairText(pairs: readonly FrontmatterPair[], key: string): string | null {
  const value = pairs.find((pair) => pair.key === key)?.value;
  if (typeof value === "string") return value === "" ? null : value;
  if (Array.isArray(value)) return value.join(", ");
  return null;
}

/** Who can invoke a skill, from its two frontmatter flags (as the server derives it). */
export function skillMode(pairs: readonly FrontmatterPair[]): Mode {
  const noModel = pairText(pairs, "disable-model-invocation") === "true";
  const noUser = pairText(pairs, "user-invocable") === "false";
  if (noModel && noUser) return "neither";
  if (noModel) return "user-only";
  if (noUser) return "model-only";
  return "both";
}

/* ---------- Hooks ---------- */

export interface DraftHook {
  event: string;
  matcher: string | null;
  type: string;
  command: string | null;
  timeout: number | null;
}

/** The hooks a `hooks.json` draft declares (Claude Code's `{"hooks": {Event: [{matcher, hooks}]}}`). */
export function readHooks(source: string): { hooks: DraftHook[]; error: string | null } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(source);
  } catch (error) {
    return { hooks: [], error: error instanceof Error ? error.message : "Not valid JSON." };
  }
  const root = typeof parsed === "object" && parsed !== null ? (parsed as JsonObject) : null;
  const events =
    root && typeof root.hooks === "object" && root.hooks !== null
      ? (root.hooks as JsonObject)
      : null;
  if (!events) return { hooks: [], error: 'No "hooks" object at the top level.' };
  const hooks: DraftHook[] = [];
  for (const [event, groups] of Object.entries(events)) {
    for (const group of Array.isArray(groups) ? groups : []) {
      const g = typeof group === "object" && group !== null ? (group as JsonObject) : {};
      const matcher = typeof g.matcher === "string" && g.matcher !== "" ? g.matcher : null;
      for (const hook of Array.isArray(g.hooks) ? g.hooks : []) {
        const h = typeof hook === "object" && hook !== null ? (hook as JsonObject) : {};
        hooks.push({
          event,
          matcher,
          type: typeof h.type === "string" ? h.type : "command",
          command: typeof h.command === "string" ? h.command : null,
          timeout: typeof h.timeout === "number" ? h.timeout : null,
        });
      }
    }
  }
  return { hooks, error: null };
}

/* ---------- What the draft reads as ---------- */

export type CheckState = "ok" | "warn" | "todo";

export interface DraftCheck {
  id: string;
  state: CheckState;
  label: string;
}

export interface DraftSummary {
  kind: ItemKind;
  /** The main file: `SKILL.md`, the agent's `<name>.md`, or `hooks.json`; null before it exists. */
  main: DraftFile | null;
  name: string | null;
  description: string | null;
  document: ReadDocument | null;
  hooks: DraftHook[];
  hooksError: string | null;
  /** The catalog card it will be, once published. */
  card: CatalogItem | null;
  checks: DraftCheck[];
  /** Every check passes or only warns: publishing is allowed. */
  publishable: boolean;
}

function mainFile(kind: ItemKind, files: readonly DraftFile[]): DraftFile | null {
  if (kind === "skill") return files.find((f) => f.path === "SKILL.md") ?? null;
  if (kind === "hook") return files.find((f) => f.path === "hooks.json") ?? null;
  return files.find((f) => !f.path.includes("/") && f.path.endsWith(".md")) ?? null;
}

/**
 * What the draft files read as: name, description, the catalog card, the checks before
 * publishing. `taken` holds the names already in the catalog for this kind.
 */
export function summarize(
  kind: ItemKind,
  files: readonly DraftFile[],
  taken: ReadonlySet<string> = new Set(),
): DraftSummary {
  const main = mainFile(kind, files);
  const checks: DraftCheck[] = [];
  let name: string | null = null;
  let description: string | null = null;
  let document: ReadDocument | null = null;
  let hooks: DraftHook[] = [];
  let hooksError: string | null = null;
  let mode: Mode | null = null;
  let invocation: string | null = null;

  if (kind === "hook") {
    if (main) {
      const read = readHooks(main.content);
      hooks = read.hooks;
      hooksError = read.error;
      const first = hooks[0];
      if (first) {
        description = `${first.event}${first.matcher ? ` (${first.matcher})` : ""}${first.command ? `: ${first.command}` : ""}`;
      }
      const script = files.find((f) => f.path !== "hooks.json" && !f.path.endsWith(".md"));
      name = script ? (script.path.split("/").pop() ?? "").replace(/\.[^.]+$/, "") : null;
    }
    checks.push({
      id: "file",
      state: main ? "ok" : "todo",
      label: main ? "hooks.json written" : "hooks.json not written yet",
    });
    if (main) {
      checks.push(
        hooksError
          ? { id: "json", state: "warn", label: `hooks.json does not read: ${hooksError}` }
          : hooks.length === 0
            ? { id: "json", state: "warn", label: "hooks.json declares no hook" }
            : {
                id: "json",
                state: "ok",
                label: `${String(hooks.length)} ${hooks.length === 1 ? "hook" : "hooks"} on ${[...new Set(hooks.map((h) => h.event))].join(", ")}`,
              },
      );
      const noCommand = hooks.filter((h) => h.type === "command" && !h.command).length;
      if (noCommand > 0)
        checks.push({ id: "command", state: "warn", label: "A command hook has no command" });
    }
  } else {
    if (main) {
      document = readDocument(main.content, kind);
      name =
        pairText(document.pairs, "name") ??
        (kind === "agent" ? main.path.replace(/\.md$/, "") : null);
      description = pairText(document.pairs, "description");
      if (kind === "skill") {
        mode = skillMode(document.pairs);
        const hint = pairText(document.pairs, "argument-hint");
        invocation = name ? `/${name}${hint ? ` ${hint}` : ""}` : null;
      }
    }
    const fileName = kind === "skill" ? "SKILL.md" : "the agent file";
    checks.push({
      id: "file",
      state: main ? "ok" : "todo",
      label: main ? `${main.path} written` : `${fileName} not written yet`,
    });
    if (main && document?.unclosed) {
      checks.push({
        id: "frontmatter",
        state: "warn",
        label: "The frontmatter block does not close",
      });
    }
    if (main) {
      checks.push(
        name === null
          ? { id: "name", state: "warn", label: "No name in the frontmatter" }
          : !NAME_PATTERN.test(name)
            ? {
                id: "name",
                state: "warn",
                label: `Name "${name}" has characters the catalog cannot address`,
              }
            : !KEBAB.test(name)
              ? { id: "name", state: "warn", label: `Name "${name}" is not kebab-case` }
              : taken.has(name)
                ? { id: "name", state: "warn", label: `A ${kind} named "${name}" already exists` }
                : { id: "name", state: "ok", label: `Name "${name}" is free` },
      );
      checks.push(
        description === null
          ? {
              id: "description",
              state: "warn",
              label: "No description: the model cannot tell when to use it",
            }
          : description.length > DESCRIPTION_ADVISED_CHARS
            ? {
                id: "description",
                state: "warn",
                label: `Description is long (${String(description.length)} characters)`,
              }
            : { id: "description", state: "ok", label: "Description says when to use it" },
      );
      const unknown = document?.pairs.filter((pair) => !pair.known).map((pair) => pair.key) ?? [];
      if (unknown.length > 0) {
        checks.push({
          id: "keys",
          state: "warn",
          label: `Not understood by Claude Code: ${unknown.join(", ")}`,
        });
      }
      if (document?.body.trim() === "") {
        checks.push({ id: "body", state: "warn", label: "The body is empty" });
      }
    }
  }
  if (files.some((f) => f.partial)) {
    checks.push({
      id: "partial",
      state: "warn",
      label: "A file was edited but never written whole: the preview may miss text",
    });
  }
  if (files.some((f) => f.pending)) {
    checks.push({ id: "pending", state: "todo", label: "Claude is still writing" });
  }

  const card: CatalogItem | null = main
    ? {
        id: `draft/${kind}/${name ?? "untitled"}`,
        kind,
        name: name ?? "untitled",
        description,
        origin: "project-owned",
        mode,
        invocation,
        source: "draft",
        source_path: main.path,
        diagnostics_count: checks.filter((c) => c.state === "warn").length,
        usage:
          kind === "hook" ? null : { count: 0, last_used_at: null, model_count: 0, user_count: 0 },
        linked_from: [],
        active: true,
        state: null,
      }
    : null;
  return {
    kind,
    main,
    name,
    description,
    document,
    hooks,
    hooksError,
    card,
    checks,
    publishable: main !== null && !checks.some((c) => c.state === "todo"),
  };
}

/* ---------- Where it is published ---------- */

/**
 * The project's own plugin folder (`plugin/<name>`), read from the project-owned items of the
 * catalog; null when the catalog has none, and Claude picks it from the hub's files.
 */
export function projectPluginDir(items: readonly CatalogItem[]): string | null {
  const counts = new Map<string, number>();
  for (const item of items) {
    if (item.origin !== "project-owned") continue;
    const match = /^(plugin\/[^/]+)\//.exec(item.source_path);
    if (match?.[1]) counts.set(match[1], (counts.get(match[1]) ?? 0) + 1);
  }
  let best: string | null = null;
  for (const [dir, count] of counts)
    if (best === null || count > (counts.get(best) ?? 0)) best = dir;
  return best;
}

/** Where the draft lands when published, for the owner to read before clicking Publish. */
export function destination(kind: ItemKind, name: string | null, pluginDir: string | null): string {
  const root = pluginDir ?? "plugin/<project plugin>";
  const item = name ?? "<name>";
  if (kind === "skill") return `${root}/skills/${item}/`;
  if (kind === "agent") return `${root}/agents/${item}.md`;
  return `${root}/hooks/hooks.json`;
}

/* ---------- What Claude is told ---------- */

const KIND_BRIEF: Record<ItemKind, string> = {
  skill:
    "A skill is a folder with a SKILL.md: YAML frontmatter (name in kebab-case, a description that says what it does and when to use it, and only when needed argument-hint, allowed-tools, disable-model-invocation, user-invocable, model) and a Markdown body of instructions. Bundled files go beside it (references/, scripts/, assets/) and the body links them by relative path.",
  agent:
    "An agent (a Claude Code subagent) is one Markdown file named <name>.md: YAML frontmatter (name in kebab-case, a description that says when the main session should delegate to it, and only when needed tools, model, skills, color) and a body that is its system prompt.",
  hook: 'A hook is a hooks.json in Claude Code\'s format: {"hooks": {"<Event>": [{"matcher": "<tool pattern>", "hooks": [{"type": "command", "command": "<shell>", "timeout": <seconds>}]}]}}. Events: PreToolUse, PostToolUse, UserPromptSubmit, Stop, SubagentStop, SessionStart, SessionEnd, Notification, PreCompact. A script it runs goes beside it (scripts/<name>.sh), referenced through ${CLAUDE_PLUGIN_ROOT} once published.',
};

export interface StudioBrief {
  project: string;
  kind: ItemKind;
  draftId: string;
  pluginDir: string | null;
  /** Names already in the catalog for this kind, so Claude does not reuse one. */
  taken: readonly string[];
}

/** The first message of a Studio conversation: what to build, where to write it, then the ask. */
export function studioPrompt(brief: StudioBrief, message: string): string {
  const dir = draftDir(brief.draftId);
  const target = brief.pluginDir
    ? `It will be published into the project's own plugin, ${brief.pluginDir}/.`
    : "It will be published into the project's own plugin under plugin/ (not plugin/hub-workflow, which hub sync overwrites); read hub.json and AGENTS.md to find it.";
  const head = [
    `I am the owner of the agent-hub project "${brief.project}", writing from the agent-hub web app's Studio.`,
    `I want to create a new ${brief.kind} for this hub with you. ${KIND_BRIEF[brief.kind]}`,
    `Write the draft ONLY inside the folder ${dir}/ (create it). The web app previews every file you write there, live, as you write it. Do not write anywhere else: nothing is published until I click Publish.`,
    target,
    "Before writing, read the closest existing items of the hub (plugin/*/skills, plugin/*/agents, .claude/) and mirror their shape and tone; reuse what exists instead of duplicating it.",
    brief.taken.length > 0 ? `These ${brief.kind} names are taken: ${brief.taken.join(", ")}.` : "",
    "If my ask is unclear, ask me at most three short questions first. Otherwise write a first complete draft right away, then tell me in a few lines what you built and what I should decide. Use Write for whole files and Edit for changes, so the preview stays exact.",
  ];
  return [...head.filter((line) => line !== ""), "", "What I want:", message].join("\n");
}

/** The message the Publish button sends: move the draft into place, nothing else. */
export function publishPrompt(kind: ItemKind, draftId: string, to: string): string {
  const dir = draftDir(draftId);
  const how: Record<ItemKind, string> = {
    skill: `Move the folder ${dir}/ to ${to} (SKILL.md and every bundled file).`,
    agent: `Move the agent file from ${dir}/ to ${to}.`,
    hook: `Merge the hooks of ${dir}/hooks.json into ${to} (create it if missing; keep every hook already there), move any script beside it into the plugin's scripts/ and point the command at \${CLAUDE_PLUGIN_ROOT}.`,
  };
  return [
    "I reviewed the draft in the preview and I approve it. Publish it now:",
    how[kind],
    `Then delete ${dir}/. If the plugin's manifest lists its ${kind}s explicitly, add it there too. Do not change anything else and do not commit.`,
    "Reply with one line per file you wrote, starting with PUBLISHED.",
  ].join("\n");
}

/** The message the Discard button sends. */
export function discardPrompt(draftId: string): string {
  return `I am discarding this draft. Delete the folder ${draftDir(draftId)}/ and nothing else.`;
}
