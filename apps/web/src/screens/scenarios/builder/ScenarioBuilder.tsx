import "./builder.css";
import "./blocks.css";
import "./steps.css";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";
import { useNavigate, useSearchParams } from "react-router";

import {
  Banner,
  Button,
  CopyButton,
  Icon,
  IconButton,
  MenuItem,
  SegmentedControl,
  Tabs,
  Toast,
} from "../../../components";
import { readStored, writeStored } from "../../../lib/storage";
import { environmentsPage } from "../../hub-config/environments";
import { DiscussButton, useDiscuss } from "../../../shell/discuss";
import { EffectBadge } from "../parts";
import {
  usePlanScenario,
  useSaveEnvironmentValue,
  useScenario,
  type ScenarioAction,
  type ScenarioDetail,
} from "../queries";
import { BlocksTab, type BlockLook } from "./BlocksTab";
import { StepList, nearestGap, scrollNear, type GapKind, type InsertTarget } from "./StepList";
import { VariablesPanel, type KeptValue } from "./VariablesPanel";
import { InsertMenu } from "./InsertMenu";
import {
  aboutStepMessage,
  createActionMessage,
  describeMessage,
  type DescribeScope,
} from "./claude";
import {
  AskActionDialog,
  DescribeDialog,
  NewActionDialog,
  useDismissProposal,
  useProposal,
} from "./ClaudeDialogs";
import { StartCard } from "./StartCard";
import { MigrateDialog } from "./MigrateDialog";
import { ActionPanel } from "../ActionPanel";
import { blockItem } from "./palette";
import { FlowCanvas, kindLook, type AddChoice } from "./FlowCanvas";
import { BlockInspector, GroupInspector, ScenarioSettings, StageInspector } from "./Inspector";
import {
  allNodes,
  dependsOn,
  freshId,
  removeBlock,
  insertAfter,
  insertBranch,
  newBlock,
  toDocument,
  updateBlock,
  valueSources,
  without,
  withoutRunRepeats,
  withoutRunRepeatsOf,
  type BuilderDocument,
  type BuilderNode,
  type ScenarioDocument,
} from "./model";
import {
  addressOfKey,
  addressed,
  decideReview,
  derivedId,
  findItem,
  fresh as freshItems,
  idChanges,
  insertAt,
  isTree,
  keyPathOf,
  listAt,
  itemId,
  keysOf,
  locate,
  mapNodes,
  newStage,
  nodeItems,
  stageSlug,
  stagesOf,
  stepNumbers,
  nodesOf,
  programNodes,
  programOf,
  renameRefs,
  replaceItem,
  takeFrom,
  toTreeDocument,
  treeNodes,
  treeOf,
  treeReview,
  type Decision,
  type Item,
  type TreeReview,
} from "./program";
import {
  useActionLibrary,
  useScenarioDraft,
  type BuilderProblem,
  type LibraryAction,
} from "./useScenarioDraft";

/* The scenario builder (Build mode of the scenario page, v6). Its main view is the step list:
 * the scenario read top to bottom, a numbered row per step, Repeat / If / At the same time as
 * indented groups. On the left, the Variables (where every value comes from) and the Actions of
 * the hub; on the right, the editor of the selected step. Graph shows the same flow as connected
 * nodes, and YAML the file Save writes. For a graph (`version: 1`) the list is a reading of the
 * document: every edit rewrites the scenario's `nodes`, which the server checks a moment later,
 * and More offers Migrate. A scenario written as blocks (`version: 2`) is edited as its stages:
 * the list is the file's `stages`, each block keyed by its address, every edit rewrites them,
 * and the Graph view only draws how they run. The builder never writes YAML: the server does. */

type View = "blocks" | "graph" | "yaml";

/** An edit of a scenario written as blocks: the document it writes, and each item's key after
 * it. */
interface TreeWrite {
  written: ScenarioDocument;
  keys: Map<string, string>;
}

const FILE_POLL_MS = 4000;
const HELP_KEY = "ah.builder.help.v6";

