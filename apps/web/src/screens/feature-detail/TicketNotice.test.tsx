import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aFeatureTickets, renderWithApi, T0 } from "../../testing/builders";
import { TicketNotice } from "./TicketNotice";

const NOT_CONNECTED =
  "From the plan (features.json); Linear is not connected for hub web, so status may be stale. Set LINEAR_API_KEY where hub web runs.";
const NOT_LOADED = "Ticket status from Linear not loaded yet; open the Tickets tab.";

describe("TicketNotice", () => {
  it("shows the D1 text, the problem and Refresh when the data is from the plan (notice)", async () => {
    const onRefresh = vi.fn();
    renderWithApi(
      <TicketNotice
        tickets={aFeatureTickets({
          source: "plan",
          as_of: null,
          notice: NOT_CONNECTED,
          tracker_problem: {
            type: "urn:agent-hub:problem:tracker-not_connected",
            title: "Linear is not connected",
            status: 503,
            detail: "LINEAR_API_KEY is not set where hub web runs.",
          },
        })}
        onRefresh={onRefresh}
      />,
    );

    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent(NOT_CONNECTED);
    expect(notice).toHaveTextContent("Linear is not connected: LINEAR_API_KEY is not set");
    expect(notice).toHaveTextContent("No status read from Linear yet");
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it("shows when the last good snapshot was read when Linear's answer is stale (notice)", () => {
    renderWithApi(
      <TicketNotice
        tickets={aFeatureTickets({ source: "linear", stale: true, notice: null, as_of: T0 })}
        onRefresh={vi.fn()}
      />,
    );

    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("Linear did not answer; showing the last status read");
    const time = notice.querySelector("time");
    expect(time).toHaveAttribute("dateTime", T0);
  });

  it("shows the not-loaded text when the cache is cold (notice)", () => {
    renderWithApi(
      <TicketNotice
        tickets={aFeatureTickets({ source: "plan", as_of: null, notice: NOT_LOADED })}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(NOT_LOADED);
  });

  it("shows only the source line and Refresh when Linear answered (notice)", async () => {
    const onRefresh = vi.fn();
    renderWithApi(<TicketNotice tickets={aFeatureTickets()} onRefresh={onRefresh} />);

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText(/From Linear · read at/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it("disables Refresh while refetching (notice states)", () => {
    renderWithApi(
      <TicketNotice tickets={aFeatureTickets({ source: "plan" })} onRefresh={vi.fn()} refreshing />,
    );

    expect(screen.getByRole("button", { name: "Refreshing" })).toBeDisabled();
  });

  it("has no serious axe violation (a11y)", async () => {
    const { container } = renderWithApi(
      <TicketNotice
        tickets={aFeatureTickets({ source: "plan", notice: NOT_CONNECTED })}
        onRefresh={vi.fn()}
      />,
    );

    await screen.findByRole("status");
    expect(await seriousViolations(container)).toEqual([]);
  });
});
