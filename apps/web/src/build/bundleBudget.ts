// The size budget of the built app (AGH-614, AC-1, AC-3): the entry chunk, the one index.html loads,
// and the vendor chunk each have a limit in bytes.

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

export function checkBundle(chunks: readonly BundleChunk[], limits: BundleLimits): BundleCheck {
  throw new Error(
    `checkBundle is not implemented yet (${String(chunks.length)} chunks, ${JSON.stringify(limits)})`,
  );
}
