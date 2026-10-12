import { Link, useLocation } from "react-router";

import { Button, Kbd } from "../../components";
import { useShell } from "../../shell/AppShell";

export interface NotFoundBodyProps {
  /** The entity line (spec 22), e.g. "No session with id 5091b98x in agent-hub." */
  line?: string | undefined;
  /** What the palette opens prefilled with; defaults to the last path segment. */
  query?: string | undefined;
}

function lastSegment(pathname: string): string {
  const parts = pathname.split("/").filter(Boolean);
  return decodeURIComponent(parts[parts.length - 1] ?? "");
}

/**
 * The 404 page body (spec 22, Screen 2): the entity line, "Search with Ctrl K" opening the
 * palette prefilled, and "Go to Portfolio". Detail screens render it in place for unknown ids.
 */
export function NotFoundBody({ line, query }: NotFoundBodyProps) {
  const { pathname } = useLocation();
  const { openPalette } = useShell();
  const prefill = query ?? lastSegment(pathname);
  return (
    <div style={{ padding: "96px 32px 40px" }}>
      <div className="ah-stack" style={{ maxWidth: 640, margin: "0 auto", gap: 12 }}>
        <div className="ah-overline">404 · Not found</div>
        <h1 className="ah-h1" style={{ fontSize: 30, lineHeight: "38px" }}>
          This page does not exist
        </h1>
        <p style={{ margin: 0 }}>
          {line ?? `There is no page at ${pathname}. Check the address or search.`}
        </p>
        <p className="ah-muted" style={{ margin: 0 }}>
          It may be in a hub that is no longer registered, or the id is mistyped.
        </p>
        <div className="ah-row" style={{ gap: 8, marginTop: 8 }}>
          <Button
            variant="primary"
            icon="search"
            onClick={() => {
              openPalette(prefill);
            }}
          >
            Search with <Kbd>Ctrl K</Kbd>
          </Button>
          <Link className="ah-btn" to="/">
            Go to Portfolio
          </Link>
        </div>
        <div className="ah-small ah-subtle">
          Requested: <span className="ah-mono">{pathname}</span>
          {prefill && (
            <>
              {" "}
              · Search opens prefilled with <span className="ah-mono">{prefill}</span>
            </>
          )}{" "}
          · press <Kbd>?</Kbd> for shortcuts
        </div>
      </div>
    </div>
  );
}

/** Any route that matches nothing (D20). */
export function NotFoundScreen() {
  return <NotFoundBody />;
}
