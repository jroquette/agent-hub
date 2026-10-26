import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";

import { Icon, type IconName } from "../../../components";
import { EffectBadge } from "../parts";
import { kindLook } from "./FlowCanvas";
import type { BuilderDocument } from "./model";
import { CATEGORIES, STAGE_ENTRY, blockItem } from "./palette";
import type { Item } from "./program";
import type { LibraryAction } from "./useScenarioDraft";

/* The Blocks tab (scenario builder v6): the block language a scenario is built from, by hand.
 * The step types (Do, Check, Control, You) and the hub's actions as ready blocks ("Run
 * queue-send", "Wait until with order-state"); a scenario written as blocks also has a Stage
 * block. Drag a block into the list, where a line shows where it lands, or click it (Enter) to
 * add it after the selected step. */

/** What a block looks like while it is dragged. */
export interface BlockLook {
  label: string;
  icon: IconName;
  tint: string;
  soft: string;
}

export interface BlocksTabProps {
  library: readonly LibraryAction[];
  pack: string;
  taken: BuilderDocument;
  /** Where a click adds: "after step 4", or "at the end". */
  where: string;
  /** Claude's proposal is under review: the draft is not edited, so no block is added. */
  locked?: boolean;
  onAdd: (item: Item) => void;
  /** A press that may become a drag; a press without a move is a click. */
  onPress: (event: ReactPointerEvent, make: () => Item, look: BlockLook) => void;
  /** A scenario written as blocks: its stages' names, and where a click adds a stage ("after
   * stage 2", "at the end"); null for a graph, which has no stages. */
  stages?: { names: readonly string[]; where: string } | null;
}

function Block({
  look,
  hint,
  extra,
  where,
  locked,
  make,
  onAdd,
  onPress,
}: {
  look: BlockLook;
  hint: string;
  extra?: ReactNode;
  where: string;
  locked: boolean;
  make: () => Item;
  onAdd: (item: Item) => void;
  onPress: BlocksTabProps["onPress"];
}) {
  return (
    <li>
      <button
        type="button"
        className="sb-pal"
        aria-label={locked ? `Add ${look.label}` : `Add ${look.label} ${where}`}
        aria-disabled={locked || undefined}
        title={locked ? LOCKED : `Drag into the list, or click to add ${where}`}
        style={{ ["--tile" as string]: look.tint, ["--tile-soft" as string]: look.soft }}
        onPointerDown={(event) => {
          onPress(event, make, look);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onAdd(make());
          }
        }}
      >
        <span className="sb-pal-tile" aria-hidden>
          <Icon name={look.icon} size="sm" />
        </span>
        <span className="sb-pal-text">
          <span className="sb-pal-label">{look.label}</span>
          <span className="sb-pal-hint">{hint}</span>
        </span>
        {extra}
        <Icon name="grip-vertical" size="sm" className="sb-pal-grip" />
      </button>
    </li>
  );
}

const LOCKED =
  "While you review Claude's proposal the draft is not edited: go back to your draft to add a block.";

export function BlocksTab({
  library,
  pack,
  taken,
  where,
  locked = false,
  onAdd,
  onPress,
  stages = null,
}: BlocksTabProps) {
  const refOf = (item: LibraryAction) =>
    item.action.pack === pack ? item.action.name : item.action.ref;
  const stageLook = kindLook("stage");
  return (
    <div className="sb-left-body">
      <span className="ah-small ah-muted">
        {locked ? LOCKED : `Drag a block into the list, or click one to add it ${where}.`}
      </span>
      {stages && (
        <section className="sb-blocks" aria-label="Stages">
          <h3 className="sb-blocks-title">Stages</h3>
          <ul>
            <Block
              look={{
                label: STAGE_ENTRY.label,
                icon: STAGE_ENTRY.icon,
                tint: stageLook.tint,
                soft: stageLook.soft,
              }}
              hint={STAGE_ENTRY.hint}
              where={stages.where}
              locked={locked}
              make={() => STAGE_ENTRY.make(stages.names)}
              onAdd={onAdd}
              onPress={onPress}
            />
          </ul>
        </section>
      )}
      {CATEGORIES.map((category) => (
        <section key={category.title} className="sb-blocks" aria-label={category.title}>
          <h3 className="sb-blocks-title">{category.title}</h3>
          <ul>
            {category.entries.map((entry) => {
              const kind = kindLook(
                entry.key === "repeat" ? "loop_group" : entry.key === "if" ? "branch" : entry.key,
              );
              return (
                <Block
                  key={entry.key}
                  look={{ label: entry.label, icon: entry.icon, tint: kind.tint, soft: kind.soft }}
                  hint={entry.hint}
                  where={where}
                  locked={locked}
                  make={() => entry.make(taken)}
                  onAdd={onAdd}
                  onPress={onPress}
                />
              );
            })}
          </ul>
        </section>
      ))}
      {library.length > 0 && (
        <section className="sb-blocks" aria-label="Your actions">
          <h3 className="sb-blocks-title">Your actions</h3>
          <span className="ah-small ah-subtle">
            A script of this hub, ready to run. One that only reads can also wait until a state
            holds.
          </span>
          <ul>
            {library.flatMap((item) => {
              const run = kindLook("action");
              const blocks = [
                <Block
                  key={`run:${item.action.ref}`}
                  look={{
                    label: `Run ${item.action.name}`,
                    icon: "circle-play",
                    tint: run.tint,
                    soft: run.soft,
                  }}
                  hint={item.action.description ?? ""}
                  extra={<EffectBadge effect={item.action.effect} />}
                  where={where}
                  locked={locked}
                  make={() => blockItem(taken, "action", refOf(item))}
                  onAdd={onAdd}
                  onPress={onPress}
                />,
              ];
              if (item.action.effect === "read") {
                const check = kindLook("expect");
                blocks.push(
                  <Block
                    key={`wait:${item.action.ref}`}
                    look={{
                      label: `Wait until, with ${item.action.name}`,
                      icon: "timer",
                      tint: check.tint,
                      soft: check.soft,
                    }}
                    hint="Read again until a state holds"
                    where={where}
                    locked={locked}
                    make={() => blockItem(taken, "expect", refOf(item))}
                    onAdd={onAdd}
                    onPress={onPress}
                  />,
                );
              }
              return blocks;
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
