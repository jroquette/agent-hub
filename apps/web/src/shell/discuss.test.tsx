import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  DiscussButton,
  DiscussProvider,
  referencedMessage,
  useDiscuss,
  useDiscussTarget,
  type DiscussTarget,
} from "./discuss";

const feature: DiscussTarget = {
  key: "feature:demo:virtual-iban",
  project: "demo",
  kind: "Feature spec",
  title: "virtual-iban",
  openOnArrive: true,
};
const skill: DiscussTarget = {
  key: "skill:demo:x",
  project: "demo",
  kind: "Skill",
  title: "x",
};

function Screen({ target }: { target: DiscussTarget }) {
  useDiscussTarget(target);
  return <DiscussButton />;
}

const pressed = () =>
  screen.getByRole("button", { name: "Discuss with Claude" }).getAttribute("aria-pressed");

describe("Discuss panel state", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("opens on a target that asks to open on arrival, and stays with the owner's choice elsewhere", () => {
    const { rerender } = render(
      <DiscussProvider>
        <Screen target={feature} />
      </DiscussProvider>,
    );
    expect(pressed()).toBe("true");

    rerender(
      <DiscussProvider>
        <Screen target={skill} />
      </DiscussProvider>,
    );
    expect(pressed()).toBe("false");
  });

  it("remembers that the owner closed it on that target", () => {
    const { rerender } = render(
      <DiscussProvider>
        <Screen target={feature} />
      </DiscussProvider>,
    );
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Discuss with Claude" }));
    });
    expect(pressed()).toBe("false");

    rerender(
      <DiscussProvider>
        <Screen target={skill} />
      </DiscussProvider>,
    );
    rerender(
      <DiscussProvider>
        <Screen target={feature} />
      </DiscussProvider>,
    );
    expect(pressed()).toBe("false");
  });
});

describe("Discuss references", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  function Pointer({ target }: { target: DiscussTarget }) {
    useDiscussTarget(target);
    const { references, addReference } = useDiscuss();
    return (
      <>
        <button
          type="button"
          onClick={() => {
            addReference({ id: "ac:AC-7", label: "AC-7", quote: "AC-7: routes multi-parcel" });
          }}
        >
          point
        </button>
        <output>{references.map((r) => r.label).join(",")}</output>
        <DiscussButton />
      </>
    );
  }

  it("opens the panel on the reference, keeps one chip per part and drops them on another target", () => {
    const { rerender } = render(
      <DiscussProvider>
        <Pointer target={skill} />
      </DiscussProvider>,
    );
    expect(pressed()).toBe("false");
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "point" }));
      fireEvent.click(screen.getByRole("button", { name: "point" }));
    });
    expect(pressed()).toBe("true");
    expect(screen.getByRole("status").textContent).toBe("AC-7");

    rerender(
      <DiscussProvider>
        <Pointer target={feature} />
      </DiscussProvider>,
    );
    expect(screen.getByRole("status").textContent).toBe("");
  });

  it("quotes each part, with its file, ahead of the owner's message", () => {
    const text = referencedMessage(
      [{ id: "ac:AC-7", label: "AC-7", source: "brain/features/x/features.json", quote: "a\nb" }],
      "Is this still right?",
    );
    expect(text).toBe(
      "About this part:\n\nAC-7 (from `brain/features/x/features.json`):\n> a\n> b\n\nIs this still right?",
    );
    expect(referencedMessage([], "plain")).toBe("plain");
  });
});
