import { toPng } from "html-to-image";

/**
 * The largest decoded PNG the server takes: its base64 fits the Anthropic API's 5 MB image limit
 * (`MAX_SCREENSHOT_BYTES` in core, spec amendment A1).
 */
export const MAX_CAPTURE_BYTES = 3_932_160;

export type CaptureResult =
  | { ok: true; dataUrl: string; bytes: number }
  | { ok: false; reason: "failed" | "timeout" | "too-large" };

/** The decoded size of a base64 data URL, from its length and padding. */
export function decodedBytes(dataUrl: string): number {
  const data = dataUrl.slice(dataUrl.indexOf(",") + 1);
  const padding = data.endsWith("==") ? 2 : data.endsWith("=") ? 1 : 0;
  return (data.length * 3) / 4 - padding;
}

const TIMED_OUT = Symbol("timeout");

async function render(node: HTMLElement, maxBytes: number): Promise<CaptureResult> {
  const first = await toPng(node, { cacheBust: false });
  if (decodedBytes(first) <= maxBytes)
    return { ok: true, dataUrl: first, bytes: decodedBytes(first) };
  const smaller = await toPng(node, { cacheBust: false, pixelRatio: 1 });
  const bytes = decodedBytes(smaller);
  return bytes <= maxBytes
    ? { ok: true, dataUrl: smaller, bytes }
    : { ok: false, reason: "too-large" };
}

/**
 * Renders `node` to a PNG data URL in the browser (no network, no permission prompt). It retries once at
 * pixel ratio 1 when the PNG is over `maxBytes`, and never rejects: a failure resolves `{ok: false}`.
 */
export async function captureScreen(
  node: HTMLElement = document.body,
  {
    timeoutMs = 1500,
    maxBytes = MAX_CAPTURE_BYTES,
  }: { timeoutMs?: number; maxBytes?: number } = {},
): Promise<CaptureResult> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<typeof TIMED_OUT>((resolve) => {
    timer = setTimeout(() => {
      resolve(TIMED_OUT);
    }, timeoutMs);
  });
  try {
    const result = await Promise.race([render(node, maxBytes), timeout]);
    return result === TIMED_OUT ? { ok: false, reason: "timeout" } : result;
  } catch {
    return { ok: false, reason: "failed" };
  } finally {
    clearTimeout(timer);
  }
}
