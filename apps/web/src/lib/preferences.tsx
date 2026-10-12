import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import type { TimeZoneMode } from "./format";
import { readStored, writeStored } from "./storage";

export type ThemeChoice = "light" | "dark" | "system";

export interface Preferences {
  theme: ThemeChoice;
  /** The theme in effect: the choice, or the system's when the choice is "system". */
  resolvedTheme: "light" | "dark";
  tz: TimeZoneMode;
  sidebarCollapsed: boolean;
  setTheme: (theme: ThemeChoice) => void;
  /** Light → Dark → System → Light. */
  cycleTheme: () => void;
  setTz: (tz: TimeZoneMode) => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
}

const THEMES: readonly ThemeChoice[] = ["light", "dark", "system"];
const KEYS = { theme: "ah.theme", tz: "ah.tz", sidebar: "ah.sidebar.collapsed" } as const;

const PreferencesContext = createContext<Preferences>({
  theme: "system",
  resolvedTheme: "light",
  tz: "local",
  sidebarCollapsed: false,
  setTheme: () => undefined,
  cycleTheme: () => undefined,
  setTz: () => undefined,
  setSidebarCollapsed: () => undefined,
});

function systemTheme(): "light" | "dark" {
  return typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function storedTheme(): ThemeChoice {
  const value = readStored(KEYS.theme);
  return THEMES.find((theme) => theme === value) ?? "system";
}

/** Theme, time zone and sidebar defaults, remembered per browser (the URL holds view state). */
export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeChoice>(storedTheme);
  const [tz, setTzState] = useState<TimeZoneMode>(() =>
    readStored(KEYS.tz) === "utc" ? "utc" : "local",
  );
  const [sidebarCollapsed, setSidebarState] = useState(() => readStored(KEYS.sidebar) === "1");
  const [system, setSystem] = useState(systemTheme);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      setSystem(query.matches ? "dark" : "light");
    };
    query.addEventListener("change", onChange);
    return () => {
      query.removeEventListener("change", onChange);
    };
  }, []);

  const resolvedTheme = theme === "system" ? system : theme;
  useEffect(() => {
    document.documentElement.dataset.theme = resolvedTheme;
  }, [resolvedTheme]);

  const setTheme = useCallback((next: ThemeChoice) => {
    setThemeState(next);
    writeStored(KEYS.theme, next);
  }, []);
  const cycleTheme = useCallback(() => {
    setThemeState((current) => {
      const next = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length] ?? "light";
      writeStored(KEYS.theme, next);
      return next;
    });
  }, []);
  const setTz = useCallback((next: TimeZoneMode) => {
    setTzState(next);
    writeStored(KEYS.tz, next);
  }, []);
  const setSidebarCollapsed = useCallback((collapsed: boolean) => {
    setSidebarState(collapsed);
    writeStored(KEYS.sidebar, collapsed ? "1" : "0");
  }, []);

  const value = useMemo(
    () => ({
      theme,
      resolvedTheme,
      tz,
      sidebarCollapsed,
      setTheme,
      cycleTheme,
      setTz,
      setSidebarCollapsed,
    }),
    [theme, resolvedTheme, tz, sidebarCollapsed, setTheme, cycleTheme, setTz, setSidebarCollapsed],
  );
  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export function usePreferences(): Preferences {
  return useContext(PreferencesContext);
}
