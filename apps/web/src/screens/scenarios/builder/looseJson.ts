/* JSON as scenario files write it: strict JSON, except that a reference may stand bare where a
 * number or a boolean goes (`"minutes":$INPUTS.minutes`); the engine puts the value there before
 * the action reads it. These read such a text into a value (a bare reference becomes a marked
 * string) and write it back the same way, so a body round-trips without changing its meaning. */

const BARE = "\u0000bare:";

/** A bare reference in a value read by `parseLoose`, kept as a marked string. */
export function isBare(value: unknown): value is string {
  return typeof value === "string" && value.startsWith(BARE);
}

/** The reference of a bare value (`$INPUTS.minutes`). */
export function bareRef(value: string): string {
  return value.slice(BARE.length);
}

/** A reference written bare, for a value that is not a string. */
export function asBare(ref: string): string {
  return `${BARE}${ref}`;
}

export type LooseParse =
  { ok: true; value: unknown } | { ok: false; message: string; line: number | null };

/** Quotes the references that stand bare outside strings, so the text parses as JSON. */
function quoteBare(text: string): string {
  let out = "";
  let inString = false;
  let escaped = false;
  for (let at = 0; at < text.length; at += 1) {
    const char = text.charAt(at);
    if (inString) {
      out += char;
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') inString = false;
      continue;
    }
    if (char === '"') {
      inString = true;
      out += char;
      continue;
    }
    if (char === "$") {
      const match = /^\$[A-Za-z_][A-Za-z0-9_.-]*/.exec(text.slice(at));
      if (match) {
        out += JSON.stringify(`${BARE}${match[0]}`);
        at += match[0].length - 1;
        continue;
      }
    }
    out += char;
  }
  return out;
}

export function parseLoose(text: string): LooseParse {
  const quoted = quoteBare(text);
  try {
    return { ok: true, value: JSON.parse(quoted) as unknown };
  } catch (error) {
    const message = error instanceof Error ? error.message : "Not valid JSON";
    const position = /position (\d+)/.exec(message);
    const line =
      position?.[1] !== undefined ? quoted.slice(0, Number(position[1])).split("\n").length : null;
    return { ok: false, message: message.replace(/^JSON\.parse: /, ""), line };
  }
}

/** Writes a value back: compact (as the file keeps it) or indented (to read and edit). */
export function stringifyLoose(value: unknown, indent = false): string {
  const text = JSON.stringify(value, null, indent ? 2 : undefined);
  return text.replace(/"\\u0000bare:(\$[^"]+)"/g, "$1");
}

/** True when the text is a JSON object or array (with bare references allowed). */
export function looksLikeJson(text: string): boolean {
  if (!/^\s*[[{]/.test(text)) return false;
  return parseLoose(text).ok;
}
