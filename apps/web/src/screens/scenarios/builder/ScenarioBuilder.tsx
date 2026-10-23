import "./builder.css";
import "./blocks.css";

import { useState, type PointerEvent as ReactPointerEvent } from "react";

import {
  Banner,
  Button,
  CopyButton,
  Icon,
  SegmentedControl,
  type IconName,
} from "../../../components";
import { readStored, writeStored } from "../../../lib/storage";
import { useDiscuss } from "../../../shell/discuss";
import { EffectBadge } from "../parts";
import { useScenario, type ScenarioAction, type ScenarioDetail } from "../queries";
import { BlockCanvas, type DragState, type DropTarget, type Stack } from "./BlockCanvas";
import { FlowCanvas, kindLook, type AddChoice } from "./FlowCanvas";
import { BlockInspector, ConditionBuilder, ScenarioSettings } from "./Inspector";
import {
  insertAfter,
  insertBranch,
  newBlock,
  toDocument,
  updateBlock,
  valueSources,
  without,
  type BlockKind,
  type BuilderDocument,
  type BuilderNode,
} from "./model";
import {
  findItem,
  freshKey,
  insertAt,
  itemId,
  nodesOf,
  programNodes,
  programOf,
  replaceItem,
  takeFrom,
  type Item,
} from "./program";
import { useActionLibrary, useScenarioDraft, type LibraryAction } from "./useScenarioDraft";

/* The scenario builder (Build mode of the scenario page). Its main view is the block canvas
 * (Scratch-like stacks and C-blocks you drag and snap); Graph shows the same flow as connected
 * nodes, and YAML the file Save writes. The program is a reading of the document: every snap
 * rewrites the scenario's `nodes`, which the server checks a moment later. */

type View = "blocks" | "graph" | "yaml";

const FILE_POLL_MS = 4000;

interface PaletteEntry {
  key: string;
  label: string;
  hint: string;
  icon: IconName;
  tint: string;
  make: (taken: BuilderDocument) => Item;
}

function blockItem(document: BuilderDocument, kind: BlockKind, action?: string): Item {
  const node = newBlock(document, kind, action);
  if (kind === "loop_group") return { kind: "repeat", node: without(node, "nodes"), body: [] };
  return { kind: "block", node };
}

const CATEGORIES: readonly { title: string; entries: readonly PaletteEntry[] }[] = [
  {
    title: "Do",
    entries: [
      {
        key: "action",
        label: "run an action",
        hint: "A script, once",
        icon: "circle-play",
        tint: kindLook("action").tint,
        make: (d) => blockItem(d, "action"),
      },
      {
        key: "include",
        label: "run a scenario",
        hint: "Reuse another one",
        icon: "layers",
        tint: kindLook("include").tint,
        make: (d) => blockItem(d, "include"),
      },
    ],
  },
  {
    title: "Check",
    entries: [
      {
        key: "expect",
        label: "wait until …",
        hint: "Read until a state holds",
        icon: "timer",
        tint: kindLook("expect").tint,
        make: (d) => blockItem(d, "expect"),
      },
      {
        key: "wait",
        label: "wait 30s",
        hint: "A set time",
        icon: "hourglass",
        tint: kindLook("wait").tint,
        make: (d) => blockItem(d, "wait"),
      },
    ],
  },
  {
    title: "Control",
    entries: [
      {
        key: "repeat",
        label: "repeat until …",
        hint: "Rounds until done",
        icon: "refresh-cw",
        tint: kindLook("loop_group").tint,
        make: (d) => blockItem(d, "loop_group"),
      },
      {
        key: "if",
        label: "if … else",
        hint: "Take one path",
        icon: "split",
        tint: "var(--ev-decision)",
        make: () => ({ kind: "if", key: freshKey("if"), condition: "", then: [], otherwise: [] }),
      },
      {
        key: "parallel",
        label: "at the same time",
        hint: "Paths side by side",
        icon: "git-branch",
        tint: "var(--ev-reasoning)",
        make: () => ({ kind: "parallel", key: freshKey("together"), lanes: [[], []] }),
      },
    ],
  },
  {
    title: "You",
    entries: [
      {
        key: "approval",
        label: "ask me to …",
        hint: "A step by hand",
        icon: "stamp",
        tint: kindLook("approval").tint,
        make: (d) => blockItem(d, "approval"),
      },
    ],
  },
];

