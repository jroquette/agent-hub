import { useMemo, useState } from "react";

import { Icon } from "../../components";
import {
  EXPAND_STEP,
  expandDiff,
  fileLines,
  revealMore,
  type GapReveal,
  type HiddenGap,
} from "./expandDiff";
import type { ChangedFile } from "./model";
import { useRepoFileText } from "./queries";

/** What a diff can reveal around its hunks, and how to ask for more. */
export interface DiffExpansion {
  /** The gap above each hunk header, in the order the headers come. */
  headers: readonly (HiddenGap | null)[];
  trailing: HiddenGap | null;
  onExpand: (gap: HiddenGap, direction: "up" | "down" | "all") => void;
}

const NOTHING: ReadonlyMap<number, GapReveal> = new Map();

const plural = (n: number) => `${String(n)} hidden line${n === 1 ? "" : "s"}`;

/**
 * The buttons in a hunk header's gutter, as on GitHub: a small gap opens whole, a bigger one
 * opens 20 lines at a time, down from the hunk above or up from the hunk below.
 */
export function ExpandGap({ gap, expansion }: { gap: HiddenGap; expansion: DiffExpansion }) {
  const button = (
    direction: "up" | "down" | "all",
    icon: "chevron-up" | "chevron-down" | "chevrons-up-down",
    label: string,
  ) => (
    <button
      type="button"
      className="as-diff-expand-btn"
      aria-label={label}
      title={label}
      onClick={() => {
        expansion.onExpand(gap, direction);
      }}
    >
      <Icon name={icon} size="sm" />
    </button>
  );
  const small = gap.hidden <= EXPAND_STEP;
  return (
    <span className="as-diff-expand">
      {small ? (
        button("all", "chevrons-up-down", `Expand all ${plural(gap.hidden)}`)
      ) : (
        <>
          {!gap.first && button("down", "chevron-down", `Expand ${String(EXPAND_STEP)} lines down`)}
          {!gap.last && button("up", "chevron-up", `Expand ${String(EXPAND_STEP)} lines up`)}
        </>
      )}
    </span>
  );
}

/** A file whose final diff can open wider: git's numbered diff against a base commit, of a file
 * the base has (not one the branch added). */
export function canExpand(file: ChangedFile): boolean {
  const { net, repo } = file;
  if (!repo?.baseSha || repo.unchanged || repo.status === "added") return false;
  return net?.numbered === true && net.diff !== "";
}

/**
 * A file's final diff, expandable around its hunks (`canExpand`): the file as the base has it is
 * read once, and each press reveals more of it. While the file loads, or when it cannot be read,
 * the diff as it is and no expansion.
 */
export function useExpandableNet(
  sessionId: string,
  file: ChangedFile,
): { diff: string | null; expansion: DiffExpansion | undefined } {
  const net = file.net;
  const repo = file.repo;
  const sha = repo?.baseSha ?? "";
  const basePath = repo?.oldPath ?? file.path;
  const enabled = canExpand(file);
  const query = useRepoFileText(sessionId, { path: basePath, sha }, enabled);
  // What was revealed holds for one diff: a newer one has other gaps, so it starts closed.
  const [state, setState] = useState<{ diff: string; reveal: ReadonlyMap<number, GapReveal> }>({
    diff: net?.diff ?? "",
    reveal: new Map(),
  });
  const reveal = state.diff === net?.diff ? state.reveal : NOTHING;
  const text = enabled ? query.data?.text : undefined;
  const base = useMemo(() => (typeof text === "string" ? fileLines(text) : null), [text]);
  const expanded = useMemo(
    () => (base && net ? expandDiff(net.diff, base, reveal) : null),
    [base, net, reveal],
  );
  if (!net) return { diff: null, expansion: undefined };
  if (!expanded) return { diff: net.diff, expansion: undefined };
  return {
    diff: expanded.diff,
    expansion: {
      headers: expanded.headers,
      trailing: expanded.trailing,
      onExpand: (gap, direction) => {
        setState((before) => ({
          diff: net.diff,
          reveal: revealMore(before.diff === net.diff ? before.reveal : NOTHING, gap, direction),
        }));
      },
    },
  };
}
