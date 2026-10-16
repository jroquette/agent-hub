import { useEffect, useState } from "react";
import { useLocation } from "react-router";

import { sessionControlUnavailable } from "../screens/sessions-list/control";
import { useAgentCapabilities } from "../screens/sessions-list/queries";
import { useDiscuss, type DiscussTarget } from "./discuss";
import { useShakeProject } from "./ShakeToSession";

/** The most of a screen's text the first message carries: a long list is cut, not dropped. */
export const MAX_SCREEN_TEXT_CHARS = 12_000;

function mainColumn(): HTMLElement | null {
  return document.getElementById("main");
}

/**
 * The screen's name as it shows it: the page heading, else the breadcrumb's current page, else
 * null (the path stands in).
 */
export function readScreenTitle(main: HTMLElement | null = mainColumn()): string | null {
  const heading = main?.querySelector("h1") ?? main?.querySelector('[aria-current="page"]');
  const text = heading?.textContent.replace(/\s+/g, " ").trim() ?? "";
  return text === "" ? null : text;
}

/**
 * What the screen shows, as text: the main column's visible text with blank runs squeezed, cut at
 * `max` characters with a note, so Claude knows the list goes on.
 */
export function readScreenText(
  main: HTMLElement | null = mainColumn(),
  max: number = MAX_SCREEN_TEXT_CHARS,
): string {
  if (!main) return "";
  // jsdom has no innerText; textContent is the honest fallback there.
  const raw = (main.innerText as string | undefined) ?? main.textContent;
  const text = raw
    .split("\n")
    .map((line) => line.replace(/[ \t]+/g, " ").trim())
    .filter((line, i, lines) => line !== "" || (i > 0 && lines[i - 1] !== ""))
    .join("\n")
    .trim();
  return text.length > max ? `${text.slice(0, max)}\n[… the rest of the screen is cut]` : text;
}

/**
 * The screen itself as a Discuss target, for a screen that registers nothing: one conversation per
 * project and path (filters in the query string do not start a new one).
 */
export function screenDiscussTarget({
  project,
  pathname,
  search,
  title,
}: {
  project: string;
  pathname: string;
  search: string;
  title: string | null;
}): DiscussTarget {
  return {
    key: `screen:${project}:${pathname}`,
    project,
    kind: "Screen",
    title: title ?? pathname,
    screen: true,
    brief: [
      `It is the screen at \`${pathname}${search}\` of the agent-hub web app, the one I have open now.`,
      "My first message carries what the screen shows: its text and a screenshot. Later messages may quote it again.",
      "Answer about what is on it; when I ask about something listed (a session, a run, a ticket), say what the screen shows about it and what you can find out from this folder.",
    ].join("\n"),
  };
}

/** The current screen's heading, re-read while the screen renders (data arrives after the route). */
function useScreenTitle(pathname: string): string | null {
  const [title, setTitle] = useState<string | null>(null);
  useEffect(() => {
    const main = mainColumn();
    const read = () => {
      setTitle(readScreenTitle(main));
    };
    read();
    if (!main) return;
    const observer = new MutationObserver(read);
    observer.observe(main, { childList: true, subtree: true, characterData: true });
    return () => {
      observer.disconnect();
    };
  }, [pathname]);
  return title;
}

/**
 * Names the screen on show as the Discuss panel's fallback target, so the panel talks about any
 * screen, not only the ones with an artifact (a feature, a skill, a workflow). The project is the
 * shake's: the served checkout's, the route's, the scope, else the first registered one. The shell
 * mounts it only while the panel is open, so a closed panel asks the API nothing.
 */
export function ScreenDiscussFallback() {
  const { setFallback } = useDiscuss();
  const { pathname, search } = useLocation();
  const capabilities = useAgentCapabilities();
  const canDrive =
    capabilities.data !== undefined &&
    sessionControlUnavailable(capabilities.error, capabilities.data) === null;
  const project = useShakeProject(canDrive);
  const title = useScreenTitle(pathname);

  useEffect(() => {
    setFallback(project ? screenDiscussTarget({ project, pathname, search, title }) : null);
  }, [project, pathname, search, title, setFallback]);
  useEffect(
    () => () => {
      setFallback(null);
    },
    [setFallback],
  );
  return null;
}
