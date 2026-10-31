// The size budget of the built app: the entry chunk, the one index.html loads, and the vendor
// chunk each have a limit in bytes.

// The limits the owner set. Budgets only tighten: lower a limit, never raise it.
export const ENTRY_LIMIT_BYTES = 400_000;
export const VENDOR_LIMIT_BYTES = 350_000;

// The name of the vendor group in vite.config.ts, which Rolldown gives its chunk too.
export const VENDOR_CHUNK_NAME = "vendor";

// One chunk of the output bundle: its file under the output folder, its chunk name, whether
// index.html loads it, and its size in bytes.
export interface BundleChunk {
  fileName: string;
  name: string;
  isEntry: boolean;
  size: number;
}

// The limits in bytes of the entry chunk and of the vendor chunk.
export interface BundleLimits {
  entry: number;
  vendor: number;
}

// `ok` when the bundle is within its limits; `lines` is what the build prints.
export interface BundleCheck {
  ok: boolean;
  lines: string[];
}

const BYTES = new Intl.NumberFormat("en-US");

function inBytes(size: number): string {
  return `${BYTES.format(size)} B`;
}

// Every chunk of a kind must be under the kind's limit. Finding none fails too, because the limit
// would then check nothing.
function checkChunks(found: readonly BundleChunk[], kind: string, limit: number): BundleCheck {
  if (found.length === 0) {
    return {
      ok: false,
      lines: [`The bundle has no ${kind} chunk, so its ${inBytes(limit)} limit cannot be checked.`],
    };
  }
  const isUnder = (chunk: BundleChunk) => chunk.size < limit;
  return {
    ok: found.every(isUnder),
    lines: found.map((chunk) =>
      isUnder(chunk)
        ? `${chunk.fileName} is ${inBytes(chunk.size)}, under the ${kind} limit of ${inBytes(limit)}.`
        : `${chunk.fileName} is ${inBytes(chunk.size)}: the ${kind} chunk must be under ${inBytes(limit)}.`,
    ),
  };
}

// Checks the entry chunk and the vendor chunk, each alone, against its own limit.
export function checkBundle(chunks: readonly BundleChunk[], limits: BundleLimits): BundleCheck {
  const entry = chunks.filter((chunk) => chunk.isEntry);
  const vendor = chunks.filter((chunk) => chunk.name === VENDOR_CHUNK_NAME);
  const checks = [
    checkChunks(entry, "entry", limits.entry),
    checkChunks(vendor, "vendor", limits.vendor),
  ];
  return {
    ok: checks.every((check) => check.ok),
    lines: checks.flatMap((check) => check.lines),
  };
}