/** The Actions tab: the hub's actions, what each does, its effect and how many steps use it. */
function ActionsTab({
  library,
  libraryError,
  usage,
  onOpen,
  onNewAction,
  onAskAction,
}: {
  library: readonly LibraryAction[];
  libraryError: boolean;
  usage: ReadonlyMap<string, number>;
  onOpen: (item: LibraryAction, opener: HTMLElement) => void;
  onNewAction: () => void;
  onAskAction: () => void;
}) {
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const shown = library.filter((item) =>
    `${item.action.ref} ${item.action.description ?? ""}`.toLowerCase().includes(needle),
  );
  return (
    <div className="sb-left-body">
      <input
        className="ah-input"
        type="search"
        aria-label="Find an action"
        placeholder="Find an action"
        data-left-search
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
      />
      {libraryError && (
        <Banner tone="error" live={false}>
          Could not load the actions. Reload the page; if it stays, run ./hub doctor.
        </Banner>
      )}
      {!libraryError && library.length === 0 && (
        <span className="ah-small ah-muted">
          No actions yet. An action is a script with a declared effect, in actions/&lt;pack&gt;/.
        </span>
      )}
      <ul className="sb-actions" aria-label="Actions in this hub">
        {shown.map((item) => {
          const used = usage.get(item.action.ref) ?? 0;
          return (
            <li key={item.action.ref}>
              <button
                type="button"
                className="sb-action-entry"
                onClick={(event) => {
                  onOpen(item, event.currentTarget);
                }}
              >
                <span className="sb-action-entry-head">
                  <Icon name="circle-play" size="sm" />
                  <span className="ah-mono">{item.action.name}</span>
                  <span className="ah-grow" />
                  <EffectBadge effect={item.action.effect} words />
                </span>
                {item.action.description && (
                  <span className="sb-action-entry-desc">{item.action.description}</span>
                )}
                <span className="sb-action-entry-foot">
                  {used > 0
                    ? `used by ${String(used)} ${used === 1 ? "step" : "steps"}`
                    : "not used"}
                  {item.action.draft ? " · Draft" : ""}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <span className="sb-action-buttons">
        <Button size="sm" icon="plus" onClick={onNewAction}>
          New action
        </Button>
        <Button size="sm" variant="ghost" icon="message-square" onClick={onAskAction}>
          Ask Claude to write one
        </Button>
      </span>
    </div>
  );
}

/** Every value a condition may compare anywhere in the flow. */
function everySource(document: BuilderDocument, outputs: (action: string) => readonly string[]) {
  const ids = document.nodes.map((node) => node.id);
  const probe = {
    ...document,
    nodes: [...document.nodes, { id: "__probe__", type: "action", depends_on: ids }],
  };
  return valueSources(probe, "__probe__", outputs);
}

// A key of a block written as blocks, as the step editor's field for it names it.
const FIELD_OF_KEY: Readonly<Record<string, string>> = {
  do: "action",
  wait_until: "action",
  you: "message",
  "repeat.max": "max_iterations",
  "repeat.until": "until_when",
};

/** The problems of the block at `key` of a scenario written as blocks, each keyed as the step
 * editor's fields are (`until` of a Wait until is `until_when`, a Pause's `wait.duration` is
 * `duration`), so a problem shows under its field. */
function inspectorProblems(
  problems: readonly BuilderProblem[],
  key: string,
  type: string,
): BuilderProblem[] {
  const prefix = `${keyPathOf(key)}.`;
  return problems.map((problem) => {
    if (!problem.key?.startsWith(prefix)) return problem;
    const rest = problem.key.slice(prefix.length);
    const named = Object.keys(FIELD_OF_KEY).find(
      (written) => rest === written || rest.startsWith(`${written}.`),
    );
    let field = named ? `${FIELD_OF_KEY[named] ?? named}${rest.slice(named.length)}` : rest;
    if (rest.startsWith("wait.")) field = rest.slice("wait.".length);
    else if (type === "expect" && (rest === "until" || rest.startsWith("until."))) {
      field = `until_when${rest.slice("until".length)}`;
    }
    return { ...problem, key: field };
  });
}

export function ScenarioBuilder({
  scenario,
  mode,
  onRun,
}: {
  scenario: ScenarioDetail;
  mode: "interactive" | "regression";
  /** Switches the page to its Run mode (plan, start, watch). */
  onRun: () => void;
}) {
  const library = useActionLibrary(scenario.project);
  const items = library.data?.items ?? [];
  // The file read again every few seconds: a change made outside (Claude, an editor) shows here.
  const fresh = useScenario(scenario.project, scenario.name, FILE_POLL_MS).data ?? scenario;
  // Written as blocks or as a graph: the page mounts a new builder when the file's format changes.
  const tree = isTree(scenario.document);
  const draft = useScenarioDraft({
    project: scenario.project,
    name: scenario.name,
    pack: scenario.pack,
    initial: tree ? toTreeDocument(fresh.document) : toDocument(fresh.document),
    contentHash: fresh.content_hash ?? null,
    read: tree ? toTreeDocument : toDocument,
  });
  const { setOpen } = useDiscuss();
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<View>("blocks");
  const [inserting, setInserting] = useState<{
    target: InsertTarget;
    anchor: DOMRect;
    where: string;
  } | null>(null);
  const [menu, setMenu] = useState<"more" | "problems" | "preview" | null>(null);
  const [migrating, setMigrating] = useState(false);
  const planner = usePlanScenario(scenario.project, scenario.name);
  const [params, setParams] = useSearchParams();
  const environment =
    params.get("env") ??
    (scenario.environments.length > 0 ? (scenario.environments[0]?.name ?? "") : "");
  const setEnvironment = (next: string) => {
    setParams(
      (current) => {
        const copy = new URLSearchParams(current);
        if (next === "") copy.delete("env");
        else copy.set("env", next);
        return copy;
      },
      { replace: true },
    );
  };
  // Where values come from, in the chosen environment.
  const environmentInfo = scenario.environments.find((item) => item.name === environment) ?? null;
  const environmentValues: Record<string, string> | null = environmentInfo
    ? (environmentInfo.values ?? {})
    : null;
  const [stepTab, setStepTab] = useState<"settings" | "script">("settings");
  const [planValues, setPlanValues] = useState<Record<string, string>>({});
  const [planAfterSave, setPlanAfterSave] = useState<Record<string, string> | null>(null);
  const [leftTab, setLeftTab] = useState<"blocks" | "variables" | "actions">("blocks");
  // A block dragged from the Blocks tab: how it looks, where the pointer is, where it would land.
  const [paletteDrag, setPaletteDrag] = useState<{
    look: BlockLook;
    x: number;
    y: number;
    target: InsertTarget | null;
  } | null>(null);
  const listScroll = useRef<HTMLDivElement>(null);
  const [rowMenu, setRowMenu] = useState<{ id: string; anchor: DOMRect } | null>(null);
  const [announce, setAnnounce] = useState("");
  const [variable, setVariable] = useState<string | null>(null);
  const preview = planner.data ?? null;
  const [previewed, setPreviewed] = useState<unknown>(null);
  if (preview && previewed !== preview) {
    setPreviewed(preview);
    if (menu === "preview") setMenu(null);
  }
  const planRows = new Map((preview?.rows ?? []).map((row) => [row.step, row]));
  // The steps as they were when the preview ran: a change after it makes the preview stale.
  const [previewFor, setPreviewFor] = useState<string | null>(null);
  const [settings, setSettings] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [help, setHelp] = useState(() => readStored(HELP_KEY) !== "hidden");
  const [describing, setDescribing] = useState(false);
  const [awaiting, setAwaiting] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  // The changes of a graph's proposal decided, accepted and rejected, by block id.
  const [resolved, setResolved] = useState<Set<string>>(() => new Set());
  // Written as blocks, the review under way: its changes (read once, from the draft as it was
  // when the review opened, `treeReview`), the decisions made on them, and the draft they gave
  // and the proposal, as text: any other edit of the draft, or another proposal, opens the review
  // again on the draft as it then is.
  const [decided, setDecided] = useState<{
    review: TreeReview;
    decisions: ReadonlyMap<string, Decision>;
    wrote: string;
    proposal: string;
  } | null>(null);
  const [newAction, setNewAction] = useState<{
    node: string | null;
    readOnly: boolean;
    existing?: ScenarioAction;
  } | null>(null);
  // Ask Claude for an action: for a step (and whether it may only read), or for the scenario.
  const [askingAction, setAskingAction] = useState<{
    step: string | null;
    readOnly: boolean;
  } | null>(null);
  const [actionPanel, setActionPanel] = useState<string | null>(null);
  const actionOpener = useRef<HTMLElement | null>(null);
  // A stage being renamed: its key, the stages and the draft before the rename began, and the
  // draft the rename wrote last.
  const renaming = useRef<{
    key: string;
    main: Item[];
    raw: ScenarioDocument;
    wrote: ScenarioDocument;
  } | null>(null);
  const { ask } = useDiscuss();
  const navigate = useNavigate();
  const saveValue = useSaveEnvironmentValue(scenario.project);
  const proposal = useProposal(scenario.project, scenario.name, awaiting);
  const dismiss = useDismissProposal(scenario.project, scenario.name);
  const offered = proposal.data?.document ? proposal.data : null;
  if (awaiting && offered) setAwaiting(false);
  // Under review the list shows the proposal, its rows under their own keys: a key there (an
  // address, written as blocks) can name another block of the draft, so no edit reads the
  // selection until the review closes.
  const underReview = reviewing && offered !== null;
  const editable = underReview ? null : selected;
  useEffect(() => {
    if (toast === null) return;
    const timer = setTimeout(() => {
      setToast(null);
    }, 6000);
    return () => {
      clearTimeout(timer);
    };
  }, [toast]);
  const raw: ScenarioDocument = draft.document;
  // Written as blocks, the stages are the program, read straight from the draft: the same file
  // gives the same keys (the block addresses), so nothing needs keeping between edits.
  const stages = useMemo(() => (tree ? stagesOf(raw) : []), [tree, raw]);
  // The document as the step editor, the values and the Graph view read it: the graph itself,
  // or, written as blocks, the nodes the stages run as (read-only: edits go to the stages).
  const document: BuilderDocument = useMemo(
    () => (tree ? { ...without(raw, "stages"), nodes: treeNodes(stages) } : toDocument(raw)),
    [tree, raw, stages],
  );

  // The program, read again whenever the document changes from elsewhere (undo, the graph).
  const [synced, setSynced] = useState("");
  const [program, setProgram] = useState<{ main: Item[]; kept: BuilderNode[] }>({
    main: [],
    kept: [],
  });
  const nodesText = JSON.stringify(document.nodes);
  if (!tree && synced !== nodesText) {
    const read = programOf(document.nodes);
    setSynced(nodesText);
    setProgram({ main: read.main, kept: read.loose });
  }
  const main: Item[] = tree ? stages : program.main;
  const kept: BuilderNode[] = tree ? [] : program.kept;

  /* Written as blocks: the document the stages `next` write, where each reference to a block
   * whose place id the edit changes follows it (`idChanges`), and each item's key after the
   * edit (keys are addresses). */
  const treeWrite = (next: readonly Item[]): TreeWrite => ({
    written: renameRefs(treeOf(raw, next), idChanges(main, next)),
    keys: addressed(next).keys,
  });
  // Puts a tree write in the draft; `focus` as `commit` takes it.
  const writeTree = ({ written, keys }: TreeWrite, focus?: string | null) => {
    const follow = focus === undefined ? selected : focus;
    setSelected(follow === null ? null : (keys.get(follow) ?? null));
    if (JSON.stringify(written) !== JSON.stringify(raw)) draft.edit(written);
    return (key: string) => keys.get(key) ?? key;
  };

  /* Writes the list back: a graph's nodes (steps the list cannot place stay as written), or the
   * stages of a scenario written as blocks (`treeWrite`). `focus` is what to select after (by
   * its key now); the answer gives an item's key after the edit. */
  const commit = (
    next: Item[],
    keptNext: BuilderNode[] = kept,
    focus?: string | null,
  ): ((key: string) => string) => {
    if (tree) return writeTree(treeWrite(next), focus);
    const nodes = [...nodesOf(next), ...keptNext];
    setProgram({ main: next, kept: keptNext });
    const text = JSON.stringify(nodes);
    setSynced(text);
    if (text !== nodesText) draft.edit({ ...document, nodes });
    if (focus !== undefined) setSelected(focus);
    return (key) => key;
  };

  const allItems: Item[] = [...main, ...kept.map((node): Item => ({ kind: "block", node }))];
  const taken: BuilderDocument = { ...document, nodes: programNodes(allItems) };
  // Written as blocks: each block's key and the id its node runs under, both ways.
  const keyOfNode = new Map<string, string>();
  const nodeOfKey = new Map<string, string>();
  for (const node of tree ? nodeItems(main) : []) {
    keyOfNode.set(node.node.id, itemId(node));
    nodeOfKey.set(itemId(node), node.node.id);
  }
  const keyOf = (id: string) => keyOfNode.get(id) ?? id;
  const nodeIdOf = (key: string) => nodeOfKey.get(key) ?? key;
  // What a header edit of a scenario written as blocks keeps: its stages.
  const editHeader = (next: BuilderDocument) => {
    draft.edit(tree ? treeOf(without(next, "nodes"), main) : next);
  };

  const findAction = (ref: string) =>
    items.find(
      (entry) => entry.action.ref === ref || entry.action.ref === `${scenario.pack}/${ref}`,
    ) ?? null;
  const actionFacts = (node: BuilderNode): ScenarioAction | null =>
    typeof node.action === "string" && node.action !== ""
      ? (findAction(node.action)?.action ?? null)
      : null;
  const outputs = (action: string) =>
    findAction(action)?.output_fields.map((field) => field.path) ?? [];
  const problems = draft.check?.problems ?? [];
  const errors = problems.filter((problem) => problem.severity === "error");
  // The block a problem is on: by its node in a graph, by its key path written as blocks.
  const problemAt = (problem: (typeof problems)[number]): string | null =>
    tree ? addressOfKey(problem.key) : (problem.node ?? null);
  const problemsOf = (key: string) => problems.filter((problem) => problemAt(problem) === key);

  // Written as blocks, a stage goes only between stages, and a step only into a list of steps.
  const fits = (moved: readonly Item[], slot: InsertTarget["slot"]) =>
    !tree || moved.every((item) => (item.kind === "stage") === (slot.in === "main"));
  // New blocks written as blocks have no id of their own until one is given.
  const asNew = (made: Item[]): Item[] => (tree ? freshItems(made) : made);

  // Puts `moved` at a place of the list.
  const placeAt = (made: Item[], target: InsertTarget) => {
    const moved = asNew(made);
    if (!fits(moved, target.slot)) return;
    const first = moved[0];
    commit(
      insertAt(main, target.slot, target.index, moved),
      kept,
      first ? itemId(first) : undefined,
    );
  };

  // Moves the step `id` to a gap of the list (by its handle, or the row menu).
  const moveTo = (id: string, target: InsertTarget) => {
    const from = locate(main, id);
    if (!from) return;
    const { rest, taken: moved } = takeFrom(main, id, true);
    if (moved.length === 0 || !fits(moved, target.slot)) return;
    const sameList = JSON.stringify(from.slot) === JSON.stringify(target.slot);
    const index = sameList && target.index > from.index ? target.index - 1 : target.index;
    if (sameList && index === from.index) return;
    const now = commit(insertAt(rest, target.slot, index, moved), kept, id);
    setAnnounce(
      `Moved ${moved[0]?.kind === "stage" ? "stage" : "step"} ${now(id)} to position ${String(index + 1)}.`,
    );
  };

  // The stage a key is in (the stage itself for a stage), written as blocks.
  const stageOf = (key: string | null) =>
    key === null ? null : (main.find((stage) => itemId(stage) === key.split(".")[0]) ?? null);
  // The id a block written as blocks runs under when it has none of its own.
  const placeIdOf = (key: string) => {
    const stage = stageOf(key);
    return stage?.kind === "stage" ? derivedId(stageSlug(stage.name), key) : key;
  };

  // A click on the palette adds after the selected block (in its list), else at the end; nothing
  // while a proposal is under review.
  const addAtEnd = (made: Item) => {
    const [item] = asNew([made]);
    if (!item || underReview) return;
    if (tree) {
      const stage = stageOf(selected);
      if (item.kind === "stage") {
        const index = stage ? main.indexOf(stage) + 1 : main.length;
        commit(insertAt(main, { in: "main" }, index, [item]), kept, item.key);
        return;
      }
      const at = selected && stage?.key !== selected ? locate(main, selected) : null;
      const last = stage ?? main.at(-1);
      let next: Item[];
      if (at) next = insertAt(main, at.slot, at.index + 1, [item]);
      else if (last?.kind === "stage") {
        next = insertAt(main, { in: "stage", owner: last.key }, last.steps.length, [item]);
      } else next = [...main, { ...newStage([]), steps: [item] }];
      commit(next, kept, itemId(item));
      return;
    }
    const at = selected ? locate(main, selected) : null;
    const next = at ? insertAt(main, at.slot, at.index + 1, [item]) : [...main, item];
    commit(next, kept, itemId(item));
  };
  const insertHere = (item: Item) => {
    if (!inserting) return;
    placeAt([item], inserting.target);
    setInserting(null);
  };
  // A new stage at `index` of the stages, selected for its name.
  const insertStage = (index: number) => {
    const stage = newStage(main.flatMap((item) => (item.kind === "stage" ? [item.name] : [])));
    commit(insertAt(main, { in: "main" }, index, [stage]), kept, itemId(stage));
  };

  const editItem = (id: string, edited: Item) => {
    // Written as blocks, an edited block keeps its key and whether its id is its own.
    const current = tree ? findItem(main, id) : null;
    let next = edited;
    if (
      current &&
      (current.kind === "block" || current.kind === "repeat") &&
      (next.kind === "block" || next.kind === "repeat")
    ) {
      next = { ...next, key: itemId(current), named: current.named === true };
    }
    commit(
      replaceItem(main, id, next),
      kept.map((node) => (node.id === id && next.kind === "block" ? next.node : node)),
    );
  };

  const editNode = (key: string, node: BuilderNode) => {
    const current = findItem(allItems, key);
    if (current?.kind === "repeat") editItem(key, { ...current, node });
    else editItem(key, { kind: "block", node });
  };

  const removeItem = (id: string) => {
    commit(
      takeFrom(main, id, true).rest,
      kept.filter((node) => node.id !== id),
      null,
    );
  };

  // A copy of the step right after it (a fresh id; a group is not copied).
  const duplicate = (id: string) => {
    const item = findItem(main, id);
    const at = locate(main, id);
    if (item?.kind !== "block" || !at) return;
    const [copy] = asNew([
      { kind: "block", node: { ...item.node, id: freshId(taken, item.node.id) } },
    ]);
    if (!copy) return;
    commit(insertAt(main, at.slot, at.index + 1, [copy]), kept, itemId(copy));
    setAnnounce(`Duplicated step ${id}.`);
  };

  const selectedItem = selected ? findItem(allItems, selected) : null;
  const serialized: BuilderDocument = tree
    ? document
    : { ...document, nodes: [...nodesOf(main), ...kept] };

  /* Written as blocks, a block's id given in its editor: its own (written even when it equals its
   * place's, so that it stays when the block moves), or none (it runs under its place's again).
   * The references to the id it ran under follow it as any edit's do
   * (`idChanges`): not when another block ran under that id, or runs under the new one. */
  const renameBlock = (key: string, next: BuilderNode) => {
    const current = findItem(main, key);
    if (current?.kind !== "block" && current?.kind !== "repeat") return;
    const named = next.id !== "";
    const node = { ...without(next, "nodes"), id: named ? next.id : placeIdOf(key) };
    commit(replaceItem(main, key, { ...current, node, named }));
  };

  /* Written as blocks, a stage's name or description changed in its editor, letter by letter.
   * Its blocks' references follow them from the ids they ran under before the rename began, so
   * a name that passes through another stage's slug (two blocks then share an id, which no
   * reference can follow) loses none of them. The rename goes on from there as long as nothing
   * else edits the draft (`renaming`). */
  const editStage = (key: string, change: { name: string; description: string }) => {
    const held = renaming.current;
    const base = held?.key === key && held.wrote === raw ? held : { key, main, raw };
    const stage = findItem(base.main, key);
    if (stage?.kind !== "stage") return;
    const extra = without(stage.extra ?? {}, "description");
    const edited: Item = {
      ...stage,
      name: change.name,
      extra: change.description === "" ? extra : { ...extra, description: change.description },
    };
    const next = replaceItem(base.main, key, edited);
    const written = renameRefs(treeOf(base.raw, next), idChanges(base.main, next));
    const changed = JSON.stringify(written) !== JSON.stringify(raw);
    renaming.current = { ...base, wrote: changed ? written : raw };
    if (changed) draft.edit(written);
  };

  const onGraphAdd = (choice: AddChoice, after: string | null, group: string | null) => {
    if (choice.kind === "branch") {
      if (after !== null) draft.edit(insertBranch(document, after, "$CTX.result", ["yes", "no"]));
      return;
    }
    if (choice.kind === "parallel") return;
    const block = newBlock(document, choice.kind);
    draft.edit(insertAfter(document, block, after, group));
    setSelected(block.id);
  };

  // What a step's form footer offers: ask Claude about it, duplicate it, delete it.
  const stepButtons = (id: string) => (
    <>
      <Button
        variant="ghost"
        icon="trash"
        onClick={() => {
          removeItem(id);
          setToast(`Deleted step ${id}.`);
        }}
      >
        Delete step
      </Button>
      <span className="ah-grow" />
      <Button
        variant="ghost"
        icon="copy"
        onClick={() => {
          duplicate(id);
        }}
      >
        Duplicate
      </Button>
      <Button
        variant="ghost"
        icon="message-square"
        onClick={() => {
          ask(aboutStepMessage({ id, scenario: scenario.name, path: scenario.path ?? "", tree }));
        }}
      >
        Ask Claude about this step
      </Button>
    </>
  );

  // The selected card, read when the form closes: focus goes back to it.
  const selectedCard: RefObject<HTMLElement | null> = {
    get current() {
      return globalThis.document.querySelector<HTMLElement>('.st-tree [aria-selected="true"]');
    },
  };
  const hatButton: RefObject<HTMLElement | null> = {
    get current() {
      return globalThis.document.querySelector<HTMLElement>('[data-row="__start__"]');
    },
  };
  const inspector = (() => {
    if (!selectedItem) {
      return settings ? (
        <ScenarioSettings
          document={document}
          onChange={editHeader}
          openerRef={hatButton}
          onClose={() => {
            setSettings(false);
          }}
        />
      ) : null;
    }
    if (selectedItem.kind === "stage") {
      const key = itemId(selectedItem);
      const description = selectedItem.extra?.description;
      return (
        <StageInspector
          key={key}
          number={key}
          name={selectedItem.name}
          description={typeof description === "string" ? description : ""}
          problems={problemsOf(key)}
          onChange={(next) => {
            editStage(key, next);
          }}
          onClose={() => {
            setSelected(null);
          }}
          openerRef={selectedCard}
          footer={
            <Button
              variant="ghost"
              icon="trash"
              onClick={() => {
                removeItem(key);
                setToast(`Deleted stage ${key} and its steps.`);
              }}
            >
              Delete the stage and its steps
            </Button>
          }
        />
      );
    }
    if (selectedItem.kind === "block" || selectedItem.kind === "repeat") {
      const key = itemId(selectedItem);
      // The block as it is written (with the `depends_on` its place in the stack gives it); written
      // as blocks, as it is (its place is its order).
      const written = tree
        ? undefined
        : allNodes(serialized.nodes).find((item) => item.id === selectedItem.node.id);
      const base = written ? { ...selectedItem.node, ...written } : selectedItem.node;
      const node =
        selectedItem.kind === "repeat" ? { ...base, nodes: nodesOf(selectedItem.body) } : base;
      return (
        <BlockInspector
          key={key}
          document={serialized}
          node={node}
          library={items}
          problems={tree ? inspectorProblems(problemsOf(key), key, node.type) : problemsOf(key)}
          mode={mode}
          number={stepNumbers(main).get(key)}
          placeId={tree ? placeIdOf(key) : undefined}
          named={selectedItem.named === true}
          onId={
            tree
              ? (id) => {
                  renameBlock(key, { ...node, id });
                }
              : undefined
          }
          libraryError={library.isError}
          openerRef={selectedCard}
          tab={stepTab}
          onTab={setStepTab}
          environment={
            environmentInfo ? { name: environmentInfo.name, values: environmentValues } : null
          }
          plan={(() => {
            const row = planRows.get(node.id);
            return row && preview?.environment ? { row, environment: preview.environment } : null;
          })()}
          actionTools={
            <>
              <Button
                size="sm"
                variant="ghost"
                icon="file-plus"
                onClick={() => {
                  setNewAction({ node: key, readOnly: node.type === "expect" });
                }}
              >
                New action
              </Button>
              <Button
                size="sm"
                variant="ghost"
                icon="message-square"
                onClick={() => {
                  // Written as blocks, a block is named by its address, as the file holds no id.
                  setAskingAction({ step: tree ? key : node.id, readOnly: node.type === "expect" });
                }}
              >
                Ask Claude to write one
              </Button>
            </>
          }
          onChange={(next) => {
            // A graph's id is set here; a block written as blocks gives its id through `onId`.
            if (!tree && next.id !== node.id) {
              draft.edit(updateBlock(serialized, node.id, next));
              setSelected(next.id);
              return;
            }
            if (selectedItem.kind === "repeat") {
              editItem(key, { ...selectedItem, node: without(next, "nodes") });
            } else editItem(key, { kind: "block", node: next });
          }}
          footer={stepButtons(key)}
          onClose={() => {
            setSelected(null);
          }}
        />
      );
    }
    const group = selectedItem;
    const groupId = itemId(group);
    return (
      <GroupInspector
        key={groupId}
        kind={group.kind}
        number={stepNumbers(main).get(groupId)}
        condition={group.kind === "if" ? group.condition : ""}
        lanes={group.kind === "parallel" ? group.lanes.length : 2}
        fields={everySource(serialized, outputs).map((source) => ({
          ref: source.ref,
          label: `${source.label} (${source.hint})`,
        }))}
        onCondition={(condition) => {
          if (group.kind === "if") editItem(groupId, { ...group, condition });
        }}
        onLanes={(count) => {
          if (group.kind !== "parallel") return;
          const lanes =
            count > group.lanes.length
              ? [...group.lanes, ...Array.from({ length: count - group.lanes.length }, () => [])]
              : group.lanes.slice(0, count);
          editItem(groupId, { ...group, lanes });
        }}
        onClose={() => {
          setSelected(null);
        }}
        openerRef={selectedCard}
        problems={problemsOf(groupId)}
        footer={
          <Button
            variant="ghost"
            icon="trash"
            onClick={() => {
              removeItem(groupId);
              setToast(`Deleted the ${group.kind === "if" ? "If" : "paths"} and what it holds.`);
            }}
          >
            Delete it and what it holds
          </Button>
        }
      />
    );
  })();

  // Describe in words → Claude proposes the scenario as blocks (a proposal file it writes).
  const sendDescription = (described: string, scope: DescribeScope, after: string | null) => {
    ask(
      describeMessage({
        text: described,
        scope,
        after,
        scenario: scenario.name,
        pack: scenario.pack,
        draftYaml: draft.check?.yaml ?? "",
        proposalPath: `.agent-runs/proposals/scenarios/${scenario.pack}/${scenario.name}.yaml`,
        actions: items,
        tree,
      }),
    );
    setAwaiting(true);
    setDescribing(false);
  };
  const proposed = offered?.document && !tree ? toDocument(offered.document) : null;
  // Written as blocks: the proposal's stages, and its changes by block address.
  const proposedTree = offered?.document && tree ? toTreeDocument(offered.document) : null;
  // A proposal for a scenario written as blocks that holds no stages (a graph of `nodes`, the
  // other format): reviewed as it is, every stage is removed.
  const proposedGraph = proposedTree !== null && !Array.isArray(proposedTree.stages);
  const theirStages = useMemo(() => (proposedTree ? stagesOf(proposedTree) : null), [proposedTree]);
  const proposalText = useMemo(() => JSON.stringify(proposedTree), [proposedTree]);
  const rawText = JSON.stringify(raw);
  const underway =
    decided !== null && decided.wrote === rawText && decided.proposal === proposalText
      ? decided
      : null;
  const review = useMemo(
    () => underway?.review ?? (proposedTree ? treeReview(raw, proposedTree) : null),
    [underway, proposedTree, raw],
  );
  const decisions: ReadonlyMap<string, Decision> = underway?.decisions ?? new Map();
  // The proposal's changes, block by block (a top-level step, a repeat with what it holds): new,
  // changed, or removed; the ones already accepted or rejected drop out.
  const changes: { id: string; kind: "new" | "changed" | "removed"; node: BuilderNode }[] = [];
  if (proposed) {
    const mine = new Map(document.nodes.map((node) => [node.id, node]));
    const theirs = new Set(proposed.nodes.map((node) => node.id));
    for (const node of proposed.nodes) {
      const before = mine.get(node.id);
      if (!before) changes.push({ id: node.id, kind: "new", node });
      else if (JSON.stringify(before) !== JSON.stringify(node)) {
        changes.push({ id: node.id, kind: "changed", node });
      }
    }
    for (const node of document.nodes) {
      if (!theirs.has(node.id)) changes.push({ id: node.id, kind: "removed", node });
    }
  }
  // Each change as the review lists it: what it is, its name to read, and its line of detail.
  const listed = tree
    ? (review?.changes ?? []).map((change) => {
        const { item } = change;
        const node = item?.kind === "block" || item?.kind === "repeat" ? item.node : null;
        const look = kindLook(
          item?.kind === "if"
            ? "branch"
            : item?.kind === "parallel"
              ? "parallel"
              : (node?.type ?? "stage"),
        );
        // Named by its id, its kind in it: a removed or changed block by its address in the
        // draft the review opened on, a new one by its address in the proposal, so two can have
        // the same address.
        return {
          id: change.id,
          kind: change.kind,
          of: change.of,
          shown: change.address === "" ? change.of : change.address,
          name: change.id,
          detail:
            item === null
              ? change.of === "inputs"
                ? `Inputs · ${Object.keys(proposedTree?.inputs ?? {}).join(", ")}`
                : `Description · ${typeof proposedTree?.description === "string" ? proposedTree.description : ""}`
              : item.kind === "stage"
                ? `Stage · ${item.name}`
                : `${look.label}${typeof node?.action === "string" ? ` · ${node.action}` : ""}${typeof node?.description === "string" ? ` · ${node.description}` : ""}`,
          // Outlined in the proposal: a new or changed block with what it holds; a stage's own
          // change, its header.
          suggested:
            item === null || change.kind === "removed"
              ? []
              : change.of === "stage" && change.kind === "changed"
                ? [itemId(item)]
                : keysOf(item),
        };
      })
    : changes.map((change) => ({
        id: change.id,
        kind: change.kind,
        of: "block" as const,
        shown: change.id,
        name: change.id,
        detail: `${kindLook(change.node.type).label}${typeof change.node.action === "string" ? ` · ${change.node.action}` : ""}${typeof change.node.description === "string" ? ` · ${change.node.description}` : ""}`,
        suggested: change.kind === "removed" ? [] : allNodes([change.node]).map((node) => node.id),
      }));
  const open = listed.filter((change) =>
    tree ? !decisions.has(change.id) : !resolved.has(change.id),
  );
  const suggestedIds = new Set(open.flatMap((change) => change.suggested));
  const removedCount = open.filter((change) => change.kind === "removed").length;
  // What the banner counts: new or changed blocks, and apart from them (written as blocks)
  // new or changed stages, a stage's own change among them, the inputs and the description.
  const added = (of: string) =>
    open.filter((change) => change.of === of && change.kind !== "removed").length;
  const blocksOpen = added("block");
  const stagesOpen = added("stage");
  const inputsOpen = open.some((change) => change.of === "inputs");
  const descriptionOpen = open.some((change) => change.of === "description");
  const counted = (n: number, what: string) => `${String(n)} ${what}${n === 1 ? "" : "s"}`;
  const proposes = [
    ...(blocksOpen > 0 || stagesOpen === 0 ? [counted(blocksOpen, "new or changed block")] : []),
    ...(stagesOpen > 0 ? [counted(stagesOpen, "new or changed stage")] : []),
    ...(removedCount > 0 ? [`${String(removedCount)} removed`] : []),
    ...(inputsOpen ? ["changed inputs"] : []),
    ...(descriptionOpen ? ["a changed description"] : []),
  ].join(", ");
  const closeReview = () => {
    setReviewing(false);
    setSelected(null);
    setResolved(new Set());
    setDecided(null);
    dismiss.mutate();
  };
  const finish = (next: Set<string>) => {
    if (listed.every((change) => next.has(change.id))) closeReview();
    else setResolved(next);
  };
  // Written as blocks: `ids` decided, and the draft written again from the draft the review
  // opened on, the proposal and every accept made (`decideReview`), never from the draft the
  // last decision gave. The review is done when every change it listed is decided; Accept all
  // and Reject all decide them all at once.
  const decideTree = (ids: readonly string[], decision: Decision) => {
    if (!review) return;
    const next = decideReview(review, decisions, ids, decision);
    const wrote = JSON.stringify(next.draft);
    if (wrote !== rawText) {
      draft.edit(next.draft);
      setSelected(null);
    }
    if (next.closed) closeReview();
    else setDecided({ review, decisions: next.decisions, wrote, proposal: proposalText });
  };
  const acceptOne = (id: string) => {
    if (tree) {
      decideTree([id], "accept");
      return;
    }
    const change = changes.find((item) => item.id === id);
    if (!change || !proposed) return;
    if (change.kind === "removed") draft.edit(removeBlock(document, id));
    else if (change.kind === "changed") draft.edit(updateBlock(document, id, change.node));
    else {
      // A new block goes right after the last block it waits for (or at the end).
      const waits = dependsOn(change.node);
      const at = Math.max(
        -1,
        ...waits.map((wait) => document.nodes.findIndex((node) => node.id === wait)),
      );
      const nodes = [...document.nodes];
      nodes.splice(at === -1 ? nodes.length : at + 1, 0, change.node);
      draft.edit({ ...document, nodes });
    }
    finish(new Set([...resolved, id]));
  };
  const rejectOne = (id: string) => {
    if (tree) decideTree([id], "reject");
    else finish(new Set([...resolved, id]));
  };
  const everyChange = (review?.changes ?? []).map((change) => change.id);
  const acceptProposal = () => {
    if (tree) {
      decideTree(everyChange, "accept");
      return;
    }
    if (!proposed) return;
    const next: ScenarioDocument = { ...document, nodes: proposed.nodes };
    if (proposed.inputs !== undefined) next.inputs = proposed.inputs;
    if (typeof proposed.description === "string") next.description = proposed.description;
    draft.edit(next);
    closeReview();
  };
  const rejectProposal = () => {
    if (tree) decideTree(everyChange, "reject");
    else closeReview();
  };
  const reviewPanel =
    reviewing && (proposed ?? proposedTree) ? (
      <section className="sb-inspector" aria-label="Claude's proposal">
        <header className="sb-inspector-head">
          <Icon name="message-square" size="sm" />
          <b>Claude&apos;s proposal</b>
          <span className="ah-grow" />
          <span className="ah-small ah-muted">{open.length} to decide</span>
        </header>
        <div className="sb-inspector-body">
          <span className="ah-small ah-muted">
            Accept or reject each change; the canvas shows the proposal, its new and changed blocks
            outlined. Nothing is saved until you press Save.
          </span>
          {open.map((change) => (
            <div key={change.id} className="sb-change" data-kind={change.kind}>
              <span className="sb-change-kind">{change.kind}</span>
              <span className="ah-stack" style={{ gap: 0, minWidth: 0 }}>
                <b className="ah-mono">{change.shown}</b>
                <span className="ah-small ah-muted">{change.detail}</span>
              </span>
              <span className="ah-row" style={{ gap: 4 }}>
                <Button
                  size="sm"
                  variant="primary"
                  aria-label={`Accept ${change.name}`}
                  onClick={() => {
                    acceptOne(change.id);
                  }}
                >
                  Accept
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Reject ${change.name}`}
                  onClick={() => {
                    rejectOne(change.id);
                  }}
                >
                  Reject
                </Button>
              </span>
            </div>
          ))}
        </div>
      </section>
    ) : null;
  const reviewProgram = underReview
    ? (theirStages ?? (proposed ? programOf(proposed.nodes).main : null))
    : null;

  // Keys on the builder (never while typing in a field): Delete removes the selected block (with
  // an Undo toast), Alt+↑/↓ moves it in its list, ⌘D duplicates it, ⌘Z/⇧⌘Z undo and redo, ⌘S
  // saves, Esc clears the selection. Under review, a selected row is the proposal's: the block
  // keys leave the draft as it is.
  const onKeys = (event: KeyboardEvent) => {
    const target = event.target as HTMLElement;
    if (!bodyRef.current?.contains(target) && target !== window.document.body) return;
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);
    const mod = event.metaKey || event.ctrlKey;
    if (mod && event.key.toLowerCase() === "s") {
      event.preventDefault();
      if (draft.dirty && errors.length === 0 && draft.check !== null) draft.save();
      return;
    }
    if (typing) return;
    if (mod && event.key.toLowerCase() === "z") {
      event.preventDefault();
      if (event.shiftKey) draft.redo();
      else draft.undo();
      return;
    }
    if (!selected) return;
    if (event.key === "Escape") {
      setSelected(null);
      return;
    }
    if (underReview) return;
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      const stage = findItem(main, selected)?.kind === "stage";
      removeItem(selected);
      setToast(stage ? `Deleted stage ${selected} and its steps.` : `Deleted step ${selected}.`);
    } else if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
      event.preventDefault();
      const at = locate(main, selected);
      if (!at) return;
      const to = at.index + (event.key === "ArrowUp" ? -1 : 1);
      const { rest, taken: moved } = takeFrom(main, selected, true);
      if (to < 0 || moved.length === 0) return;
      // Written as blocks, a block keeps to its list's end (a stage holds what it holds).
      if (tree && to > (listAt(rest, at.slot)?.length ?? 0)) return;
      commit(insertAt(rest, at.slot, to, moved));
    } else if (mod && event.key.toLowerCase() === "d") {
      event.preventDefault();
      const item = findItem(main, selected);
      const at = locate(main, selected);
      if (item?.kind !== "block" || !at) return;
      const [copy] = asNew([
        { kind: "block", node: { ...item.node, id: freshId(taken, item.node.id) } },
      ]);
      if (!copy) return;
      commit(insertAt(main, at.slot, at.index + 1, [copy]), kept, itemId(copy));
    }
  };

  const keys = useRef(onKeys);
  useEffect(() => {
    keys.current = onKeys;
  });
  useEffect(() => {
    const listen = (event: KeyboardEvent) => {
      keys.current(event);
    };
    window.addEventListener("keydown", listen);
    return () => {
      window.removeEventListener("keydown", listen);
    };
  }, []);

  const drafts = new Set(
    programNodes(main)
      .map((node) => actionFacts(node))
      .filter((action) => action?.draft === true)
      .map((action) => action?.ref),
  ).size;

  const declaredInputs = Object.entries(
    typeof document.inputs === "object" &&
      document.inputs !== null &&
      !Array.isArray(document.inputs)
      ? document.inputs
      : {},
  );
  // Required run inputs nothing else gives a value: asked at start (and before a plan).
  const asksAtStart = declaredInputs
    .filter(([name, spec]) => {
      const item = typeof spec === "object" && spec !== null && !Array.isArray(spec) ? spec : {};
      return item.default === undefined && !(environmentValues && name in environmentValues);
    })
    .map(([name]) => name);
  const missingToPlan = asksAtStart.filter((name) => (planValues[name] ?? "") === "");
  const planNow = (values: Record<string, string>) => {
    setMenu(null);
    if (draft.dirty) {
      setPlanAfterSave(values);
      draft.save();
      return;
    }
    setPreviewFor(JSON.stringify(document.nodes));
    planner.mutate({ environment, inputs: values });
  };
  // "Save and plan": the plan runs once the save has written the file.
  if (planAfterSave !== null && !draft.dirty && !draft.saving) {
    const values = planAfterSave;
    setPlanAfterSave(null);
    if (!draft.saveError) {
      setPreviewFor(JSON.stringify(document.nodes));
      queueMicrotask(() => {
        planner.mutate({ environment, inputs: values });
      });
    }
  }

  // Which steps use a variable: a reference to it, or an action input of its name the step
  // leaves to the run (or the environment).
  const nodeUses = (node: BuilderNode, name: string): boolean => {
    const written = JSON.stringify(without(node, "nodes"));
    if (written.includes(`$INPUTS.${name}`) || written.includes(`$CTX.${name}`)) return true;
    const facts = actionFacts(node);
    const given =
      typeof node.with === "object" && node.with !== null && !Array.isArray(node.with)
        ? node.with
        : {};
    return facts?.inputs.some((input) => input.name === name && !(name in given)) ?? false;
  };
  const everyNode = allNodes(document.nodes);
  const numbersNow = stepNumbers(main);
  const keptValues: KeptValue[] = everyNode.flatMap((node) =>
    Object.keys(
      typeof node.capture === "object" && node.capture !== null && !Array.isArray(node.capture)
        ? node.capture
        : {},
    ).map((name) => ({ name, step: node.id, number: numbersNow.get(keyOf(node.id)) ?? node.id })),
  );
  const variableUsage = new Map<string, number>();
  for (const name of [
    ...declaredInputs.map(([name]) => name),
    ...Object.keys(environmentValues ?? {}),
    ...keptValues.map((item) => item.name),
  ]) {
    variableUsage.set(name, everyNode.filter((node) => nodeUses(node, name)).length);
  }
  const actionUsage = new Map<string, number>();
  for (const node of everyNode) {
    const ref = actionFacts(node)?.ref;
    if (ref) actionUsage.set(ref, (actionUsage.get(ref) ?? 0) + 1);
  }
  const repeats = withoutRunRepeats(document);
  // Drops the repeats of a run value: from the graph's nodes, or from each block's `with`.
  const dropRepeats = () => {
    if (tree) commit(mapNodes(main, (node) => withoutRunRepeatsOf(node).node));
    else draft.edit(repeats.document);
  };
  const variablesPanel = (
    <VariablesPanel
      document={document}
      environment={environment || null}
      environmentValues={environmentValues}
      kept={keptValues}
      usage={variableUsage}
      repeats={repeats.dropped}
      selected={variable}
      onSelect={setVariable}
      onEditInputs={() => {
        setSelected(null);
        setSettings(true);
      }}
      stepCount={everyNode.length}
      onKeepAll={
        environmentInfo
          ? async (names) => {
              for (const name of names) {
                const spec = declaredInputs.find(([key]) => key === name)?.[1];
                const fallback =
                  typeof spec === "object" && spec !== null && !Array.isArray(spec)
                    ? spec.default
                    : undefined;
                if (fallback === undefined) continue;
                await saveValue.mutateAsync({
                  environment,
                  name,
                  value: typeof fallback === "string" ? fallback : JSON.stringify(fallback),
                });
              }
              if (repeats.dropped > 0) dropRepeats();
              setToast(
                `Kept ${names.join(", ")} in ${environment}${repeats.dropped > 0 ? ` and removed ${String(repeats.dropped)} repeats` : ""}.`,
              );
            }
          : null
      }
      onRemoveRepeats={() => {
        dropRepeats();
        setToast(`Removed ${String(repeats.dropped)} repeats.`);
      }}
      onSaveValue={
        environmentInfo
          ? async (name, value) => {
              await saveValue.mutateAsync({ environment, name, value });
              setToast(
                value === null
                  ? `Removed ${name} from ${environment}.`
                  : `Saved ${name} in ${environment}.`,
              );
            }
          : null
      }
      onOpenEnvironments={() => {
        void navigate(environmentsPage(scenario.project));
      }}
      onOpenStep={(id) => {
        setSettings(false);
        setSelected(keyOf(id));
      }}
    />
  );

  // A press on a block of the Blocks tab: a drag drops it into the gap nearest the pointer
  // (a line shows where); a press that does not move adds it after the selected step.
  const pressBlock = (event: ReactPointerEvent, make: () => Item, look: BlockLook) => {
    if (event.button !== 0 || reviewProgram) return;
    event.preventDefault();
    const origin = { x: event.clientX, y: event.clientY };
    let moved = false;
    let target: InsertTarget | null = null;
    const made = make();
    // A stage lands between stages, any other block in a list of steps.
    const kind: GapKind = made.kind === "stage" ? "stage" : "step";
    const inList = (x: number) => {
      const box = listScroll.current?.getBoundingClientRect();
      return box !== undefined && x >= box.left && x <= box.right;
    };
    const move = (moving: PointerEvent) => {
      if (!moved && Math.hypot(moving.clientX - origin.x, moving.clientY - origin.y) < 4) return;
      moved = true;
      target = inList(moving.clientX)
        ? nearestGap(listScroll.current, moving.clientY, undefined, kind)
        : null;
      if (target) scrollNear(listScroll.current, moving.clientY);
      setPaletteDrag({ look, x: moving.clientX, y: moving.clientY, target });
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setPaletteDrag(null);
      if (!moved) addAtEnd(made);
      else if (target) {
        placeAt([made], target);
        setSettings(false);
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  // The row menu (right click, Shift F10, or a click on the handle): move, duplicate, delete.
  const rowMenuAt = rowMenu ? locate(main, rowMenu.id) : null;
  const rowMenuLength = rowMenuAt ? (listAt(main, rowMenuAt.slot)?.length ?? 0) : 0;
  const rowMenuStage = rowMenu ? findItem(main, rowMenu.id)?.kind === "stage" : false;
  const rowNoun = rowMenuStage ? "stage" : "step";
  const closeRowMenu = () => {
    setRowMenu(null);
  };
  const rowMenuView = rowMenu && (
    <>
      <div className="sb-menu-scrim" onClick={closeRowMenu} aria-hidden />
      <div
        className="ah-pop sb-row-menu"
        role="menu"
        aria-label={`${rowMenuStage ? "Stage" : "Step"} ${rowMenu.id}`}
        style={{
          top: Math.min(rowMenu.anchor.bottom + 4, window.innerHeight - 260),
          left: rowMenu.anchor.left,
        }}
      >
        <MenuItem
          icon="pencil"
          onClick={() => {
            setSettings(false);
            setSelected(rowMenu.id);
            closeRowMenu();
          }}
        >
          Open
        </MenuItem>
        {rowMenuAt && rowMenuAt.index > 0 && (
          <MenuItem
            icon="arrow-up"
            onClick={() => {
              moveTo(rowMenu.id, { slot: rowMenuAt.slot, index: rowMenuAt.index - 1 });
              closeRowMenu();
            }}
          >
            Move up
          </MenuItem>
        )}
        {rowMenuAt && rowMenuAt.index < rowMenuLength - 1 && (
          <MenuItem
            icon="arrow-down"
            onClick={() => {
              moveTo(rowMenu.id, { slot: rowMenuAt.slot, index: rowMenuAt.index + 2 });
              closeRowMenu();
            }}
          >
            Move down
          </MenuItem>
        )}
        {!rowMenuStage && (
          <MenuItem
            icon="copy"
            onClick={() => {
              duplicate(rowMenu.id);
              closeRowMenu();
            }}
          >
            Duplicate
          </MenuItem>
        )}
        <MenuItem
          icon="trash"
          onClick={() => {
            removeItem(rowMenu.id);
            setToast(
              rowMenuStage
                ? `Deleted stage ${rowMenu.id} and its steps.`
                : `Deleted step ${rowMenu.id}.`,
            );
            closeRowMenu();
          }}
        >
          Delete {rowNoun}
        </MenuItem>
      </div>
    </>
  );

  return (
    <div className="sb-root">
      <div className="sb-toolbar">
        <span className="sb-title">
          <b className="ah-mono">{scenario.name}</b>
          <span className="ah-small ah-muted">
            {scenario.pack} · rev{" "}
            {typeof document.revision === "number" ? document.revision : scenario.revision}
          </span>
        </span>
        <SegmentedControl
          label="View"
          value={view}
          onChange={(id) => {
            if (id === "run") onRun();
            else setView(id === "yaml" || id === "graph" ? id : "blocks");
          }}
          options={[
            { id: "blocks", label: "Blocks", icon: "puzzle" },
            { id: "graph", label: "Graph", icon: "workflow" },
            { id: "yaml", label: "YAML", icon: "file-text" },
            { id: "run", label: "Run", icon: "play" },
          ]}
        />
        <span className="sb-menu-anchor">
          <button
            type="button"
            className="sb-check"
            aria-haspopup="dialog"
            aria-expanded={menu === "problems"}
            onClick={() => {
              setMenu(menu === "problems" ? null : "problems");
            }}
          >
            {draft.check === null ? (
              <>
                <Icon name="circle-dashed" size="sm" /> Checking…
              </>
            ) : errors.length > 0 ? (
              <span style={{ color: "var(--failed)" }}>
                <Icon name="circle-x" size="sm" /> {errors.length}{" "}
                {errors.length === 1 ? "problem" : "problems"}
              </span>
            ) : (
              <>
                <Icon name="circle-check" size="sm" style={{ color: "var(--done)" }} /> Loads
                {drafts > 0 && (
                  <span className="ah-muted">
                    {" "}
                    · {drafts} draft {drafts === 1 ? "action" : "actions"}
                  </span>
                )}
              </>
            )}
            <Icon name="chevron-down" size="sm" />
          </button>
          {menu === "problems" && (
            <div className="ah-pop sb-pop" role="dialog" aria-label="Problems">
              {problems.length === 0 ? (
                <span className="ah-small ah-muted">The scenario loads. Nothing to fix.</span>
              ) : (
                problems.map((problem, index) => (
                  <button
                    key={index}
                    type="button"
                    className="sb-problem-row"
                    data-severity={problem.severity}
                    onClick={() => {
                      const at = problemAt(problem);
                      if (at) setSelected(at);
                      setMenu(null);
                    }}
                  >
                    <Icon
                      name={problem.severity === "error" ? "circle-x" : "circle-dashed"}
                      size="sm"
                    />
                    <span className="ah-grow">
                      {problemAt(problem) && <b className="ah-mono">{problemAt(problem)}: </b>}
                      {problem.message}
                    </span>
                  </button>
                ))
              )}
            </div>
          )}
        </span>
        <span className="ah-grow" />
        {draft.dirty && (
          <span className="ah-small ah-muted">
            <span className="sb-dot" aria-hidden /> Unsaved
          </span>
        )}
        {draft.saved && !draft.dirty && (
          <span className="ah-small ah-muted">Saved · rev {draft.saved.revision}</span>
        )}
        <IconButton
          icon="undo-2"
          label="Undo (⌘Z)"
          disabled={!draft.canUndo}
          onClick={draft.undo}
        />
        <IconButton icon="redo-2" label="Redo" disabled={!draft.canRedo} onClick={draft.redo} />
        <span className="sb-compact">
          <Button
            size="sm"
            icon="message-square"
            title="Describe with Claude"
            onClick={() => {
              setDescribing(true);
            }}
          >
            Describe with Claude
          </Button>
          <DiscussButton label="Chat" />
        </span>
        <Button
          variant="primary"
          icon="save"
          disabled={!draft.dirty || draft.saving || errors.length > 0 || draft.check === null}
          title={errors.length > 0 ? `Fix ${String(errors.length)} problems to save` : undefined}
          onClick={draft.save}
        >
          {draft.saving ? "Saving…" : "Save scenario"}
        </Button>
        <span className="sb-menu-anchor">
          <IconButton
            icon="ellipsis"
            label="More"
            onClick={() => {
              setMenu(menu === "more" ? null : "more");
            }}
          />
          {menu === "more" && (
            <div className="ah-pop sb-pop sb-pop-right" role="menu" aria-label="More">
              {draft.check && (
                <MenuItem
                  icon="copy"
                  onClick={() => {
                    void navigator.clipboard.writeText(draft.check?.yaml ?? "");
                    setMenu(null);
                  }}
                >
                  Copy the YAML
                </MenuItem>
              )}
              {!tree && (
                <MenuItem
                  icon="milestone"
                  onClick={() => {
                    setMenu(null);
                    setMigrating(true);
                  }}
                >
                  Migrate to stages of blocks
                </MenuItem>
              )}
            </div>
          )}
        </span>
      </div>
      <div className="sb-context">
        <label className="sb-env">
          <span className="ah-small ah-muted">Environment</span>
          <select
            className="ah-input"
            aria-label="Environment"
            value={environment}
            disabled={scenario.environments.length === 0}
            onChange={(event) => {
              setEnvironment(event.target.value);
            }}
          >
            {scenario.environments.length === 0 && <option value="">No environment</option>}
            {scenario.environments.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name} · {item.access}
                {item.production ? " · production" : ""}
              </option>
            ))}
          </select>
        </label>
        <span className="sb-menu-anchor">
          <Button
            size="sm"
            icon="list-checks"
            disabled={environment === "" || planner.isPending || draft.saving || errors.length > 0}
            title={
              errors.length > 0
                ? "Fix the problems first"
                : "Each action's script runs in plan mode, with no credential: nothing is changed."
            }
            onClick={() => {
              if (missingToPlan.length > 0) setMenu(menu === "preview" ? null : "preview");
              else planNow({});
            }}
          >
            {planner.isPending
              ? "Planning…"
              : draft.dirty
                ? "Save and plan"
                : `Plan in ${environment || "…"}`}
          </Button>
          {menu === "preview" && (
            <form
              className="ah-pop sb-pop sb-preview"
              aria-label="Values to plan with"
              onSubmit={(event) => {
                event.preventDefault();
                planNow(planValues);
              }}
            >
              <b className="ah-small">Values to plan with</b>
              <span className="ah-small ah-muted">
                Nothing gives these a value in {environment}. Nothing is changed by a plan.
              </span>
              {asksAtStart.map((name) => (
                <label key={name} className="ah-stack ah-small" style={{ gap: 4 }}>
                  {name}
                  <input
                    className="ah-input"
                    value={planValues[name] ?? ""}
                    onChange={(event) => {
                      setPlanValues({ ...planValues, [name]: event.target.value });
                    }}
                  />
                </label>
              ))}
              <span className="ah-row" style={{ gap: 6, justifyContent: "flex-end" }}>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setMenu(null);
                  }}
                >
                  Cancel
                </Button>
                <Button size="sm" variant="primary" type="submit">
                  {draft.dirty ? "Save and plan" : `Plan in ${environment}`}
                </Button>
              </span>
            </form>
          )}
        </span>
        {preview && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              planner.reset();
            }}
          >
            Clear plan
          </Button>
        )}
        {planner.error && (
          <span className="ah-small" style={{ color: "var(--failed)" }}>
            {planner.error.detail ?? planner.error.title}
          </span>
        )}
        <span className="ah-grow" />
      </div>
      {draft.saveError && (
        <Banner tone="error" boxed>
          Could not save: {draft.saveError.detail ?? draft.saveError.title}
        </Banner>
      )}
      {(awaiting || offered) && (
        <div className="sb-proposal" role="status">
          <Icon name="message-square" size="sm" />
          {offered ? (
            <>
              <span>
                <b>Claude proposes</b> {proposes}
                {proposedGraph &&
                  " · it is written as a graph (nodes), not as stages: accepting it all leaves no stage"}
                {offered.check
                  ? offered.check.loads
                    ? " · it loads"
                    : ` · ${String(offered.check.problems.filter((p) => p.severity === "error").length)} problems to fix after accepting`
                  : offered.problem
                    ? ` · ${offered.problem}`
                    : ""}
              </span>
              <span className="ah-grow" />
              <Button
                size="sm"
                variant={reviewing ? "primary" : "default"}
                onClick={() => {
                  setReviewing(!reviewing);
                  // The draft's and the proposal's rows are other blocks under the same keys.
                  setSelected(null);
                  setView("blocks");
                }}
              >
                {reviewing ? "Back to my draft" : "Review"}
              </Button>
              <Button size="sm" variant="primary" icon="check" onClick={acceptProposal}>
                Accept all
              </Button>
              <Button size="sm" variant="ghost" onClick={rejectProposal}>
                Reject all
              </Button>
            </>
          ) : (
            <>
              <span>
                Waiting for Claude&apos;s proposal… follow it in the Discuss panel; it shows here as
                suggested blocks when it is written.
              </span>
              <span className="ah-grow" />
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setAwaiting(false);
                }}
              >
                Stop waiting
              </Button>
            </>
          )}
        </div>
      )}
      {draft.conflict && (
        <Banner
          tone="warning"
          boxed
          action={
            <span className="ah-row" style={{ gap: 6 }}>
              <Button size="sm" onClick={draft.takeFile}>
                Load the file&apos;s version
              </Button>
              <Button size="sm" variant="ghost" onClick={draft.keepMine}>
                Keep mine
              </Button>
            </span>
          }
        >
          The scenario file changed outside the builder (Claude or an editor) while you had unsaved
          changes. Keep mine replaces the file&apos;s new version when you save.
        </Banner>
      )}
      {draft.restored && !draft.conflict && (
        <Banner
          tone="info"
          boxed
          live={false}
          action={
            <Button size="sm" variant="ghost" onClick={draft.discard}>
              Discard them
            </Button>
          }
        >
          Your unsaved changes came back from this browser. Save them, or discard them to see the
          file.
        </Banner>
      )}
      <div
        className="sb-body"
        data-panel={(reviewPanel ?? inspector) ? "open" : undefined}
        ref={bodyRef}
      >
        <aside className="sb-left" aria-label="Blocks, variables and actions">
          <Tabs
            label="Left column"
            value={leftTab}
            onChange={(id) => {
              setLeftTab(
                id === "actions" ? "actions" : id === "variables" ? "variables" : "blocks",
              );
            }}
            tabs={[
              { id: "blocks", label: "Blocks" },
              { id: "variables", label: "Variables" },
              { id: "actions", label: "Actions", count: items.length },
            ]}
          />
          {leftTab === "blocks" ? (
            <BlocksTab
              library={items}
              pack={scenario.pack}
              taken={taken}
              where={
                tree && selected && stageOf(selected)?.key === selected
                  ? `at the end of stage ${selected}`
                  : selected && locate(main, selected)
                    ? `after step ${numbersNow.get(selected) ?? selected}`
                    : "at the end"
              }
              locked={underReview}
              onAdd={addAtEnd}
              onPress={pressBlock}
              stages={
                tree
                  ? {
                      names: main.flatMap((item) => (item.kind === "stage" ? [item.name] : [])),
                      where: stageOf(selected)
                        ? `after stage ${stageOf(selected)?.key ?? ""}`
                        : "at the end",
                    }
                  : null
              }
            />
          ) : leftTab === "variables" ? (
            variablesPanel
          ) : (
            <ActionsTab
              library={items}
              libraryError={library.isError}
              usage={actionUsage}
              onOpen={(item, opener) => {
                actionOpener.current = opener;
                setActionPanel(item.action.ref);
              }}
              onNewAction={() => {
                setNewAction({ node: null, readOnly: false });
              }}
              onAskAction={() => {
                setAskingAction({ step: null, readOnly: false });
              }}
            />
          )}
        </aside>
        <div className="sb-stage">
          {view === "blocks" && (
            <StepList
              scrollRef={listScroll}
              externalTarget={paletteDrag?.target ?? null}
              empty={
                kept.length === 0 && !reviewProgram ? (
                  <StartCard
                    onDescribe={() => {
                      setDescribing(true);
                    }}
                    onTemplate={(items_) => {
                      // Written as blocks, a shape starts the first stage.
                      commit(tree ? asNew([{ ...newStage([]), steps: items_ }]) : items_);
                    }}
                    taken={taken}
                  />
                ) : null
              }
              scenarioName={scenario.name}
              items={reviewProgram ?? main}
              numbers={stepNumbers(reviewProgram ?? main)}
              selected={selected}
              actionOf={actionFacts}
              problemsOf={tree && reviewProgram ? () => [] : problemsOf}
              // The plan was made for the draft's blocks: a proposal's, by its own addresses,
              // are other blocks, so none shows one.
              planOf={
                tree && reviewProgram ? () => null : (id) => planRows.get(nodeIdOf(id)) ?? null
              }
              planStale={previewFor !== null && previewFor !== JSON.stringify(document.nodes)}
              start={{
                environment: environment || null,
                asks: asksAtStart,
                selected: settings && !selectedItem,
              }}
              onStart={() => {
                setSelected(null);
                setSettings(true);
              }}
              onSelect={(id) => {
                setSettings(false);
                setSelected(id);
              }}
              onInsert={(target, anchor, label) => {
                if (reviewProgram) return;
                setInserting({ target, anchor, where: label });
              }}
              onMove={moveTo}
              onRowMenu={(id, anchor) => {
                if (reviewProgram) return;
                setRowMenu({ id, anchor });
              }}
              variable={variable}
              usesVariable={(node) => (variable ? nodeUses(node, variable) : false)}
              suggested={reviewProgram ? suggestedIds : undefined}
              readOnly={reviewProgram !== null}
              loose={kept}
              onInsertStage={tree ? insertStage : undefined}
              onOpenYaml={() => {
                setView("yaml");
              }}
              footer={
                help ? (
                  <div className="sb-hint" role="note">
                    <span>
                      Drag a block from the left into the list, or click one to add it after the
                      selected step. Steps run top to bottom; drag a step&apos;s handle or press Alt
                      ↑ / Alt ↓ to move it.
                    </span>
                    <Button
                      size="sm"
                      onClick={() => {
                        setHelp(false);
                        writeStored(HELP_KEY, "hidden");
                      }}
                    >
                      Got it
                    </Button>
                  </div>
                ) : null
              }
            />
          )}
          {view === "graph" && !tree && (
            <FlowCanvas
              nodes={document.nodes}
              actionOf={actionFacts}
              problemsOf={(id) => problems.filter((problem) => problem.node === id)}
              selected={selected}
              onSelect={setSelected}
              onAdd={onGraphAdd}
            />
          )}
          {view === "graph" && tree && (
            <div className="sb-graph-picture">
              <span className="ah-small ah-muted" role="note">
                The graph shows how the blocks run: edit them in Blocks.
              </span>
              <FlowCanvas
                nodes={document.nodes}
                actionOf={actionFacts}
                problemsOf={(id) => problemsOf(keyOf(id))}
                selected={selected ? nodeIdOf(selected) : null}
                onSelect={(id) => {
                  setSelected(id === null ? null : keyOf(id));
                }}
                onAdd={() => undefined}
                readOnly
              />
            </div>
          )}
          {view === "yaml" && (
            <div className="sb-yaml">
              <div className="ah-row" style={{ gap: 8 }}>
                <span className="ah-small ah-muted">
                  Generated from the blocks: exactly what Save writes
                  {draft.dirty ? " (not saved yet)" : ""}.
                </span>
                <span className="ah-grow" />
                {draft.check && <CopyButton text={draft.check.yaml} label="Copy the YAML" />}
                <Button
                  size="sm"
                  icon="message-square"
                  disabled={draft.dirty}
                  title={draft.dirty ? "Save first, so Claude edits what you see." : undefined}
                  onClick={() => {
                    setOpen(true);
                  }}
                >
                  Edit with Claude
                </Button>
              </div>
              {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a scrollable region */}
              <pre className="ah-json sb-yaml-text" tabIndex={0} aria-label="Generated YAML">
                {draft.check?.yaml ?? ""}
              </pre>
            </div>
          )}
        </div>
        {reviewPanel ?? inspector}
      </div>
      {migrating && (
        <MigrateDialog
          project={scenario.project}
          name={scenario.name}
          contentHash={fresh.content_hash ?? null}
          unsaved={draft.dirty}
          onClose={() => {
            setMigrating(false);
          }}
        />
      )}
      {describing && (
        <DescribeDialog
          empty={main.length === 0}
          after={editable}
          tree={tree}
          onSend={(described, scope) => {
            sendDescription(described, scope, scope === "after" ? editable : null);
          }}
          onClose={() => {
            setDescribing(false);
          }}
        />
      )}
      {askingAction && (
        <AskActionDialog
          onSend={(described) => {
            ask(
              createActionMessage({
                text: described,
                pack: scenario.pack,
                step: askingAction.step,
                readOnly: askingAction.readOnly,
                tree,
              }),
            );
            setAskingAction(null);
          }}
          onClose={() => {
            setAskingAction(null);
          }}
        />
      )}
      {actionPanel &&
        (() => {
          const shownAction = items.find((item) => item.action.ref === actionPanel)?.action;
          if (!shownAction) return null;
          return (
            <ActionPanel
              action={shownAction}
              steps={programNodes(main).map((node) => ({
                id: node.id,
                type: node.type,
                action: typeof node.action === "string" ? node.action : null,
                depends_on: [],
              }))}
              openerRef={actionOpener}
              onClose={() => {
                setActionPanel(null);
              }}
              onShowStep={(id) => {
                setSelected(keyOf(id));
                setActionPanel(null);
              }}
              tools={
                <>
                  <Button
                    size="sm"
                    icon="pencil"
                    onClick={() => {
                      setNewAction({ node: null, readOnly: false, existing: shownAction });
                      setActionPanel(null);
                    }}
                  >
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant="primary"
                    icon="plus"
                    // Under review the draft is not edited (the Blocks tab says so).
                    disabled={underReview}
                    onClick={() => {
                      const ref =
                        shownAction.pack === scenario.pack ? shownAction.name : shownAction.ref;
                      addAtEnd(blockItem(taken, "action", ref));
                      setActionPanel(null);
                    }}
                  >
                    Add to the scenario
                  </Button>
                </>
              }
            />
          );
        })()}
      {newAction && (
        <NewActionDialog
          project={scenario.project}
          pack={scenario.pack}
          existing={newAction.existing ?? null}
          readOnly={newAction.readOnly}
          onCreated={(action) => {
            const key = newAction.node;
            const target = key ? findItem(allItems, key) : null;
            if (key && target?.kind === "block")
              editNode(key, { ...target.node, action: action.name });
            setNewAction(null);
          }}
          onClose={() => {
            setNewAction(null);
          }}
        />
      )}
      {toast && (
        <div className="sb-toast">
          <Toast
            onUndo={() => {
              draft.undo();
              setToast(null);
            }}
          >
            {toast}
          </Toast>
        </div>
      )}
      {rowMenuView}
      {paletteDrag && (
        <div
          className="sb-pal-ghost"
          aria-hidden
          data-over={paletteDrag.target ? "list" : undefined}
          style={{
            left: paletteDrag.x + 12,
            top: paletteDrag.y + 8,
            ["--tile" as string]: paletteDrag.look.tint,
            ["--tile-soft" as string]: paletteDrag.look.soft,
          }}
        >
          <span className="sb-pal-tile">
            <Icon name={paletteDrag.look.icon} size="sm" />
          </span>
          {paletteDrag.look.label}
        </div>
      )}
      <span className="ah-sr" role="status" aria-live="polite">
        {announce}
      </span>
      {inserting && (
        <InsertMenu
          anchor={inserting.anchor}
          where={inserting.where}
          library={items}
          pack={scenario.pack}
          taken={taken}
          onPick={insertHere}
          onAskClaude={(described) => {
            const before = inserting.where.startsWith("after ") ? inserting.where.slice(6) : null;
            sendDescription(described, "after", before);
            setInserting(null);
          }}
          onClose={() => {
            setInserting(null);
          }}
          onNewAction={() => {
            setInserting(null);
            setNewAction({ node: null, readOnly: false });
          }}
          onAskAction={() => {
            setInserting(null);
            setAskingAction({ step: null, readOnly: false });
          }}
        />
      )}
    </div>
  );
}
