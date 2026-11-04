/* The effort levels of a session (`--effort`), as the model and effort menu shows them. */
import type { components } from "../../api/schema";
import { readStored, writeStored } from "../../lib/storage";

export type EffortLevel = components["schemas"]["EffortLevel"];

interface EffortOption {
  value: EffortLevel;
  label: string;
  /** A short tag beside the level. */
  tag?: string;
  /** The tag warns: this level costs far more. */
  costly?: boolean;
}

export const EFFORTS: readonly EffortOption[] = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium", tag: "Recommended" },
  { value: "high", label: "High" },
  { value: "xhigh", label: "Extra" },
  { value: "max", label: "Max", tag: "3.5× or more usage", costly: true },
];

const EFFORT_KEY = "ah.session.effort";

/** The effort a new session starts with: the one last picked in this browser, else the CLI's. */
export function rememberedEffort(): EffortLevel | null {
  const stored = readStored(EFFORT_KEY);
  return EFFORTS.find((effort) => effort.value === stored)?.value ?? null;
}

export function rememberEffort(effort: EffortLevel): void {
  writeStored(EFFORT_KEY, effort);
}

export function effortLabel(effort: EffortLevel): string {
  return EFFORTS.find((option) => option.value === effort)?.label ?? effort;
}
