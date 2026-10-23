import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { components } from "../../api/schema";
import { apiCommand, apiKey, apiPost, useApi, type ApiProblem } from "../../lib/api";
import { useEventStream } from "../../lib/sse";
import type { Approval } from "../approvals/queries";

/* The Scenarios screens' reads and writes (docs/API.md § Scenarios, AGH-350 T13). */

type Schemas = components["schemas"];
export type ScenarioCatalog = Schemas["ScenarioCatalogView"];
export type ScenarioSummary = Schemas["ScenarioSummary"];
export type ScenarioDetail = Schemas["ScenarioDetail"];
export type ScenarioRunRef = Schemas["ScenarioRunRef"];
export type ScenarioStep = Schemas["ScenarioStepView"];
export type ScenarioPlan = Schemas["ScenarioPlanView"];
export type ScenarioPlanRow = Schemas["ScenarioPlanRow"];
export type ScenarioRunDetail = Schemas["ScenarioRunDetail"];
export type ScenarioOption = Schemas["OptionEntry"];
export type ScenarioFinding = Schemas["FindingEntry"];
export type ScenarioMode = Schemas["ScenarioMode"];
export type FindingIssue = Schemas["FindingIssue"];
export type FindingNote = Schemas["FindingNote"];
export type InvestigationSession = Schemas["InvestigationSession"];
export type InvestigationAnswered = Schemas["InvestigationAnswered"];
export type RunAccepted = Schemas["RunAccepted"];
type InputValue = string | number | boolean;

/** The scenario's page. */
export function scenarioHref(project: string, name: string): string {
  return `/scenarios/${encodeURIComponent(project)}/${encodeURIComponent(name)}`;
}

/** A scenario run's page. */
export function scenarioRunHref(project: string, name: string, runId: string): string {
  return `${scenarioHref(project, name)}/runs/${encodeURIComponent(runId)}`;
}

/** The scenario a run's label names (`scenario:<name>`), or null for a workflow run. */
export function scenarioOfLabel(workflow: string): string | null {
  const name = workflow.startsWith("scenario:") ? workflow.slice("scenario:".length) : "";
  return name === "" ? null : name;
}

export function useScenarios(project: string | null) {
  return useApi("/api/v1/scenarios", { query: { project } });
}

export function useScenario(project: string, name: string, refetchInterval?: number) {
  return useApi(
    "/api/v1/scenarios/{project}/{name}",
    { path: { project, name } },
    refetchInterval === undefined ? undefined : { refetchInterval },
  );
}

/** The scenario runs of a project (or every one): what maps an open gate to its scenario. */
export function useScenarioRuns(project: string | null) {
  return useApi("/api/v1/workflow-runs", { query: { project, kind: "scenario", limit: 50 } });
}

/** The open human gates of a project (the query `useOpenGates` makes): a scenario run waits on
 * one of them when its session is `run:<id>`. */
export function useOpenHumanGates(project: string | null) {
  return useApi("/api/v1/approvals", {
    query: { project, kind: "human_gate", status: "open", limit: 200 },
  });
}

/** The run a gate belongs to (`<run>:<node>:<attempt>` in session `run:<run>`), else null. */
export function gateRun(gate: Approval): string | null {
  const run = gate.gate_id.split(":")[0] ?? "";
  return gate.session_id === `run:${run}` ? run : null;
}

/** A gate's node (`<run>:<node>:<attempt>`). */
export function gateNodeOf(gate: Approval): string {
  return gate.gate_id.split(":")[1] ?? gate.gate_id;
}

/** The step a gate waits at, shown in words: the run's record names the gate's kind (E-10), and
 * only then is the planner's suffix (`__investigation`, `__ask`) dropped for display. */
export function gateStep(gate: Approval): string {
  const node = gateNodeOf(gate);
  const suffix =
    gate.gate_kind === "investigation"
      ? "__investigation"
      : gate.gate_kind === "policy"
        ? "__ask"
        : null;
  return suffix !== null && node.endsWith(suffix) ? node.slice(0, -suffix.length) : node;
}

export function useScenarioRun(runId: string, live: boolean) {
  return useApi(
    "/api/v1/scenario-runs/{run_id}",
    { path: { run_id: runId } },
    { refetchInterval: live ? 15_000 : false },
  );
}

/** Live: the run's stream refetches its record, its run and the open gates. */
export function useScenarioRunStream(runId: string, live: boolean): void {
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({
      queryKey: apiKey("/api/v1/scenario-runs/{run_id}", { path: { run_id: runId } }),
    });
    void client.invalidateQueries({
      queryKey: apiKey("/api/v1/workflow-runs/{run_id}", { path: { run_id: runId } }),
    });
  };
  const refreshGates = () => {
    refresh();
    void client.invalidateQueries({ queryKey: apiKey("/api/v1/approvals") });
  };
  useEventStream(live ? `/api/v1/workflow-runs/${encodeURIComponent(runId)}/stream` : null, {
    run: refresh,
    step: refresh,
    gate: refreshGates,
    reset: refreshGates,
  });
}

export interface PlanRequest {
  environment: string;
  inputs: Record<string, InputValue>;
}

export function usePlanScenario(project: string, name: string) {
  return useMutation<ScenarioPlan, ApiProblem, PlanRequest>({
    mutationFn: (body) =>
      apiPost("/api/v1/scenarios/{project}/{name}/plan", body, { path: { project, name } }),
  });
}

export function useStartScenario(project: string, name: string) {
  const client = useQueryClient();
  return useMutation<RunAccepted, ApiProblem, PlanRequest & { mode: ScenarioMode }>({
    mutationFn: (body) =>
      apiPost("/api/v1/scenarios/{project}/{name}/runs", body, { path: { project, name } }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/scenarios") });
    },
  });
}

/** Starts (or rejoins) the open investigation's session (AM-2). */
export function useOpenInvestigation(runId: string) {
  return useMutation<InvestigationSession, ApiProblem>({
    mutationFn: () =>
      apiCommand("/api/v1/scenario-runs/{run_id}/investigation", { path: { run_id: runId } }),
  });
}

export interface Answer {
  choice: "pick" | "retry" | "stop";
  option?: string;
}

export function useAnswerInvestigation(runId: string) {
  const client = useQueryClient();
  return useMutation<InvestigationAnswered, ApiProblem, Answer>({
    mutationFn: (body) =>
      apiPost("/api/v1/scenario-runs/{run_id}/answer", body, { path: { run_id: runId } }),
    onSettled: () => {
      void client.invalidateQueries({
        queryKey: apiKey("/api/v1/scenario-runs/{run_id}", { path: { run_id: runId } }),
      });
      void client.invalidateQueries({ queryKey: apiKey("/api/v1/approvals") });
    },
  });
}

export function useFindingIssue(runId: string, findingId: string) {
  return useMutation<FindingIssue, ApiProblem, { confirm: boolean }>({
    mutationFn: (body) =>
      apiPost("/api/v1/scenario-runs/{run_id}/findings/{finding_id}/issue", body, {
        path: { run_id: runId, finding_id: findingId },
      }),
  });
}

export function useFindingInbox(runId: string, findingId: string) {
  return useMutation<FindingNote, ApiProblem>({
    mutationFn: () =>
      apiCommand("/api/v1/scenario-runs/{run_id}/findings/{finding_id}/inbox", {
        path: { run_id: runId, finding_id: findingId },
      }),
  });
}
