import "./builder.css";
import "./blocks.css";
import "./steps.css";

import { useEffect, useRef, useState, type RefObject } from "react";
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
import { StepList, type InsertTarget } from "./StepList";
import { VariablesPanel, type KeptValue } from "./VariablesPanel";
import { InsertMenu } from "./InsertMenu";
import { createActionMessage, describeMessage, type DescribeScope } from "./claude";
import {
  AskActionDialog,
  DescribeDialog,
  NewActionDialog,
  useDismissProposal,
  useProposal,
} from "./ClaudeDialogs";
import { StartCard } from "./StartCard";
import { ActionPanel } from "../ActionPanel";
import { blockItem } from "./palette";
import { FlowCanvas, kindLook, type AddChoice } from "./FlowCanvas";
import { BlockInspector, GroupInspector, ScenarioSettings } from "./Inspector";
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
  type BuilderDocument,
  type BuilderNode,
} from "./model";
import {
  findItem,
  insertAt,
  listAt,
  itemId,
  locate,
  stepNumbers,
  nodesOf,
  programNodes,
  programOf,
  replaceItem,
  takeFrom,
  type Item,
} from "./program";
import { useActionLibrary, useScenarioDraft, type LibraryAction } from "./useScenarioDraft";

/* The scenario builder (Build mode of the scenario page, v6). Its main view is the step list:
 * the scenario read top to bottom, a numbered row per step, Repeat / If / At the same time as
 * indented groups. On the left, the Variables (where every value comes from) and the Actions of
 * the hub; on the right, the editor of the selected step. Graph shows the same flow as connected
 * nodes, and YAML the file Save writes. The list is a reading of the document: every edit
 * rewrites the scenario's `nodes`, which the server checks a moment later. */

