import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import {
  DataTable,
  FilterChip,
  FilterRail,
  KpiStat,
  SavedViewMenu,
  Sparkline,
  VIRTUAL_THRESHOLD,
  type DataTableColumn,
} from "./data";

interface Row {
  id: string;
  name: string;
  cost: number;
}
const columns: DataTableColumn<Row>[] = [
  { id: "name", label: "Name", sortable: true, hint: "Agent name" },
  { id: "cost", label: "Cost", align: "right", render: (row) => `$${String(row.cost)}` },
];
const rows = (n: number): Row[] =>
  Array.from({ length: n }, (_, i) => ({
    id: `r${String(i)}`,
    name: `agent ${String(i)}`,
    cost: i,
  }));

describe("DataTable", () => {
  it("renders every row of a short table with right-aligned numbers", () => {
    render(<DataTable columns={columns} rows={rows(3)} rowKey={(r) => r.id} caption="Sessions" />);

    expect(screen.getAllByRole("row")).toHaveLength(4);
    expect(screen.getByRole("cell", { name: "$2" })).toHaveClass("ah-r");
  });

  it("renders only the rows in view when the table is long", () => {
    render(<DataTable columns={columns} rows={rows(5000)} rowKey={(r) => r.id} maxHeight={600} />);

    const bodyRows = screen.getAllByRole("row").length - 1;
    expect(bodyRows).toBeLessThan(200);
    expect(bodyRows).toBeGreaterThan(0);
    expect(screen.getByRole("table")).toHaveAttribute("aria-rowcount", "5001");
    expect(VIRTUAL_THRESHOLD).toBe(100);
  });

  it("sorts, opens rows by click or Enter, and selects rows", () => {
    const onSort = vi.fn();
    const onRowClick = vi.fn();
    const onSelect = vi.fn();
    const onSelectAll = vi.fn();
    render(
      <DataTable
        columns={columns}
        rows={rows(2)}
        rowKey={(r) => r.id}
        sort={{ id: "name", dir: "asc" }}
        onSort={onSort}
        onRowClick={onRowClick}
        selectable
        selected={["r1"]}
        onSelect={onSelect}
        onSelectAll={onSelectAll}
        footer="2 sessions"
      />,
    );

    expect(screen.getByRole("columnheader", { name: /Name/ })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
    fireEvent.click(screen.getByRole("button", { name: /Name/ }));
    expect(onSort).toHaveBeenCalledWith("name");
    const [first, second] = screen.getAllByRole("row").slice(1);
    if (!first || !second) throw new Error("expected two body rows");
    fireEvent.click(first);
    fireEvent.keyDown(second, { key: "Enter" });
    expect(onRowClick).toHaveBeenCalledTimes(2);
    expect(second).toHaveAttribute("aria-selected", "true");
    fireEvent.click(within(first).getByRole("checkbox"));
    expect(onSelect).toHaveBeenCalledWith("r0");
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
    expect(onSelectAll).toHaveBeenCalledWith(true);
    expect(screen.getByText("2 sessions")).toHaveClass("ah-table-foot");
  });

  it("shows skeleton rows while loading and the empty state when there are none", () => {
    vi.useFakeTimers();
    const { rerender, container } = render(
      <DataTable
        columns={columns}
        rows={[]}
        rowKey={(r) => r.id}
        loading
        empty={<p>No sessions</p>}
      />,
    );
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(container.querySelectorAll(".ah-skel").length).toBeGreaterThan(0);
    expect(screen.queryByText("No sessions")).not.toBeInTheDocument();

    rerender(
      <DataTable columns={columns} rows={[]} rowKey={(r) => r.id} empty={<p>No sessions</p>} />,
    );
    expect(screen.getByText("No sessions")).toBeInTheDocument();
    vi.useRealTimers();
  });
});

describe("filters", () => {
  it("toggles and removes a chip, and adds one", () => {
    const onClick = vi.fn();
    const onRemove = vi.fn();
    render(
      <>
        <FilterChip k="agent" value="evaluator" onClick={onClick} onRemove={onRemove} />
        <FilterChip add="Add filter" onClick={onClick} />
      </>,
    );

    fireEvent.click(screen.getByRole("button", { name: "agentevaluator" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove filter agent evaluator" }));
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));

    expect(onClick).toHaveBeenCalledTimes(2);
    expect(onRemove).toHaveBeenCalled();
  });

  it("toggles facet options", () => {
    const onToggle = vi.fn();
    render(
      <FilterRail
        onToggle={onToggle}
        facets={[
          {
            id: "outcome",
            title: "Outcome",
            phase: "P3",
            options: [{ id: "error", label: "Error", count: 2, checked: true, mono: true }],
          },
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: /Error/ }));
    expect(onToggle).toHaveBeenCalledWith("outcome", "error");
  });

  it("picks and saves views", () => {
    const onPick = vi.fn();
    const onSave = vi.fn();
    render(
      <SavedViewMenu
        views={[
          { name: "Errors", count: 3 },
          { name: "Shared", shared: true },
        ]}
        current="Errors"
        onPick={onPick}
        onSave={onSave}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Errors/ }));
    fireEvent.click(screen.getByRole("button", { name: /Shared/ }));
    expect(onPick).toHaveBeenCalledWith("Shared");
    fireEvent.click(screen.getByRole("button", { name: /Errors/ }));
    fireEvent.click(screen.getByRole("button", { name: /Save current filters/ }));
    expect(onSave).toHaveBeenCalled();
  });
});

describe("Sparkline and KpiStat", () => {
  it("draws bars with zero ticks, or a line with the previous period", () => {
    const { container, rerender } = render(<Sparkline data={[0, 2, 1]} bars label="events" />);
    expect(container.querySelectorAll("rect")).toHaveLength(3);
    expect(container.querySelector(".ah-spark-zero")).not.toBeNull();

    rerender(<Sparkline data={[1, 2]} prev={[2, 1]} area label="cost" />);
    expect(container.querySelector(".ah-spark-prev")).not.toBeNull();
    expect(container.querySelector(".ah-spark-area")).not.toBeNull();
    expect(screen.getByRole("img", { name: "cost" })).toBeInTheDocument();
  });

  it("shows value, unit, delta tone and trend", () => {
    const { container } = render(
      <KpiStat
        label="Cost"
        value="$12"
        unit="USD"
        delta="−8 %"
        deltaTone="good"
        spark={[1, 2]}
        hint="Estimated"
        small
      />,
    );

    expect(screen.getByText("−8 %")).toHaveAttribute("data-tone", "good");
    expect(screen.getByRole("img", { name: "Cost trend" })).toBeInTheDocument();
    expect(container.querySelector(".ah-kpi-value")).toHaveTextContent("$12USD");
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = render(
      <div>
        <DataTable
          columns={columns}
          rows={rows(2)}
          rowKey={(r) => r.id}
          caption="Rows"
          onRowClick={vi.fn()}
        />
        <FilterChip k="repo" value="agent-hub" onRemove={vi.fn()} />
        <KpiStat label="Runs" value={3} delta="+1" />
      </div>,
    );

    expect(await seriousViolations(container)).toEqual([]);
  });
});
