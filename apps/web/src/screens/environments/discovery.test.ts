import { describe, expect, it } from "vitest";

import {
  applyPlan,
  countByStatus,
  defaultSelection,
  environmentKey,
  serviceKey,
} from "./discovery";
import type { DiscoveryProposal } from "./discovery";

/** The item at ``index``; the test fails plainly when there is none. */
function at<T>(items: readonly T[], index: number): T {
  const item = items[index];
  if (item === undefined) throw new Error(`no item ${String(index)}`);
  return item;
}

function aProposal(): DiscoveryProposal {
  return {
    environments: [
      {
        name: "staging",
        preset: "staging",
        access: "ask",
        production: false,
        description: "Shared test stack",
        aws_profile: "demo-staging",
        env_file: null,
        evidence: [{ path: "demo-api/serverless.yml", line: 12 }],
        status: "new",
        yours: null,
      },
      {
        name: "production",
        preset: "production",
        access: "read",
        production: true,
        description: null,
        aws_profile: null,
        env_file: null,
        evidence: [],
        status: "new",
        yours: null,
      },
    ],
    services: [
      {
        repo: "demo-api",
        name: "orders-queue",
        kind: "queue",
        description: null,
        evidence: [{ path: "demo-api/serverless.yml", line: 40 }],
        status: "new",
        addresses: [
          {
            environment: "staging",
            address: "orders-queue-staging",
            note: null,
            evidence: [],
            status: "new",
            yours: null,
          },
          {
            environment: "production",
            address: "orders-queue",
            note: null,
            evidence: [],
            status: "new",
            yours: null,
          },
        ],
      },
      {
        repo: "demo-api",
        name: "api",
        kind: "api",
        description: null,
        evidence: [],
        status: "declared",
        addresses: [
          {
            environment: "local",
            address: "http://localhost:9000",
            note: null,
            evidence: [],
            status: "differs",
            yours: "http://localhost:8000",
          },
        ],
      },
    ],
    missing: [],
    not_read: [],
    dropped: [],
  } as unknown as DiscoveryProposal;
}

describe("defaultSelection", () => {
  it("AC-418.11 selects new rows but waits for the person on production and differences", () => {
    const proposal = aProposal();

    const selected = defaultSelection(proposal);

    expect(selected.has(environmentKey(at(proposal.environments, 0)))).toBe(true);
    expect(selected.has(environmentKey(at(proposal.environments, 1)))).toBe(false);
    expect(selected.has(serviceKey(at(proposal.services, 0)))).toBe(true);
    expect(selected.has(serviceKey(at(proposal.services, 1)))).toBe(false);
  });
});

describe("countByStatus", () => {
  it("AC-418.10 counts environments and services by status", () => {
    expect(countByStatus(aProposal())).toEqual({ all: 4, new: 3, differs: 0, declared: 1 });
  });
});

describe("applyPlan", () => {
  it("AC-418.12 adds environments first, then a new service with the addresses it can use", () => {
    const proposal = aProposal();
    const declared = new Map<string, "team" | "local">([["local", "team"]]);

    const plan = applyPlan(proposal, defaultSelection(proposal), declared);

    expect(plan.ops).toEqual([
      {
        op: "add_environment",
        scope: "team",
        name: "staging",
        access: "ask",
        production: false,
        description: "Shared test stack",
        aws_profile: "demo-staging",
        env_file: null,
        credential_env: [],
      },
      {
        op: "add_service",
        repo: "demo-api",
        service: "orders-queue",
        kind: "queue",
        description: null,
        addresses: [{ environment: "staging", address: "orders-queue-staging", note: null }],
      },
    ]);
    expect(plan).toMatchObject({ environments: 1, services: 1, skipped: [] });
  });

  it("AC-418.12 replaces a different address of a declared service in its environment's file", () => {
    const proposal = aProposal();
    const declared = new Map<string, "team" | "local">([["local", "local"]]);

    const plan = applyPlan(proposal, new Set([serviceKey(at(proposal.services, 1))]), declared);

    expect(plan.ops).toEqual([
      {
        op: "add_endpoint",
        scope: "local",
        repo: "demo-api",
        service: "api",
        environment: "local",
        url: "http://localhost:9000",
        resource: null,
        note: null,
        replace: true,
      },
    ]);
  });

  it("AC-418.12 skips a new service whose environments are neither declared nor selected", () => {
    const proposal = aProposal();

    const plan = applyPlan(proposal, new Set([serviceKey(at(proposal.services, 0))]), new Map());

    expect(plan.ops).toEqual([]);
    expect(plan.skipped).toEqual([
      {
        key: serviceKey(at(proposal.services, 0)),
        reason: "Select an environment it runs in first.",
      },
    ]);
  });
});
