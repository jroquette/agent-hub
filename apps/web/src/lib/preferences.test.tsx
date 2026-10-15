import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PreferencesProvider, usePreferences } from "./preferences";
import { readStored, writeStored } from "./storage";

function Probe() {
  const prefs = usePreferences();
  return (
    <div>
      <span data-testid="theme">{prefs.theme}</span>
      <span data-testid="resolved">{prefs.resolvedTheme}</span>
      <span data-testid="tz">{prefs.tz}</span>
      <span data-testid="sidebar">{String(prefs.sidebarCollapsed)}</span>
      <button type="button" onClick={prefs.cycleTheme}>
        cycle
      </button>
      <button
        type="button"
        onClick={() => {
          prefs.setTz("utc");
          prefs.setSidebarCollapsed(true);
          prefs.setTheme("dark");
        }}
      >
        set
      </button>
    </div>
  );
}

afterEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("PreferencesProvider", () => {
  it("starts from system theme and local time when nothing is stored", () => {
    render(
      <PreferencesProvider>
        <Probe />
      </PreferencesProvider>,
    );

    expect(screen.getByTestId("theme")).toHaveTextContent("system");
    expect(screen.getByTestId("tz")).toHaveTextContent("local");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("cycles light, dark and system when the theme is cycled", () => {
    window.localStorage.setItem("ah.theme", "light");
    render(
      <PreferencesProvider>
        <Probe />
      </PreferencesProvider>,
    );

    act(() => {
      screen.getByRole("button", { name: "cycle" }).click();
    });
    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    act(() => {
      screen.getByRole("button", { name: "cycle" }).click();
    });
    expect(screen.getByTestId("theme")).toHaveTextContent("system");
    expect(window.localStorage.getItem("ah.theme")).toBe("system");
  });

  it("remembers time zone, sidebar and theme when they are set", () => {
    render(
      <PreferencesProvider>
        <Probe />
      </PreferencesProvider>,
    );

    act(() => {
      screen.getByRole("button", { name: "set" }).click();
    });
    expect(screen.getByTestId("tz")).toHaveTextContent("utc");
    expect(screen.getByTestId("sidebar")).toHaveTextContent("true");
    expect(window.localStorage.getItem("ah.tz")).toBe("utc");
    expect(window.localStorage.getItem("ah.sidebar.collapsed")).toBe("1");
    expect(window.localStorage.getItem("ah.theme")).toBe("dark");
  });

  it("follows the system when it prefers dark", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("dark"),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    render(
      <PreferencesProvider>
        <Probe />
      </PreferencesProvider>,
    );

    expect(screen.getByTestId("resolved")).toHaveTextContent("dark");
    vi.unstubAllGlobals();
  });
});

describe("shake to session", () => {
  function ShakeProbe() {
    const prefs = usePreferences();
    return (
      <div>
        <span data-testid="shake">{String(prefs.shakeToSession)}</span>
        <button
          type="button"
          onClick={() => {
            prefs.setShakeToSession(!prefs.shakeToSession);
          }}
        >
          toggle
        </button>
      </div>
    );
  }

  it("shake: off by default, stored on, removed off, kept after remount", () => {
    const first = render(
      <PreferencesProvider>
        <ShakeProbe />
      </PreferencesProvider>,
    );
    expect(screen.getByTestId("shake")).toHaveTextContent("false");
    expect(window.localStorage.getItem("ah.shakeToSession")).toBeNull();

    act(() => {
      screen.getByRole("button", { name: "toggle" }).click();
    });
    expect(screen.getByTestId("shake")).toHaveTextContent("true");
    expect(window.localStorage.getItem("ah.shakeToSession")).toBe("on");

    first.unmount();
    const second = render(
      <PreferencesProvider>
        <ShakeProbe />
      </PreferencesProvider>,
    );
    expect(screen.getByTestId("shake")).toHaveTextContent("true");

    act(() => {
      screen.getByRole("button", { name: "toggle" }).click();
    });
    expect(screen.getByTestId("shake")).toHaveTextContent("false");
    expect(window.localStorage.getItem("ah.shakeToSession")).toBeNull();
    second.unmount();
  });

  it("shake: the context default is off without a provider", () => {
    render(<ShakeProbe />);

    expect(screen.getByTestId("shake")).toHaveTextContent("false");
  });
});

describe("storage", () => {
  it("returns null and keeps going when storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    expect(readStored("ah.theme")).toBeNull();
    expect(() => {
      writeStored("ah.theme", "dark");
    }).not.toThrow();
  });
});
