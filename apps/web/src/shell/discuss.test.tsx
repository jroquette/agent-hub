import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { DiscussButton, DiscussProvider, useDiscussTarget, type DiscussTarget } from "./discuss";

const feature: DiscussTarget = {
  key: "feature:tipple:virtual-iban",
  project: "tipple",
  kind: "Feature spec",
  title: "virtual-iban",
  openOnArrive: true,
};
const skill: DiscussTarget = {
  key: "skill:tipple:x",
  project: "tipple",
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
