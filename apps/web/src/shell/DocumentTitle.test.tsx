import { readFileSync } from "node:fs";

import { act, render, screen, waitFor } from "@testing-library/react";
import { useEffect, useState } from "react";
import { MemoryRouter, Outlet, Route, Routes, useNavigate } from "react-router";
import { describe, expect, it } from "vitest";

import { DocumentTitle, documentTitle } from "./DocumentTitle";

describe("the page's head", () => {
  it("names the app and shows the agent-hub icon before any screen draws", () => {
    const page = new DOMParser().parseFromString(readFileSync("index.html", "utf8"), "text/html");
    expect(page.title).toBe("agent-hub");
    const icon = page.querySelector('link[rel="icon"]');
    expect(icon?.getAttribute("type")).toBe("image/svg+xml");
    expect(decodeURIComponent(icon?.getAttribute("href") ?? "")).toContain(">ah</text>");
  });
});

describe("documentTitle", () => {
  it("joins the screen, the project and the app name", () => {
    expect(documentTitle("Environments", "demo-api")).toBe("Environments · demo-api · agent-hub");
  });

  it("falls back to the app name alone when the screen has no name yet", () => {
    expect(documentTitle(null, null)).toBe("agent-hub");
  });

  it("does not repeat a project the heading already names", () => {
    expect(documentTitle("demo-api", "demo-api")).toBe("demo-api · agent-hub");
  });
});

describe("DocumentTitle", () => {
  it("names the tab after the screen's heading", async () => {
    render(
      <MemoryRouter initialEntries={["/projects/demo-api/environments"]}>
        <Routes>
          <Route
            path="*"
            element={
              <>
                <DocumentTitle />
                <main id="main">
                  <h1>Environments</h1>
                </main>
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(document.title).toBe("Environments · demo-api · agent-hub");
    });
  });

  it("follows a heading that shows up after the first render", async () => {
    function LateHeading() {
      const [name, setName] = useState<string | null>(null);
      useEffect(() => {
        const timer = setTimeout(() => {
          setName("Sessions");
        }, 10);
        return () => {
          clearTimeout(timer);
        };
      }, []);
      return name === null ? <p>Loading</p> : <h1>{name}</h1>;
    }
    render(
      <MemoryRouter initialEntries={["/sessions"]}>
        <Routes>
          <Route
            path="*"
            element={
              <>
                <DocumentTitle />
                <main id="main">
                  <LateHeading />
                </main>
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
    expect(document.title).toBe("agent-hub");
    await waitFor(() => {
      expect(document.title).toBe("Sessions · agent-hub");
    });
  });

  it("follows the heading's text when it changes in place", async () => {
    function RenamedHeading() {
      const [name, setName] = useState("Environments");
      return (
        <>
          <h1>{name}</h1>
          <button
            type="button"
            onClick={() => {
              setName("Environment settings");
            }}
          >
            Rename
          </button>
        </>
      );
    }
    render(
      <MemoryRouter initialEntries={["/projects/demo-web/environments"]}>
        <Routes>
          <Route
            path="*"
            element={
              <>
                <DocumentTitle />
                <main id="main">
                  <RenamedHeading />
                </main>
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(document.title).toBe("Environments · demo-web · agent-hub");
    });
    act(() => {
      screen.getByRole("button", { name: "Rename" }).click();
    });
    await waitFor(() => {
      expect(document.title).toBe("Environment settings · demo-web · agent-hub");
    });
  });

  it("follows navigation to another screen and drops the project the new route lacks", async () => {
    function Layout() {
      const navigate = useNavigate();
      return (
        <>
          <DocumentTitle />
          <button
            type="button"
            onClick={() => {
              void navigate("/sessions");
            }}
          >
            Go to sessions
          </button>
          <main id="main">
            <Outlet />
          </main>
        </>
      );
    }
    render(
      <MemoryRouter initialEntries={["/projects/demo-api/environments"]}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/projects/:project/environments" element={<h1>Environments</h1>} />
            <Route path="/sessions" element={<h1>Sessions</h1>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(document.title).toBe("Environments · demo-api · agent-hub");
    });
    act(() => {
      screen.getByRole("button", { name: "Go to sessions" }).click();
    });
    await waitFor(() => {
      expect(document.title).toBe("Sessions · agent-hub");
    });
  });
});
