import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { aBrainNote, renderWithApi } from "../../testing/builders";
import { NoteView } from "./NoteView";

// Counts the note's Markdown renders (each one parses the whole note) while keeping its output.
const renders = vi.hoisted(() => ({ count: 0 }));
vi.mock("../../components/Markdown", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../components/Markdown")>();
  return {
    ...actual,
    Markdown: (props: Parameters<typeof actual.Markdown>[0]) => {
      renders.count += 1;
      return actual.Markdown(props);
    },
  };
});

const NOTE = "/api/v1/projects/agent-hub/brain/note";

describe("NoteView render cost", () => {
  it("keeps the note still while ?q= changes, and opens a link with the query of the moment", async () => {
    const { router } = renderWithApi(<NoteView project="agent-hub" path="index.md" />, {
      routes: { [NOTE]: aBrainNote() },
      path: "/here?q=w",
    });
    await screen.findByRole("heading", { level: 1, name: "Brain" });
    const before = renders.count;

    for (const q of ["wo", "wor", "work"]) {
      await act(() => router.navigate(`/here?q=${q}`, { replace: true }));
    }

    expect(renders.count).toBe(before);
    await userEvent.click(screen.getByRole("link", { name: "decisions" }));
    expect(router.state.location.pathname).toBe("/projects/agent-hub/brain/decisions/index.md");
    expect(router.state.location.search).toBe("?q=work");
  });
});
