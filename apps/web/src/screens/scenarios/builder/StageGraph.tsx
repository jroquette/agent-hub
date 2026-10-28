import type { ReactNode } from "react";

import { Icon } from "../../../components";
import type { ScenarioAction } from "../queries";
import { KindTile } from "./CardParts";
import { FlowBlock, kindLook } from "./FlowCanvas";
import { conditionWords, text, type BuilderNode } from "./model";
import { itemId, type Item } from "./program";
import type { BuilderProblem } from "./useScenarioDraft";

/* The Graph view of a scenario written as blocks: a picture of how its blocks run, drawn from the
 * blocks themselves. Each stage is a labelled band; inside it the blocks run left to right and
 * wrap at the band's edge, an arrow between two. An If shows its two paths, At the same time its
 * lanes, a Repeat a frame around the blocks each round runs. Nothing is added or moved here: a
 * card selects its block, which opens as in Blocks. */

export interface StageGraphProps {
  items: readonly Item[];
  numbers: ReadonlyMap<string, string>;
  actionOf: (node: BuilderNode) => ScenarioAction | null;
  problemsOf: (key: string) => readonly BuilderProblem[];
  statusOf?: ((key: string) => ReactNode) | undefined;
  /** The block the shown scenario run is at now. */
  current?: string | null | undefined;
  selected: string | null;
  onSelect: (key: string) => void;
}

function count(n: number, noun: string): string {
  return `${String(n)} ${n === 1 ? noun : `${noun}s`}`;
}

function blocksIn(items: readonly Item[]): number {
  return items.reduce((sum, item) => {
    if (item.kind === "block") return sum + 1;
    if (item.kind === "repeat") return sum + 1 + blocksIn(item.body);
    if (item.kind === "if") return sum + blocksIn(item.then) + blocksIn(item.otherwise);
    if (item.kind === "parallel")
      return sum + item.lanes.reduce((n, lane) => n + blocksIn(lane), 0);
    return sum + blocksIn(item.steps);
  }, 0);
}

export function StageGraph(props: StageGraphProps) {
  const { items, numbers } = props;

  const card = (key: string, node: BuilderNode) => (
    <div className="sg-cell" data-current={props.current === key ? "true" : undefined}>
      <FlowBlock
        node={node}
        action={props.actionOf(node)}
        problems={props.problemsOf(key)}
        selected={props.selected === key}
        status={props.statusOf?.(key)}
        number={numbers.get(key)}
        onSelect={() => {
          props.onSelect(key);
        }}
      />
    </div>
  );

  const flow = (list: readonly Item[]): ReactNode =>
    list.length === 0 ? (
      <span className="sg-empty">No blocks.</span>
    ) : (
      <div className="sg-flow">
        {list.map((item, index) => (
          <div key={itemId(item)} className="sg-step">
            {index > 0 && (
              <span className="sg-arrow" aria-hidden>
                <Icon name="arrow-right" size="sm" />
              </span>
            )}
            {node(item)}
          </div>
        ))}
      </div>
    );

  const node = (item: Item): ReactNode => {
    const key = itemId(item);
    if (item.kind === "block") return card(key, item.node);
    if (item.kind === "repeat") {
      const rounds = text(item.node.max_iterations, "1");
      return (
        <div className="sg-frame" aria-label={`Repeat ${numbers.get(key) ?? key}`} role="group">
          {card(key, item.node)}
          <div className="sg-frame-body">
            <span className="sg-path-label">
              <Icon name="refresh-cw" size="sm" /> Each round, at most {rounds}
            </span>
            {flow(item.body)}
          </div>
        </div>
      );
    }
    if (item.kind === "if") {
      return (
        <div className="sg-frame" role="group" aria-label={`If ${numbers.get(key) ?? key}`}>
          <span className="sg-frame-head">
            <span className="sg-num">{numbers.get(key)}</span>
            <KindTile look={kindLook("branch")} />
            If {conditionWords(item.condition) || "…"}
          </span>
          <div className="sg-paths">
            <div className="sg-path">
              <span className="sg-path-label">If yes</span>
              {flow(item.then)}
            </div>
            <div className="sg-path">
              <span className="sg-path-label">Otherwise</span>
              {flow(item.otherwise)}
            </div>
          </div>
        </div>
      );
    }
    if (item.kind === "parallel") {
      return (
        <div
          className="sg-frame"
          role="group"
          aria-label={`At the same time ${numbers.get(key) ?? key}`}
        >
          <span className="sg-frame-head">
            <span className="sg-num">{numbers.get(key)}</span>
            <KindTile look={kindLook("parallel")} />
            At the same time · {count(item.lanes.length, "path")}, then continues
          </span>
          <div className="sg-paths">
            {item.lanes.map((lane, index) => (
              <div key={index} className="sg-path">
                <span className="sg-path-label">Path {index + 1}</span>
                {flow(lane)}
              </div>
            ))}
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="sg-graph">
      <span className="sg-start">
        <Icon name="flag" size="sm" /> Start
      </span>
      {items.map((stage) =>
        stage.kind === "stage" ? (
          <section
            key={stage.key}
            className="sg-band"
            aria-label={`Stage ${numbers.get(stage.key) ?? stage.key}: ${stage.name}`}
          >
            <header className="sg-band-head">
              <span className="sg-num">{numbers.get(stage.key)}</span>
              <KindTile look={kindLook("stage")} />
              <b>{stage.name || "A stage with no name"}</b>
              <span className="sg-band-count">{count(blocksIn(stage.steps), "block")}</span>
            </header>
            {flow(stage.steps)}
          </section>
        ) : (
          <div key={itemId(stage)}>{node(stage)}</div>
        ),
      )}
      <span className="sg-start">
        <Icon name="flag" size="sm" /> End
      </span>
    </div>
  );
}