function startPaletteDrag(
  event: ReactPointerEvent,
  make: () => Item,
  onDrag: (drag: DragState) => void,
  onClick: () => void,
) {
  if (event.button !== 0) return;
  const start = { x: event.clientX, y: event.clientY };
  const move = (moved: PointerEvent) => {
    if (Math.hypot(moved.clientX - start.x, moved.clientY - start.y) < 4) return;
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    onDrag({
      items: [make()],
      grab: { x: 24, y: 16 },
      client: { x: moved.clientX, y: moved.clientY },
      target: null,
    });
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    onClick();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up, { once: true });
}

function Palette({
  library,
  pack,
  taken,
  onDrag,
  onAdd,
}: {
  library: readonly LibraryAction[];
  pack: string;
  taken: BuilderDocument;
  onDrag: (drag: DragState) => void;
  onAdd: (item: Item) => void;
}) {
  const [query, setQuery] = useState("");
  const shown = library.filter((item) =>
    `${item.action.ref} ${item.action.description ?? ""}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const refOf = (item: LibraryAction) =>
    item.action.pack === pack ? item.action.name : item.action.ref;
  return (
    <aside className="sb-palette" aria-label="Blocks">
      <span className="ah-small ah-muted">
        Drag a block onto the canvas, or click to add it at the end.
      </span>
      {CATEGORIES.map((category) => (
        <div key={category.title} className="ah-stack" style={{ gap: 4 }}>
          <span className="ah-overline">{category.title}</span>
          {category.entries.map((entry) => (
            <button
              key={entry.key}
              type="button"
              className="bk-palette-block"
              style={{ ["--kind" as string]: entry.tint }}
              onPointerDown={(event) => {
                startPaletteDrag(
                  event,
                  () => entry.make(taken),
                  onDrag,
                  () => {
                    onAdd(entry.make(taken));
                  },
                );
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onAdd(entry.make(taken));
                }
              }}
              aria-label={`Add block: ${entry.label}`}
            >
              <Icon name={entry.icon} size="sm" />
              <span className="ah-stack" style={{ gap: 0 }}>
                <b>{entry.label}</b>
                <span className="bk-palette-hint">{entry.hint}</span>
              </span>
            </button>
          ))}
        </div>
      ))}
      <span className="ah-overline">Actions in this hub</span>
      <input
        className="ah-input"
        aria-label="Find an action"
        placeholder="Find an action"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
      />
      {library.length === 0 && (
        <span className="ah-small ah-subtle">
          No actions yet: an action is a script in actions/&lt;pack&gt;/.
        </span>
      )}
      {shown.map((item) => {
        const asCheck = item.action.effect === "read";
        return (
          <button
            key={item.action.ref}
            type="button"
            className="bk-palette-action"
            style={{ ["--kind" as string]: kindLook("action").tint }}
            title={`${item.action.description ?? ""}${asCheck ? "\nShift: add as a check" : ""}`}
            aria-label={`Add action ${item.action.name}`}
            onPointerDown={(event) => {
              const check = asCheck && event.shiftKey;
              const make = () => blockItem(taken, check ? "expect" : "action", refOf(item));
              startPaletteDrag(event, make, onDrag, () => {
                onAdd(make());
              });
            }}
          >
            <Icon name="circle-play" size="sm" />
            <span className="ah-mono">{item.action.name}</span>
            <span className="ah-grow" />
            <EffectBadge effect={item.action.effect} />
          </button>
        );
      })}
    </aside>
  );
}

interface Layout {
  main: { x: number; y: number };
  loose: Stack[];
}

function layoutKey(project: string, name: string): string {
  return `ah.builder.layout.${project}/${name}`;
}

function readLayout(project: string, name: string): Layout {
  try {
    const value = JSON.parse(
      readStored(layoutKey(project, name)) ?? "null",
    ) as Partial<Layout> | null;
    return {
      main: value?.main ?? { x: 80, y: 40 },
      loose: Array.isArray(value?.loose) ? value.loose.filter((stack) => !stack.kept) : [],
    };
  } catch {
    return { main: { x: 80, y: 40 }, loose: [] };
  }
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
}: {
  scenario: ScenarioDetail;
  mode: "interactive" | "regression";
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
  const [drag, setDrag] = useState<DragState | null>(null);
  const document = draft.document;

  // The program, read again whenever the document changes from elsewhere (undo, the graph).
  const [synced, setSynced] = useState("");
  const [program, setProgram] = useState<{ main: Item[]; kept: Stack[] }>({ main: [], kept: [] });
  const [layout, setLayout] = useState<Layout>(() => readLayout(scenario.project, scenario.name));
  const nodesText = JSON.stringify(document.nodes);
  if (synced !== nodesText) {
    const read = programOf(document.nodes);
    setSynced(nodesText);
    setProgram({
      main: read.main,
      kept:
        read.loose.length > 0
          ? [
              {
                id: "kept",
                x: layout.main.x + 560,
                y: layout.main.y,
                items: read.loose.map((node) => ({ kind: "block", node })),
                kept: true,
              },
            ]
          : [],
    });
  }

  const saveLayout = (next: Layout) => {
    setLayout(next);
    writeStored(layoutKey(scenario.project, scenario.name), JSON.stringify(next));
  };

  const commit = (main: Item[], kept: Stack[], loose: Stack[]) => {
    const nodes = [...nodesOf(main), ...kept.flatMap((stack) => programNodes(stack.items))];
    setProgram({ main, kept });
    saveLayout({ ...layout, loose: loose.filter((stack) => stack.items.length > 0) });
    const text = JSON.stringify(nodes);
    setSynced(text);
    if (text !== nodesText) draft.edit({ ...document, nodes });
  };

  const allItems = [
    ...program.main,
    ...program.kept.flatMap((s) => s.items),
    ...layout.loose.flatMap((s) => s.items),
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

  const onTake = (stack: string, id: string, alone: boolean): Item[] => {
    if (stack === "main") {
      const { rest, taken: moved } = takeFrom(program.main, id, alone);
      setProgram({ ...program, main: rest });
      return moved;
    }
    const inKept = program.kept.some((s) => s.id === stack);
    const source = inKept ? program.kept : layout.loose;
    let moved: Item[] = [];
    const next = source.map((s) => {
      if (s.id !== stack) return s;
      const out = takeFrom(s.items, id, alone);
      moved = out.taken;
      return { ...s, items: out.rest };
    });
    if (inKept) setProgram({ ...program, kept: next });
    else setLayout({ ...layout, loose: next });
    return moved;
  };

  const onDrop = (moved: Item[], target: DropTarget) => {
    const first = moved[0];
    if (first) setSelected(itemId(first));
    if ("free" in target) {
      commit(program.main, program.kept, [
        ...layout.loose,
        { id: freshKey("stack"), x: target.free.x, y: target.free.y, items: moved },
      ]);
      return;
    }
    if (target.stack === "main") {
      commit(insertAt(program.main, target.slot, target.index, moved), program.kept, layout.loose);
      return;
    }
    const into = (list: Stack[]) =>
      list.map((s) =>
        s.id === target.stack
          ? { ...s, items: insertAt(s.items, target.slot, target.index, moved) }
          : s,
      );
    commit(program.main, into(program.kept), into(layout.loose));
  };

  const addAtEnd = (item: Item) => {
    commit([...program.main, item], program.kept, layout.loose);
    setSelected(itemId(item));
  };

  const editItem = (id: string, next: Item) => {
    commit(
      replaceItem(program.main, id, next),
      program.kept.map((s) => ({ ...s, items: replaceItem(s.items, id, next) })),
      layout.loose.map((s) => ({ ...s, items: replaceItem(s.items, id, next) })),
    );
  };

  const editNode = (node: BuilderNode) => {
    const current = findItem(allItems, node.id);
    if (current?.kind === "repeat") editItem(node.id, { ...current, node });
    else editItem(node.id, { kind: "block", node });
  };

  const removeItem = (id: string) => {
    const strip = (list: Item[]) => takeFrom(list, id, true).rest;
    commit(
      strip(program.main),
      program.kept.map((s) => ({ ...s, items: strip(s.items) })),
      layout.loose.map((s) => ({ ...s, items: strip(s.items) })),
    );
    setSelected(null);
  };

  const selectedItem = selected ? findItem(allItems, selected) : null;
  const serialized: BuilderDocument = {
    ...document,
    nodes: [...nodesOf(program.main), ...program.kept.flatMap((s) => programNodes(s.items))],
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

  const inspector = (() => {
    if (!selectedItem) return <ScenarioSettings document={document} onChange={draft.edit} />;
    if (selectedItem.kind === "block" || selectedItem.kind === "repeat") {
      const node =
        selectedItem.kind === "repeat"
          ? { ...selectedItem.node, nodes: nodesOf(selectedItem.body) }
          : selectedItem.node;
      return (
        <BlockInspector
          key={node.id}
          document={serialized}
          node={node}
          library={items}
          problems={problems.filter((problem) => problem.node === node.id)}
          mode={mode}
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
          onDelete={() => {
            removeItem(node.id);
          }}
          onClose={() => {
            setSelected(null);
          }}
        />
      );
    }
    const isIf = selectedItem.kind === "if";
    return (
      <section
        className="sb-inspector"
        aria-label={isIf ? "Inspector: If" : "Inspector: At the same time"}
      >
        <header
          className="sb-inspector-head"
          style={{ ["--kind" as string]: isIf ? "var(--ev-decision)" : "var(--ev-reasoning)" }}
        >
          <span className="sb-kind" aria-hidden>
            <Icon name={isIf ? "split" : "git-branch"} size="sm" />
          </span>
          <b>{isIf ? "If … else" : "At the same time"}</b>
          <span className="ah-grow" />
          <button
            type="button"
            className="sb-icon-btn"
            aria-label="Delete this block and what it holds"
            onClick={() => {
              removeItem(selectedItem.key);
            }}
          >
            <Icon name="trash" size="sm" />
          </button>
          <button
            type="button"
            className="sb-icon-btn"
            aria-label="Close the inspector"
            onClick={() => {
              setSelected(null);
            }}
          >
            <Icon name="x" size="sm" />
          </button>
        </header>
        <div className="sb-inspector-body">
          {isIf ? (
            <>
              <ConditionBuilder
                label="If"
                value={selectedItem.condition}
                fields={everySource(serialized, outputs).map((source) => ({
                  ref: source.ref,
                  label: `${source.label} (${source.hint})`,
                }))}
                onChange={(condition) => {
                  editItem(selectedItem.key, { ...selectedItem, condition });
                }}
              />
              <span className="ah-small ah-subtle">
                The first block of the path runs only when it holds; the else path runs when it does
                not. The blocks after the If run after the path taken.
              </span>
            </>
          ) : (
            <>
              <span className="ah-small">
                {selectedItem.lanes.length} paths start together; the next block waits for all.
              </span>
              <span className="ah-row" style={{ gap: 6 }}>
                <Button
                  size="sm"
                  icon="plus"
                  onClick={() => {
                    editItem(selectedItem.key, {
                      ...selectedItem,
                      lanes: [...selectedItem.lanes, []],
                    });
                  }}
                >
                  Add a path
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={selectedItem.lanes.length <= 2}
                  onClick={() => {
                    editItem(selectedItem.key, {
                      ...selectedItem,
                      lanes: selectedItem.lanes.slice(0, -1),
                    });
                  }}
                >
                  Remove the last path
                </Button>
              </span>
            </>
          )}
        </div>
      </section>
    );
  })();

  const inputs =
    typeof document.inputs === "object" &&
    document.inputs !== null &&
    !Array.isArray(document.inputs)
      ? Object.keys(document.inputs)
      : [];
  const unsaved = layout.loose.reduce(
    (count, stack) => count + programNodes(stack.items).length,
    0,
  );

  return (
    <div className="sb-root">
      <div className="sb-toolbar">
        <SegmentedControl
          label="View"
          value={view}
          onChange={(id) => {
            setView(id === "graph" || id === "yaml" ? id : "blocks");
          }}
          options={[
            { id: "blocks", label: "Blocks", icon: "puzzle" },
            { id: "graph", label: "Graph", icon: "workflow" },
            { id: "yaml", label: "YAML", icon: "file-text" },
          ]}
        />
        <Button
          size="sm"
          variant="ghost"
          icon="undo-2"
          disabled={!draft.canUndo}
          onClick={draft.undo}
        >
          Undo
        </Button>
        <Button
          size="sm"
          variant="ghost"
          icon="redo-2"
          disabled={!draft.canRedo}
          onClick={draft.redo}
        >
          Redo
        </Button>
        <span className="sb-check ah-small" role="status">
          {draft.check === null ? (
            "Checking…"
          ) : errors.length > 0 ? (
            <span style={{ color: "var(--failed)" }}>
              <Icon name="circle-x" size="sm" /> {errors.length}{" "}
              {errors.length === 1 ? "problem" : "problems"}
            </span>
          ) : (
            <span>
              <Icon name="circle-check" size="sm" style={{ color: "var(--done)" }} /> Loads
              {problems.length > 0 &&
                ` · ${String(problems.length)} warning${problems.length === 1 ? "" : "s"}`}
            </span>
          )}
        </span>
        {unsaved > 0 && (
          <span className="ah-small" style={{ color: "var(--waiting)" }}>
            <Icon name="triangle-alert" size="sm" /> {unsaved} loose{" "}
            {unsaved === 1 ? "block" : "blocks"} not in the flow
          </span>
        )}
        <span className="ah-grow" />
        {draft.dirty && (
          <span className="ah-small ah-muted">
            <span className="sb-dot" aria-hidden /> Unsaved changes
          </span>
        )}
        {draft.saved && !draft.dirty && (
          <span className="ah-small ah-muted">Saved · revision {draft.saved.revision}</span>
        )}
        <Button
          variant="primary"
          icon="save"
          disabled={!draft.dirty || draft.saving || errors.length > 0 || draft.check === null}
          title={errors.length > 0 ? `Fix ${String(errors.length)} problems to save` : undefined}
          onClick={draft.save}
        >
          {draft.saving ? "Saving…" : "Save scenario"}
        </Button>
      </div>
      {draft.saveError && (
        <Banner tone="error" boxed>
          Could not save: {draft.saveError.detail ?? draft.saveError.title}
        </Banner>
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
      <div className="sb-body">
        <Palette
          library={items}
          pack={scenario.pack}
          taken={taken}
          onDrag={setDrag}
          onAdd={addAtEnd}
        />
        <div className="sb-stage">
          {view === "blocks" && (
            <BlockCanvas
              main={{ id: "main", x: layout.main.x, y: layout.main.y, items: program.main }}
              loose={[...program.kept, ...layout.loose]}
              selected={selected}
              actionOf={actionFacts}
              problemsOf={(id) => problems.filter((problem) => problem.node === id)}
              inputs={inputs}
              onSelect={setSelected}
              onTake={onTake}
              onDrop={onDrop}
              onMoveStack={(_stack, x, y) => {
                saveLayout({ ...layout, main: { x, y } });
              }}
              onEditNode={editNode}
              drag={drag}
              onDrag={setDrag}
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
        {inspector}
      </div>
    </div>
  );
}
