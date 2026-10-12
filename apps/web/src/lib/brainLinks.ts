/**
 * Where a link inside a brain note goes (AC-201.36): another note of the same brain opens in the app,
 * an absolute http(s) URL opens in a new tab through `safeHref`, a path leaving `brain/` is plain text
 * with the tooltip "outside the brain", and anything else is plain text.
 */
import { safeHref } from "./safeHref";

export const OUTSIDE_BRAIN = "outside the brain";
const NOT_A_LINK = "Link not shown: only http(s) links and brain notes are opened";
const NOT_A_NOTE = "Link not shown: only Markdown notes of the brain open in the app";
const NO_PLACE = "Link not shown: this note's place in the brain is unknown";

/** The server's note bounds (S8): longer or deeper paths are never served, so never linked. */
const MAX_PATH_CHARS = 512;
const MAX_SEGMENTS = 16;
// eslint-disable-next-line no-control-regex -- control characters are exactly what is rejected
const CONTROL_OR_BACKSLASH = /[\u0000-\u001f\u007f\\]/;
const SCHEME = /^[a-z][a-z0-9+.-]*:/i;

export type BrainLink =
  | { kind: "brain"; path: string; anchor: string | null; route: string }
  | { kind: "external"; href: string }
  | { kind: "outside"; title: string }
  | { kind: "text"; title: string };

/** The in-app route of a brain note: `/projects/<project>/brain/<path>[#anchor]`, each part encoded. */
export function brainRoute(project: string, path: string, anchor: string | null = null): string {
  const segments = path.split("/").map(encodeURIComponent).join("/");
  const hash = anchor ? `#${encodeURIComponent(anchor)}` : "";
  return `/projects/${encodeURIComponent(project)}/brain/${segments}${hash}`;
}

/** A GitHub-style heading slug: lower case, letters, digits, `-` and `_`, spaces as `-`. */
export function headingSlug(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s_-]/gu, "")
    .replace(/\s/g, "-");
}

/** The element id of a heading or anchor: prefixed so a note's ids cannot clobber page globals. */
export function anchorId(fragment: string): string {
  return `md-${headingSlug(fragment)}`;
}

function decode(value: string): string | null {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}

/** Resolve `href` written in the note at brain-relative `notePath` of `project`. */
export function resolveBrainLink(
  href: string,
  notePath: string | null,
  project: string | null,
): BrainLink {
  if (href === "" || href !== href.trim() || CONTROL_OR_BACKSLASH.test(href)) {
    return { kind: "text", title: NOT_A_LINK };
  }
  if (/^https?:\/\//i.test(href)) {
    const safe = safeHref(href);
    return safe === null ? { kind: "text", title: NOT_A_LINK } : { kind: "external", href: safe };
  }
  if (SCHEME.test(href) || href.startsWith("//") || href.includes("?")) {
    return { kind: "text", title: NOT_A_LINK };
  }
  if (href.startsWith("/")) return { kind: "outside", title: OUTSIDE_BRAIN };
  if (notePath === null || project === null) return { kind: "text", title: NO_PLACE };

  const hashAt = href.indexOf("#");
  const rawPath = hashAt === -1 ? href : href.slice(0, hashAt);
  const rawAnchor = hashAt === -1 ? "" : href.slice(hashAt + 1);
  const path = decode(rawPath);
  const anchor = decode(rawAnchor);
  if (path === null || anchor === null) return { kind: "text", title: NOT_A_LINK };

  const resolved = path === "" ? notePath.split("/") : notePath.split("/").slice(0, -1);
  if (path !== "") {
    for (const segment of path.split("/")) {
      if (segment === "" || segment === ".") continue;
      if (segment === "..") {
        if (resolved.length === 0) return { kind: "outside", title: OUTSIDE_BRAIN };
        resolved.pop();
      } else resolved.push(segment);
    }
  }
  const full = resolved.join("/");
  if (
    resolved.length === 0 ||
    resolved.length > MAX_SEGMENTS ||
    full.length > MAX_PATH_CHARS ||
    !full.endsWith(".md") ||
    resolved[0] === "auto" ||
    resolved.some((segment) => segment.startsWith("."))
  ) {
    return { kind: "text", title: NOT_A_NOTE };
  }
  const fragment = anchor === "" ? null : anchor;
  return {
    kind: "brain",
    path: full,
    anchor: fragment,
    route: brainRoute(project, full, fragment),
  };
}
