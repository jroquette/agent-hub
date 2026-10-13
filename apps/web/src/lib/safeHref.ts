/**
 * The one gate for links built from API data (pr_url, issue urls, activity hrefs, Markdown links).
 *
 * Keeps an absolute `http:`/`https:` URL or a same-origin relative path and returns `null` for anything
 * else (`javascript:`, `data:`, protocol-relative `//host`, backslash tricks, control characters), so the
 * caller renders the label as plain text.
 */
const ABSOLUTE = /^https?:\/\//i;
const SCHEME = /^[a-z][a-z0-9+.-]*:/i;
// eslint-disable-next-line no-control-regex -- control characters are exactly what is rejected
const CONTROL_OR_BACKSLASH = /[\u0000-\u001f\u007f\\]/;
const BASE = "https://same-origin.invalid/app/";
const BASE_ORIGIN = new URL(BASE).origin;

export function safeHref(value: string | null | undefined): string | null {
  if (
    typeof value !== "string" ||
    value === "" ||
    value !== value.trim() ||
    CONTROL_OR_BACKSLASH.test(value)
  )
    return null;
  const absolute = ABSOLUTE.test(value);
  if (!absolute && SCHEME.test(value)) return null;
  let url: URL;
  try {
    url = absolute ? new URL(value) : new URL(value, BASE);
  } catch {
    return null;
  }
  if (absolute) {
    return url.protocol === "https:" || url.protocol === "http:" ? value : null;
  }
  return url.origin === BASE_ORIGIN ? value : null;
}

/** True for a safe root-relative path that the in-app router can open (`/runs/r-1`). */
export function isInAppPath(value: string | null | undefined): boolean {
  const safe = safeHref(value);
  return safe?.startsWith("/") ?? false;
}

const LINEAR_PREFIX = "https://linear.app/";

/**
 * A Linear issue link (AC-136.29): a `safeHref` URL that is `https://linear.app/…` exactly (no
 * other scheme, host, port or user), else `null`, so the caller shows the id as plain text.
 */
export function linearHref(value: string | null | undefined): string | null {
  const safe = safeHref(value);
  if (safe === null || !safe.startsWith(LINEAR_PREFIX) || safe === LINEAR_PREFIX) return null;
  try {
    const url = new URL(safe);
    if (url.origin !== "https://linear.app" || url.username || url.password) return null;
  } catch {
    return null;
  }
  return safe;
}

/** The only links a cloud session may open (D8, AC-165.40); the server checks the same prefix. */
export const CLAUDE_CODE_PREFIX = "https://claude.ai/code/";

/**
 * A cloud session link: a `safeHref` URL under `https://claude.ai/code/` (no other scheme, host,
 * port or user, and no dot segment leaving `/code/`), else `null`, so the caller shows plain text.
 */
export function claudeCodeHref(value: string | null | undefined): string | null {
  const safe = safeHref(value);
  if (safe === null || !safe.startsWith(CLAUDE_CODE_PREFIX) || safe === CLAUDE_CODE_PREFIX)
    return null;
  try {
    const url = new URL(safe);
    if (url.origin !== "https://claude.ai" || url.username || url.password) return null;
    if (!url.pathname.startsWith("/code/") || url.pathname === "/code/") return null;
  } catch {
    return null;
  }
  return safe;
}
