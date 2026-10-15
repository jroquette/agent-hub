import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { Outlet, useNavigate } from "react-router";

import { usePreferences } from "../lib/preferences";
import { useScope } from "../lib/scope";
import { CommandPalette } from "./CommandPalette";
import { GlobalStreamProvider, useGlobalStream } from "./GlobalStream";
import { armGoSequence, clearGoSequence, goSequencePending } from "./goSequence";
import { OfflineBanner } from "./OfflineBanner";
import { ShortcutSheet } from "./ShortcutSheet";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

interface ShellActions {
  /** Opens the command palette, optionally with a query (the 404 page's "Search with Ctrl K"). */
  openPalette: (query?: string) => void;
  openShortcuts: () => void;
}

const ShellContext = createContext<ShellActions>({
  openPalette: () => undefined,
  openShortcuts: () => undefined,
});

export function useShell(): ShellActions {
  return useContext(ShellContext);
}

/** `g` then a key goes to a destination (spec 01 keyboard map). */
const GO: Record<string, string> = {
  p: "/",
  a: "/approvals",
  l: "/live",
  s: "/sessions",
  r: "/runs",
  k: "/knowledge/learnings",
  f: "/features",
  h: "/health",
  ",": "/settings",
};

function typingIn(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) ||
    target.closest("[role=dialog]") !== null
  );
}

function useGlobalKeys(actions: {
  togglePalette: () => void;
  openShortcuts: () => void;
  closeAll: () => void;
  toggleTz: () => void;
  cycleTheme: () => void;
}) {
  const navigate = useNavigate();
  const latest = useRef(actions);
  useEffect(() => {
    latest.current = actions;
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const act = latest.current;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        act.togglePalette();
        return;
      }
      if (event.key === "Escape") {
        act.closeAll();
        return;
      }
      // A key a screen already handled (a card's `a`) is not the shell's.
      if (event.defaultPrevented) return;
      if (event.ctrlKey || event.metaKey || event.altKey || typingIn(event.target)) return;
      if (goSequencePending()) {
        clearGoSequence();
        const to = GO[event.key];
        if (to !== undefined) {
          event.preventDefault();
          void navigate(to);
        }
        return;
      }
      if (event.key === "g") armGoSequence();
      else if (event.key === "?") act.openShortcuts();
      else if (event.key === "t") act.toggleTz();
      else if (event.key === "D" && event.shiftKey) act.cycleTheme();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      clearGoSequence();
    };
  }, [navigate]);
}

function ShellLayout({ children }: { children?: ReactNode }) {
  const preferences = usePreferences();
  const [scope, setScope] = useScope();
  const { health, counts } = useGlobalStream();
  const [palette, setPalette] = useState<{ query: string } | null>(null);
  const [sheet, setSheet] = useState(false);

  const actions = useMemo<ShellActions>(
    () => ({
      openPalette: (query = "") => {
        setPalette({ query });
      },
      openShortcuts: () => {
        setSheet(true);
      },
    }),
    [],
  );
  const closeAll = useCallback(() => {
    setPalette(null);
    setSheet(false);
  }, []);
  useGlobalKeys({
    togglePalette: () => {
      setPalette((open) => (open ? null : { query: "" }));
    },
    openShortcuts: actions.openShortcuts,
    closeAll,
    toggleTz: () => {
      preferences.setTz(preferences.tz === "utc" ? "local" : "utc");
    },
    cycleTheme: preferences.cycleTheme,
  });

  return (
    <ShellContext.Provider value={actions}>
      <div className="ah-shell" data-collapsed={preferences.sidebarCollapsed || undefined}>
        <Sidebar
          counts={{
            approvals: counts?.approvals_open,
            live: counts?.live_sessions,
            learnings: counts?.learnings_proposed,
            health: counts?.doctor_errors ?? undefined,
          }}
          onShortcuts={actions.openShortcuts}
        />
        <TopBar
          scope={scope}
          onScope={setScope}
          health={health}
          sidebarCollapsed={preferences.sidebarCollapsed}
          onToggleSidebar={() => {
            preferences.setSidebarCollapsed(!preferences.sidebarCollapsed);
          }}
          onPalette={() => {
            actions.openPalette();
          }}
        />
        <div className="ah-shell-banner">
          <OfflineBanner health={health} />
        </div>
        <main className="ah-shell-main" id="main">
          {children ?? <Outlet />}
        </main>
      </div>
      {palette && (
        <CommandPalette onClose={closeAll} initialQuery={palette.query} project={scope} />
      )}
      {sheet && <ShortcutSheet onClose={closeAll} />}
    </ShellContext.Provider>
  );
}

/** The frame every screen sits in: sidebar, top bar, offline banner, palette and shortcuts. */
export function AppShell({ children }: { children?: ReactNode }) {
  const [scope] = useScope();
  return (
    <GlobalStreamProvider project={scope}>
      <ShellLayout>{children}</ShellLayout>
    </GlobalStreamProvider>
  );
}
