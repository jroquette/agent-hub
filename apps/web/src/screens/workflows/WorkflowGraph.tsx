import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useSearchParams } from "react-router";

import { Button, DataTable, Icon, SegmentedControl } from "../../components";
import type { IconName } from "../../components";

/* The layered graph of a workflow (plan 6.3/6.4): a column per layer, SVG edges for depends_on
 * under focusable node buttons, a list view as its text alternative and a node side panel. */

export interface GraphNode {
  id: string;
  type: string;
  depends_on: string[];
}

const TYPE_ICON: Readonly<Record<string, IconName>> = {
  agent: "message-square",
  shell: "terminal",
  script: "file-text",
  loop: "rotate-ccw",
  loop_group: "refresh-cw",
  approval: "stamp",
  wait: "hourglass",
  halt: "octagon-x",
  include: "layers",
};

export function typeIcon(type: string): IconName {
  return TYPE_ICON[type] ?? "box";
}

/** One edge per depends_on whose source is drawn, as `source→target`. */
export function edgesOf(layers: readonly (readonly GraphNode[])[]): [string, string][] {
  const ids = new Set(layers.flat().map((node) => node.id));
  return layers
    .flat()
    .flatMap((node) =>
      node.depends_on.filter((dep) => ids.has(dep)).map((dep): [string, string] => [dep, node.id]),
    );
}

/** The DOM id of a node's button, to give focus back when its panel closes. */
export function nodeDomId(id: string): string {
  return `wf-node-${id}`;
}

interface Box {
  left: number;
  right: number;
  mid: number;
}

export interface WorkflowGraphProps<N extends GraphNode> {
  layers: N[][];
  /** The graph's accessible name (default "Workflow graph"). */
  label?: string | undefined;
  selected: string | null;
  onSelect: (id: string) => void;
  /** A line under the node's type (a run's state); also a column of the list view. */
  detail?: ((node: N) => ReactNode) | undefined;
  /** The node's state for styling (`data-state`). */
  state?: ((node: N) => string) | undefined;
  /** The list view's last column title, when `detail` is given. */
  detailLabel?: string | undefined;
}

