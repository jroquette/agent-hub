import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TodoList } from "./TodoList";

describe("TodoList (transcript)", () => {
  it("shows each item with its status in words and the active form while in progress", () => {
    render(
      <TodoList
        items={[
          { content: "Read", status: "completed", activeForm: null },
          { content: "Fix", status: "in_progress", activeForm: "Fixing" },
          { content: "Ship", status: "pending", activeForm: null },
          { content: "Odd", status: "blocked", activeForm: null },
        ]}
      />,
    );

    const list = screen.getByRole("region", { name: "Todo list" });
    expect(list).toHaveTextContent("1 of 4 done");
    expect(screen.getByText("Fixing")).toBeInTheDocument();
    expect(list).toHaveTextContent("Read (done)");
    expect(list).toHaveTextContent("Ship (to do)");
    expect(list).toHaveTextContent("Odd (blocked)");
  });

  it("renders nothing when there are no todos", () => {
    const { container } = render(<TodoList items={[]} />);

    expect(container).toBeEmptyDOMElement();
  });
});
