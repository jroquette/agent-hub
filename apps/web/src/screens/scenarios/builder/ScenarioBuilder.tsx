import "./builder.css";

import { useState } from "react";

import { Banner, Button, CopyButton, Icon, SegmentedControl } from "../../../components";
import { useDiscuss } from "../../../shell/discuss";
import { EffectBadge } from "../parts";
import type { ScenarioAction, ScenarioDetail } from "../queries";
import { ADD_CHOICES, FlowCanvas, kindLook, type AddChoice } from "./FlowCanvas";
import { BlockInspector, ScenarioSettings } from "./Inspector";
import {
  allNodes,
  insertAfter,
  insertBranch,
  moveBlock,
  newBlock,
  removeBlock,
  toDocument,
  updateBlock,
  type BlockKind,
  type BuilderDocument,
  type BuilderNode,
} from "./model";
import { useActionLibrary, useScenarioDraft, type LibraryAction } from "./useScenarioDraft";

/* The scenario builder (Build mode of the scenario page): a palette of blocks and of the hub's
 * actions, the flow canvas, and the inspector of the selected block (or the scenario's settings).
 * Every edit is checked by the server a moment later (the YAML Save would write, whether it
 * loads, each problem on its block); Save writes the file only when it loads. */

function Palette({
  library,
  onAddKind,
  onAddAction,
}: {
  library: readonly LibraryAction[];
  onAddKind: (kind: BlockKind) => void;
  onAddAction: (item: LibraryAction, asCheck: boolean) => void;
}) {
  const [query, setQuery] = useState("");
  const shown = library.filter((item) =>
    `${item.action.ref} ${item.action.description ?? ""}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const packs = [...new Set(shown.map((item) => item.action.pack ?? ""))];
  return (
    <aside className="sb-palette" aria-label="Blocks">
      <input
        className="ah-input"
        aria-label="Find an action"
        placeholder="Find an action"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
      />
      <span className="ah-overline">Steps</span>
      {ADD_CHOICES.filter((choice) => choice.kind !== "branch" && choice.kind !== "parallel").map(
        (choice) => (
          <button
            key={choice.kind}
            type="button"
            className="sb-palette-kind"
            style={{ ["--kind" as string]: kindLook(choice.kind).tint }}
            onClick={() => {
              onAddKind(choice.kind as BlockKind);
            }}
          >
            <span className="sb-kind" aria-hidden>
              <Icon name={choice.icon} size="sm" />
            </span>
            <span className="ah-stack" style={{ gap: 0 }}>
              <b>{choice.label}</b>
              <span className="ah-small ah-muted">{KIND_HINT[choice.kind]}</span>
            </span>
          </button>
        ),
      )}
      <span className="ah-overline">Actions in this hub</span>
      {library.length === 0 && (
        <span className="ah-small ah-subtle">
          No actions yet. An action is a script in actions/&lt;pack&gt;/ with a declared effect.
        </span>
      )}
      {packs.map((pack) => (
        <div key={pack} className="ah-stack" style={{ gap: 2 }}>
          <span className="ah-small ah-muted">{pack}</span>
          {shown
            .filter((item) => item.action.pack === pack)
            .map((item) => (
              <div
                key={item.action.ref}
                className="sb-palette-action"
                title={item.action.description ?? ""}
              >
                <button
                  type="button"
                  onClick={() => {
                    onAddAction(item, false);
                  }}
                  aria-label={`Add ${item.action.name} as a script block`}
                >
                  <Icon name="circle-play" size="sm" />
                  <span className="ah-mono">{item.action.name}</span>
                </button>
                <EffectBadge effect={item.action.effect} />
                {item.action.effect === "read" && (
                  <button
                    type="button"
                    className="sb-icon-btn"
                    title="Add as a check (polls until a state holds)"
                    aria-label={`Add ${item.action.name} as a check block`}
                    onClick={() => {
                      onAddAction(item, true);
                    }}
                  >
                    <Icon name="timer" size="sm" />
                  </button>
                )}
              </div>
            ))}
        </div>
      ))}
    </aside>
  );
}

const KIND_HINT: Readonly<Record<string, string>> = {
  action: "Runs an action once.",
  expect: "Reads until a state holds.",
  approval: "You do it by hand, then go on.",
  wait: "Waits for a set time.",
  loop_group: "Rounds until done.",
  include: "Reuses a scenario.",
};

export function ScenarioBuilder({
  scenario,
  mode,
}: {
  scenario: ScenarioDetail;
  mode: "interactive" | "regression";
}) {
  const library = useActionLibrary(scenario.project);
  const items = library.data?.items ?? [];
  const draft = useScenarioDraft({
    project: scenario.project,
    name: scenario.name,
    pack: scenario.pack,
    initial: toDocument(scenario.document),
    contentHash: scenario.content_hash ?? null,
  });
  const { setOpen } = useDiscuss();
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<"canvas" | "yaml">("canvas");
  const document = draft.document;
  const node = selected
    ? (allNodes(document.nodes).find((item) => item.id === selected) ?? null)
    : null;
  const problems = draft.check?.problems ?? [];
  const errors = problems.filter((problem) => problem.severity === "error");

  const actionFacts = (item: BuilderNode): ScenarioAction | null => {
    const ref = typeof item.action === "string" ? item.action : "";
    if (!ref) return null;
    return (
      items.find(
        (entry) => entry.action.ref === ref || entry.action.ref === `${scenario.pack}/${ref}`,
      )?.action ?? null
    );
  };

  const add = (next: BuilderDocument, block: BuilderNode) => {
    draft.edit(next);
    setSelected(block.id);
  };

  const onAdd = (choice: AddChoice, after: string | null, group: string | null) => {
    if (choice.kind === "branch") {
      if (after === null) return;
      const next = insertBranch(document, after, "$CTX.result", ["yes", "no"]);
      draft.edit(next);
      setSelected(null);
      return;
    }
    if (choice.kind === "parallel") return;
    const block = newBlock(document, choice.kind);
    add(insertAfter(document, block, after, group), block);
  };

  const at = selected && node ? selected : null;
  const placeAfter = at && node?.type !== "loop_group" ? at : null;

  return (
    <div className="sb-root">
      <div className="sb-toolbar">
        <SegmentedControl
          label="View"
          value={view}
          onChange={(id) => {
            setView(id === "yaml" ? "yaml" : "canvas");
          }}
          options={[
            { id: "canvas", label: "Canvas", icon: "workflow" },
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
      <div className="sb-body">
        <Palette
          library={items}
          onAddKind={(kind) => {
            const block = newBlock(document, kind);
            add(insertAfter(document, block, placeAfter), block);
          }}
          onAddAction={(item, asCheck) => {
            const ref = item.action.pack === scenario.pack ? item.action.name : item.action.ref;
            const block = newBlock(document, asCheck ? "expect" : "action", ref);
            add(insertAfter(document, block, placeAfter), block);
          }}
        />
        <div className="sb-stage">
          {view === "canvas" ? (
            <FlowCanvas
              nodes={document.nodes}
              actionOf={actionFacts}
              problemsOf={(id) => problems.filter((problem) => problem.node === id)}
              selected={selected}
              onSelect={setSelected}
              onAdd={onAdd}
            />
          ) : (
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
        {node ? (
          <BlockInspector
            key={node.id}
            document={document}
            node={node}
            library={items}
            problems={problems.filter((problem) => problem.node === node.id)}
            mode={mode}
            onChange={(next) => {
              draft.edit(updateBlock(document, node.id, next));
              if (next.id !== node.id) setSelected(next.id);
            }}
            onDelete={() => {
              draft.edit(removeBlock(document, node.id));
              setSelected(null);
            }}
            onMove={(by) => {
              draft.edit(moveBlock(document, node.id, by));
            }}
            onClose={() => {
              setSelected(null);
            }}
          />
        ) : (
          <ScenarioSettings document={document} onChange={draft.edit} />
        )}
      </div>
    </div>
  );
}