function GraphCanvas<N extends GraphNode>({
  layers,
  label = "Workflow graph",
  selected,
  onSelect,
  detail,
  state,
}: WorkflowGraphProps<N>) {
  const ref = useRef<HTMLDivElement>(null);
  const [boxes, setBoxes] = useState<Record<string, Box>>({});
  const [size, setSize] = useState({ width: 0, height: 0 });
  const edges = edgesOf(layers);
  // Re-measure when the shape changes, not on every render (a live run re-renders each second).
  const shape = layers
    .map((layer) => layer.map((node) => `${node.id}<${node.depends_on.join(",")}`).join(" "))
    .join("|");

  useLayoutEffect(() => {
    const root = ref.current;
    if (!root) return;
    // Content coordinates: the SVG scrolls with the nodes, so add the scroll offsets.
    const measure = () => {
      const origin = root.getBoundingClientRect();
      const dx = root.scrollLeft - origin.left;
      const dy = root.scrollTop - origin.top;
      const next: Record<string, Box> = {};
      root.querySelectorAll<HTMLElement>("[data-node-id]").forEach((el) => {
        const r = el.getBoundingClientRect();
        next[el.dataset.nodeId ?? ""] = {
          left: r.left + dx,
          right: r.right + dx,
          mid: r.top + dy + r.height / 2,
        };
      });
      setBoxes(next);
      setSize({ width: root.scrollWidth, height: root.scrollHeight });
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(root);
    // A node that reflows (a longer state line) moves its edges without resizing the root.
    root.querySelectorAll("[data-node-id]").forEach((el) => {
      observer.observe(el);
    });
    return () => {
      observer.disconnect();
    };
  }, [shape]);

  return (
    <div
      ref={ref}
      role="group"
      aria-label={label}
      style={{ position: "relative", display: "flex", gap: 48, overflowX: "auto", padding: 4 }}
    >
      <svg
        aria-hidden="true"
        data-edges=""
        width={size.width}
        height={size.height}
        style={{ position: "absolute", left: 0, top: 0, pointerEvents: "none" }}
      >
        {edges.map(([from, to]) => {
          const a = boxes[from];
          const b = boxes[to];
          const x1 = a?.right ?? 0;
          const y1 = a?.mid ?? 0;
          const x2 = b?.left ?? 0;
          const y2 = b?.mid ?? 0;
          const mx = (x1 + x2) / 2;
          return (
            <path
              key={`${from}→${to}`}
              data-edge={`${from}→${to}`}
              d={`M ${String(x1)} ${String(y1)} C ${String(mx)} ${String(y1)}, ${String(mx)} ${String(y2)}, ${String(x2)} ${String(y2)}`}
              fill="none"
              stroke="var(--border-strong)"
              strokeWidth={1.5}
            />
          );
        })}
      </svg>
      {layers.map((layer, i) => (
        <ol
          key={i}
          aria-label={`Layer ${String(i + 1)}`}
          className="ah-stack"
          style={{ gap: 12, listStyle: "none", margin: 0, padding: 0, minWidth: 168 }}
        >
          {layer.map((node) => (
            <li key={node.id}>
              <button
                type="button"
                id={nodeDomId(node.id)}
                data-node-id={node.id}
                data-state={state?.(node)}
                aria-pressed={selected === node.id}
                onClick={() => {
                  onSelect(node.id);
                }}
                className="ah-card"
                style={{
                  position: "relative",
                  display: "grid",
                  gridTemplateColumns: "16px 1fr",
                  gap: "2px 8px",
                  width: "100%",
                  padding: "8px 10px",
                  textAlign: "left",
                  cursor: "pointer",
                  font: "inherit",
                  color: "inherit",
                  borderColor: selected === node.id ? "var(--accent)" : undefined,
                  boxShadow: selected === node.id ? "0 0 0 1px var(--accent)" : undefined,
                }}
              >
                <Icon name={typeIcon(node.type)} size="sm" style={{ marginTop: 2 }} />
                <span className="ah-mono" style={{ fontWeight: 500, overflowWrap: "anywhere" }}>
                  {node.id}
                </span>
                <span />
                <span className="ah-small ah-subtle">{node.type}</span>
                {detail && (
                  <>
                    <span />
                    <span className="ah-small">{detail(node)}</span>
                  </>
                )}
              </button>
            </li>
          ))}
        </ol>
      ))}
    </div>
  );
}

function GraphList<N extends GraphNode>({
  layers,
  onSelect,
  detail,
  detailLabel,
}: WorkflowGraphProps<N>) {
  const rows = layers.flatMap((layer, i) => layer.map((node) => ({ node, layer: i + 1 })));
  return (
    <DataTable
      caption="Nodes in run order"
      density="compact"
      rows={rows}
      rowKey={(row) => row.node.id}
      onRowClick={(row) => {
        onSelect(row.node.id);
      }}
      columns={[
        { id: "layer", label: "Layer", width: 64, render: (row) => row.layer },
        {
          id: "node",
          label: "Node",
          render: (row) => <span className="ah-mono">{row.node.id}</span>,
        },
        { id: "type", label: "Type", render: (row) => row.node.type },
        {
          id: "after",
          label: "Waits for",
          render: (row) => row.node.depends_on.join(", ") || "—",
        },
        ...(detail
          ? [
              {
                id: "detail",
                label: detailLabel ?? "State",
                render: (row: { node: N }) => detail(row.node),
              },
            ]
          : []),
      ]}
    />
  );
}

/** The graph with a Graph | List switch; the list is the graph's text alternative. */
export function WorkflowGraph<N extends GraphNode>(props: WorkflowGraphProps<N>) {
  const [view, setView] = useState<"graph" | "list">("graph");
  return (
    <div className="ah-stack" style={{ gap: 8 }}>
      <div className="ah-row" style={{ gap: 8 }}>
        <span className="ah-small ah-subtle">
          One column per layer · arrows follow depends_on · choose a node for its details
        </span>
        <span className="ah-grow" />
        <SegmentedControl
          label="Graph view"
          value={view}
          onChange={(id) => {
            setView(id === "list" ? "list" : "graph");
          }}
          options={[
            { id: "graph", label: "Graph" },
            { id: "list", label: "List" },
          ]}
        />
      </div>
      {view === "graph" ? <GraphCanvas {...props} /> : <GraphList {...props} />}
    </div>
  );
}

/**
 * The selected node (`?node=`): `open` remembers the element that opened the panel (a node button
 * or a list row) and `close` gives focus back to it, else to the node's button.
 */
export function useNodeParam(): {
  nodeId: string | null;
  openedByUser: boolean;
  open: (id: string) => void;
  close: () => void;
} {
  const [params, setParams] = useSearchParams();
  const opener = useRef<HTMLElement | null>(null);
  const [openedByUser, setOpenedByUser] = useState(false);
  const nodeId = params.get("node");
  const setNode = useCallback(
    (id: string | null) => {
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          if (id === null) next.delete("node");
          else next.set("node", id);
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );
  const open = (id: string) => {
    const active = document.activeElement;
    // Safari leaves focus on the body after a mouse click: fall back to the node then.
    opener.current = active instanceof HTMLElement && active !== document.body ? active : null;
    setOpenedByUser(true);
    setNode(id);
  };
  const close = () => {
    const back = opener.current?.isConnected
      ? opener.current
      : nodeId
        ? document.getElementById(nodeDomId(nodeId))
        : null;
    opener.current = null;
    setOpenedByUser(false);
    setNode(null);
    back?.focus();
  };
  return { nodeId, openedByUser, open, close };
}

/** The selected node's side panel; Close gives focus back to what opened it. */
export function NodePanel({
  id,
  onClose,
  focusOnOpen,
  children,
}: {
  id: string;
  onClose: () => void;
  /** Move focus into the panel: on a user's choice, not on a `?node=` link at load. */
  focusOnOpen: boolean;
  children: ReactNode;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (focusOnOpen) heading.current?.focus();
  }, [id, focusOnOpen]);
  return (
    <aside className="ah-card" aria-label={`Node ${id}`} style={{ padding: "12px 16px" }}>
      <div className="ah-row" style={{ gap: 8, marginBottom: 8 }}>
        <h2 ref={heading} tabIndex={-1} className="ah-h3 ah-mono" style={{ margin: 0 }}>
          {id}
        </h2>
        <span className="ah-grow" />
        <Button size="sm" variant="ghost" icon="x" onClick={onClose}>
          Close
        </Button>
      </div>
      {children}
    </aside>
  );
}