type View = "blocks" | "graph" | "yaml";

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
  const draft = useScenarioDraft({
    project: scenario.project,
    name: scenario.name,
    pack: scenario.pack,
    initial: toDocument(fresh.document),
    contentHash: fresh.content_hash ?? null,
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
  const [planValues, setPlanValues] = useState<Record<string, string>>({});
  const [planAfterSave, setPlanAfterSave] = useState<Record<string, string> | null>(null);
  const [leftTab, setLeftTab] = useState<"variables" | "actions">("variables");
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
  const [resolved, setResolved] = useState<Set<string>>(() => new Set());
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
  const { ask } = useDiscuss();
  const navigate = useNavigate();
  const saveValue = useSaveEnvironmentValue(scenario.project);
  const proposal = useProposal(scenario.project, scenario.name, awaiting);
  const dismiss = useDismissProposal(scenario.project, scenario.name);
  const offered = proposal.data?.document ? proposal.data : null;
  if (awaiting && offered) setAwaiting(false);
  useEffect(() => {
    if (toast === null) return;
    const timer = setTimeout(() => {
      setToast(null);
    }, 6000);
    return () => {
      clearTimeout(timer);
    };
  }, [toast]);
  const document = draft.document;

  // The program, read again whenever the document changes from elsewhere (undo, the graph).
  const [synced, setSynced] = useState("");
  const [program, setProgram] = useState<{ main: Item[]; kept: BuilderNode[] }>({
    main: [],
    kept: [],
  });
  const nodesText = JSON.stringify(document.nodes);
  if (synced !== nodesText) {
    const read = programOf(document.nodes);
    setSynced(nodesText);
    setProgram({ main: read.main, kept: read.loose });
  }

  // Writes the list back to the scenario's nodes (steps the list cannot place stay as written).
  const commit = (main: Item[], kept: BuilderNode[] = program.kept) => {
    const nodes = [...nodesOf(main), ...kept];
    setProgram({ main, kept });
    const text = JSON.stringify(nodes);
    setSynced(text);
    if (text !== nodesText) draft.edit({ ...document, nodes });
  };

  const allItems: Item[] = [
    ...program.main,
    ...program.kept.map((node): Item => ({ kind: "block", node })),
  ];
  const taken: BuilderDocument = { ...document, nodes: programNodes(allItems) };

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

  // Puts `moved` at a place of the list.
  const placeAt = (moved: Item[], target: InsertTarget) => {
    const first = moved[0];
    if (first) setSelected(itemId(first));
    commit(insertAt(program.main, target.slot, target.index, moved));
  };

  // Moves the step `id` to a gap of the list (by its handle, or the row menu).
  const moveTo = (id: string, target: InsertTarget) => {
    const from = locate(program.main, id);
    if (!from) return;
    const { rest, taken: moved } = takeFrom(program.main, id, true);
    if (moved.length === 0) return;
    const sameList = JSON.stringify(from.slot) === JSON.stringify(target.slot);
    const index = sameList && target.index > from.index ? target.index - 1 : target.index;
    if (sameList && index === from.index) return;
    commit(insertAt(rest, target.slot, index, moved));
    setSelected(id);
    setAnnounce(`Moved step ${id} to position ${String(index + 1)}.`);
  };

  // A click on the palette adds after the selected block (in its list), else at the end.
  const addAtEnd = (item: Item) => {
    const at = selected ? locate(program.main, selected) : null;
    const main = at
      ? insertAt(program.main, at.slot, at.index + 1, [item])
      : [...program.main, item];
    commit(main);
    setSelected(itemId(item));
  };
  const insertHere = (item: Item) => {
    if (!inserting) return;
    placeAt([item], inserting.target);
    setInserting(null);
  };

  const editItem = (id: string, next: Item) => {
    commit(
      replaceItem(program.main, id, next),
      program.kept.map((node) => (node.id === id && next.kind === "block" ? next.node : node)),
    );
  };

  const editNode = (node: BuilderNode) => {
    const current = findItem(allItems, node.id);
    if (current?.kind === "repeat") editItem(node.id, { ...current, node });
    else editItem(node.id, { kind: "block", node });
  };

  const removeItem = (id: string) => {
    commit(
      takeFrom(program.main, id, true).rest,
      program.kept.filter((node) => node.id !== id),
    );
    setSelected(null);
  };

  // A copy of the step right after it (a fresh id; a group is not copied).
  const duplicate = (id: string) => {
    const item = findItem(program.main, id);
    const at = locate(program.main, id);
    if (item?.kind !== "block" || !at) return;
    const copy: Item = {
      kind: "block",
      node: { ...item.node, id: freshId(taken, item.node.id) },
    };
    commit(insertAt(program.main, at.slot, at.index + 1, [copy]));
    setSelected(itemId(copy));
    setAnnounce(`Duplicated step ${id}.`);
  };

  const selectedItem = selected ? findItem(allItems, selected) : null;
  const serialized: BuilderDocument = {
    ...document,
    nodes: [...nodesOf(program.main), ...program.kept],
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
          ask(
            `About the step \`${id}\` of the scenario \`${scenario.name}\` (the file \`${scenario.path ?? ""}\`): explain in a few lines what it does, what it runs and where it can stop. Change nothing.`,
          );
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
  // How many steps take each scenario input as the run's value (left out, or only repeated).
  const runValueUsage: Record<string, number> = {};
  const runNames = new Set(
    typeof document.inputs === "object" &&
      document.inputs !== null &&
      !Array.isArray(document.inputs)
      ? Object.keys(document.inputs)
      : [],
  );
  for (const node of allNodes(document.nodes)) {
    const facts = actionFacts(node);
    if (!facts) continue;
    const given =
      typeof node.with === "object" && node.with !== null && !Array.isArray(node.with)
        ? node.with
        : {};
    for (const input of facts.inputs) {
      const value = given[input.name];
      if (runNames.has(input.name) && (value === undefined || value === `$INPUTS.${input.name}`))
        runValueUsage[input.name] = (runValueUsage[input.name] ?? 0) + 1;
    }
  }
  const hatButton: RefObject<HTMLElement | null> = {
    get current() {
      return globalThis.document.querySelector<HTMLElement>(".bk-hat");
    },
  };
  const inspector = (() => {
    if (!selectedItem) {
      return settings ? (
        <ScenarioSettings
          document={document}
          onChange={draft.edit}
          openerRef={hatButton}
          usage={runValueUsage}
          onClose={() => {
            setSettings(false);
          }}
        />
      ) : null;
    }
    if (selectedItem.kind === "block" || selectedItem.kind === "repeat") {
      // The block as it is written (with the `depends_on` its place in the stack gives it).
      const written = allNodes(serialized.nodes).find((item) => item.id === selectedItem.node.id);
      const base = written ? { ...selectedItem.node, ...written } : selectedItem.node;
      const node =
        selectedItem.kind === "repeat" ? { ...base, nodes: nodesOf(selectedItem.body) } : base;
      return (
        <BlockInspector
          key={node.id}
          document={serialized}
          node={node}
          library={items}
          problems={problems.filter((problem) => problem.node === node.id)}
          mode={mode}
          number={stepNumbers(program.main).get(node.id)}
          libraryError={library.isError}
          openerRef={selectedCard}
          onOpenAction={setActionPanel}
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
                  setNewAction({ node: node.id, readOnly: node.type === "expect" });
                }}
              >
                New action
              </Button>
              <Button
                size="sm"
                variant="ghost"
                icon="message-square"
                onClick={() => {
                  setAskingAction({ step: node.id, readOnly: node.type === "expect" });
                }}
              >
                Ask Claude to write one
              </Button>
            </>
          }
          onChange={(next) => {
            if (next.id !== node.id) {
              draft.edit(updateBlock(serialized, node.id, next));
              setSelected(next.id);
              return;
            }
            if (selectedItem.kind === "repeat") {
              editItem(node.id, { ...selectedItem, node: without(next, "nodes") });
            } else editItem(node.id, { kind: "block", node: next });
          }}
          footer={stepButtons(node.id)}
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
        number={stepNumbers(program.main).get(groupId)}
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
      }),
    );
    setAwaiting(true);
    setDescribing(false);
  };
  const proposed = offered?.document ? toDocument(offered.document) : null;
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
  const open = changes.filter((change) => !resolved.has(change.id));
  const suggestedIds = new Set(
    open
      .filter((change) => change.kind !== "removed")
      .flatMap((change) => allNodes([change.node]).map((node) => node.id)),
  );
  const removedCount = open.filter((change) => change.kind === "removed").length;
  const finish = (next: Set<string>) => {
    if (changes.every((change) => next.has(change.id))) {
      setReviewing(false);
      setResolved(new Set());
      dismiss.mutate();
    } else setResolved(next);
  };
  const acceptOne = (id: string) => {
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
    finish(new Set([...resolved, id]));
  };
  const acceptProposal = () => {
    if (!proposed) return;
    const next: BuilderDocument = { ...document, nodes: proposed.nodes };
    if (proposed.inputs !== undefined) next.inputs = proposed.inputs;
    if (typeof proposed.description === "string") next.description = proposed.description;
    draft.edit(next);
    setReviewing(false);
    setResolved(new Set());
    dismiss.mutate();
  };
  const reviewPanel =
    reviewing && proposed ? (
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
                <b className="ah-mono">{change.id}</b>
                <span className="ah-small ah-muted">
                  {kindLook(change.node.type).label}
                  {typeof change.node.action === "string" ? ` · ${change.node.action}` : ""}
                  {typeof change.node.description === "string"
                    ? ` · ${change.node.description}`
                    : ""}
                </span>
              </span>
              <span className="ah-row" style={{ gap: 4 }}>
                <Button
                  size="sm"
                  variant="primary"
                  aria-label={`Accept ${change.id}`}
                  onClick={() => {
                    acceptOne(change.id);
                  }}
                >
                  Accept
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Reject ${change.id}`}
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
  const reviewProgram = proposed && reviewing ? programOf(proposed.nodes).main : null;

  // Keys on the builder (never while typing in a field): Delete removes the selected block (with
  // an Undo toast), Alt+↑/↓ moves it in its list, ⌘D duplicates it, ⌘Z/⇧⌘Z undo and redo, ⌘S
  // saves, Esc clears the selection.
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
    } else if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      removeItem(selected);
      setToast(`Deleted ${selected}.`);
    } else if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
      event.preventDefault();
      const at = locate(program.main, selected);
      if (!at) return;
      const to = at.index + (event.key === "ArrowUp" ? -1 : 1);
      const { rest, taken: moved } = takeFrom(program.main, selected, true);
      if (to < 0 || moved.length === 0) return;
      commit(insertAt(rest, at.slot, to, moved));
    } else if (mod && event.key.toLowerCase() === "d") {
      event.preventDefault();
      const item = findItem(program.main, selected);
      const at = locate(program.main, selected);
      if (item?.kind !== "block" || !at) return;
      const copy: Item = {
        kind: "block",
        node: { ...item.node, id: freshId(taken, item.node.id) },
      };
      commit(insertAt(program.main, at.slot, at.index + 1, [copy]));
      setSelected(itemId(copy));
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
    programNodes(program.main)
      .map((node) => actionFacts(node))
      .filter((action) => action?.draft === true)
      .map((action) => action?.ref),
  ).size;

  // Where values come from, in the chosen environment.
  const environmentInfo = scenario.environments.find((item) => item.name === environment) ?? null;
  const environmentValues: Record<string, string> | null = environmentInfo
    ? (environmentInfo.values ?? {})
    : null;
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
  const numbersNow = stepNumbers(program.main);
  const keptValues: KeptValue[] = everyNode.flatMap((node) =>
    Object.keys(
      typeof node.capture === "object" && node.capture !== null && !Array.isArray(node.capture)
        ? node.capture
        : {},
    ).map((name) => ({ name, step: node.id, number: numbersNow.get(node.id) ?? node.id })),
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
      onRemoveRepeats={() => {
        draft.edit(repeats.document);
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
        setSelected(id);
      }}
    />
  );

  // The row menu (right click, Shift F10, or a click on the handle): move, duplicate, delete.
  const rowMenuAt = rowMenu ? locate(program.main, rowMenu.id) : null;
  const rowMenuLength = rowMenuAt ? (listAt(program.main, rowMenuAt.slot)?.length ?? 0) : 0;
  const closeRowMenu = () => {
    setRowMenu(null);
  };
  const rowMenuView = rowMenu && (
    <>
      <div className="sb-menu-scrim" onClick={closeRowMenu} aria-hidden />
      <div
        className="ah-pop sb-row-menu"
        role="menu"
        aria-label={`Step ${rowMenu.id}`}
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
        <MenuItem
          icon="copy"
          onClick={() => {
            duplicate(rowMenu.id);
            closeRowMenu();
          }}
        >
          Duplicate
        </MenuItem>
        <MenuItem
          icon="trash"
          onClick={() => {
            removeItem(rowMenu.id);
            setToast(`Deleted step ${rowMenu.id}.`);
            closeRowMenu();
          }}
        >
          Delete step
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
                      if (problem.node) setSelected(problem.node);
                      setMenu(null);
                    }}
                  >
                    <Icon
                      name={problem.severity === "error" ? "circle-x" : "circle-dashed"}
                      size="sm"
                    />
                    <span className="ah-grow">
                      {problem.node && <b className="ah-mono">{problem.node}: </b>}
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
        <Button
          size="sm"
          icon="message-square"
          onClick={() => {
            setDescribing(true);
          }}
        >
          Describe with Claude
        </Button>
        <DiscussButton label="Chat" />
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
              {missingToPlan.map((name) => (
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
        {environmentInfo && (
          <span className="ah-small ah-muted">
            {Object.keys(environmentValues ?? {}).length > 0
              ? `${String(Object.keys(environmentValues ?? {}).length)} values from ${environment} fill the steps`
              : `${environment} has no values yet: add them in Variables`}
          </span>
        )}
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
                <b>Claude proposes</b> {open.length - removedCount} new or changed{" "}
                {open.length - removedCount === 1 ? "block" : "blocks"}
                {removedCount > 0 && `, ${String(removedCount)} removed`}
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
                  setView("blocks");
                }}
              >
                {reviewing ? "Back to my draft" : "Review"}
              </Button>
              <Button size="sm" variant="primary" icon="check" onClick={acceptProposal}>
                Accept all
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setReviewing(false);
                  setResolved(new Set());
                  dismiss.mutate();
                }}
              >
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
        <aside className="sb-left" aria-label="Variables and actions">
          <Tabs
            label="Left column"
            value={leftTab}
            onChange={(id) => {
              setLeftTab(id === "actions" ? "actions" : "variables");
            }}
            tabs={[
              { id: "variables", label: "Variables", icon: "braces" },
              { id: "actions", label: "Actions", icon: "circle-play", count: items.length },
            ]}
          />
          {leftTab === "variables" ? (
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
          {view === "blocks" &&
            program.main.length === 0 &&
            program.kept.length === 0 &&
            !reviewProgram && (
              <StartCard
                onDescribe={() => {
                  setDescribing(true);
                }}
                onTemplate={(items_) => {
                  commit(items_);
                }}
                taken={taken}
              />
            )}
          {view === "blocks" && (program.main.length > 0 || reviewProgram) && (
            <StepList
              scenarioName={scenario.name}
              items={reviewProgram ?? program.main}
              numbers={stepNumbers(reviewProgram ?? program.main)}
              selected={selected}
              actionOf={actionFacts}
              problemsOf={(id) => problems.filter((problem) => problem.node === id)}
              planOf={(id) => planRows.get(id) ?? null}
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
              loose={program.kept}
              onOpenYaml={() => {
                setView("yaml");
              }}
              footer={
                help ? (
                  <div className="sb-hint" role="note">
                    <span>
                      Steps run top to bottom, each after the one above. Drag the handle or press
                      Alt ↑ / Alt ↓ to move one; the + between two steps adds one there.
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
          {view === "graph" && (
            <FlowCanvas
              nodes={document.nodes}
              actionOf={actionFacts}
              problemsOf={(id) => problems.filter((problem) => problem.node === id)}
              selected={selected}
              onSelect={setSelected}
              onAdd={onGraphAdd}
            />
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
      {describing && (
        <DescribeDialog
          empty={program.main.length === 0}
          after={selected}
          onSend={(described, scope) => {
            sendDescription(described, scope, scope === "after" ? selected : null);
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
              steps={programNodes(program.main).map((node) => ({
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
                setSelected(id);
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
            const target = newAction.node ? findItem(allItems, newAction.node) : null;
            if (target?.kind === "block") editNode({ ...target.node, action: action.name });
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
        />
      )}
    </div>
  );
}
