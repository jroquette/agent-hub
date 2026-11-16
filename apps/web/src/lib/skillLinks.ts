/**
 * Relative links inside a skill body (S7, AC-164.21): a link that names one of the skill's bundled
 * files, relative to the skill folder, opens that file in the page; anything else is not resolved
 * here (the renderer shows it as text, never as a Brain link). Files are known only by the ids the
 * server issued, so a link never reaches the API as a path.
 */
import { isRelativeHref } from "./brainLinks";

function decode(value: string): string | null {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}

/** The bundled file a relative `href` of the skill body names, or null. */
export function resolveSkillLink<F extends { path: string }>(
  href: string,
  files: readonly F[],
): F | null {
  if (!isRelativeHref(href) || href.includes("?")) return null;
  const hashAt = href.indexOf("#");
  const path = decode(hashAt === -1 ? href : href.slice(0, hashAt));
  if (path === null || path === "") return null;
  const resolved: string[] = [];
  for (const segment of path.split("/")) {
    if (segment === "" || segment === ".") continue;
    if (segment === "..") {
      if (resolved.length === 0) return null;
      resolved.pop();
    } else resolved.push(segment);
  }
  const full = resolved.join("/");
  return files.find((file) => file.path === full) ?? null;
}

/** The element id of a bundled file's row on the detail page. */
export function bundledFileAnchor(id: string): string {
  return `skill-file-${id}`;
}
