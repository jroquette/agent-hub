import type { components } from "../../api/schema";
import type { SingleEdit } from "../hub-config/environments";

/* "Find services with Claude": what a discovery proposes, which rows start selected, and the one
   batch that adds the selected rows to hub.json (proposals go to the team, never only me). */

export type EnvironmentDiscovery = components["schemas"]["EnvironmentDiscovery"];
export type DiscoveryProposal = components["schemas"]["DiscoveryProposal"];
export type ProposedEnvironment = DiscoveryProposal["environments"][number];
export type ProposedService = DiscoveryProposal["services"][number];
export type ProposedAddress = ProposedService["addresses"][number];
export type ProposalStatus = ProposedEnvironment["status"];

export function discoverPath(project: string, discovery?: string): string {
  const path = `/projects/${encodeURIComponent(project)}/environments/discover`;
  return discovery ? `${path}?discovery=${encodeURIComponent(discovery)}` : path;
}

export function reviewPath(project: string, discovery: string): string {
  return `/projects/${encodeURIComponent(project)}/environments/discover/${encodeURIComponent(discovery)}`;
}

/** A row's key in the selection. */
export function environmentKey(environment: ProposedEnvironment): string {
  return `env:${environment.name}`;
}
export function serviceKey(service: ProposedService): string {
  return `svc:${service.repo}/${service.name}`;
}

/** The status words a person reads; the server computes the status. */
export const STATUS_LOOK: Record<
  ProposalStatus,
  { label: string; icon: "plus" | "git-compare" | "check" }
> = {
  new: { label: "New", icon: "plus" },
  differs: { label: "Differs from yours", icon: "git-compare" },
  declared: { label: "Already declared", icon: "check" },
};

/** What a service row would add: its new addresses, and the changed ones when "differs". */
export function addressesToApply(service: ProposedService): ProposedAddress[] {
  return service.addresses.filter((address) => address.status !== "declared");
}

/** New rows start checked; production environments and "differs" rows wait for the person;
 * already declared ones cannot be picked. */
export function defaultSelection(proposal: DiscoveryProposal): Set<string> {
  const selected = new Set<string>();
  for (const environment of proposal.environments)
    if (environment.status === "new" && !environment.production)
      selected.add(environmentKey(environment));
  for (const service of proposal.services)
    if (service.status === "new" && addressesToApply(service).length > 0)
      selected.add(serviceKey(service));
  return selected;
}

/** How many items a proposal holds, by status, for the filter and the finished line. */
export function countByStatus(proposal: DiscoveryProposal): Record<ProposalStatus | "all", number> {
  const counts = { all: 0, new: 0, differs: 0, declared: 0 };
  for (const item of [...proposal.environments, ...proposal.services]) {
    counts.all += 1;
    counts[item.status] += 1;
  }
  return counts;
}

export interface ApplyPlan {
  ops: SingleEdit[];
  environments: number;
  services: number;
  /** Selected services that cannot be added, with why. */
  skipped: { key: string; reason: string }[];
}

/**
 * The batch for the selected rows: environments first (so a service can name one being added),
 * then services. An address in an environment that is neither declared nor being added is left
 * out; a new service left with no address is skipped with the reason.
 */
export function applyPlan(
  proposal: DiscoveryProposal,
  selected: ReadonlySet<string>,
  /** Each declared environment and the file its addresses go to. */
  declaredEnvironments: ReadonlyMap<string, "team" | "local">,
): ApplyPlan {
  const ops: SingleEdit[] = [];
  const skipped: ApplyPlan["skipped"] = [];
  const usable = new Map(declaredEnvironments);
  let environments = 0;
  let services = 0;

  for (const environment of proposal.environments) {
    if (!selected.has(environmentKey(environment)) || environment.status === "declared") continue;
    environments += 1;
    usable.set(environment.name, "team");
    if (environment.status === "new")
      ops.push({
        op: "add_environment",
        scope: "team",
        name: environment.name,
        access: environment.access,
        production: environment.production,
        description: environment.description ?? null,
        aws_profile: environment.aws_profile ?? null,
        env_file: environment.env_file ?? null,
        credential_env: [],
      });
    else
      ops.push({
        op: "set_environment",
        scope: "team",
        name: environment.name,
        access: environment.access,
        production: environment.production,
        description: environment.description ?? "",
      });
  }

  for (const service of proposal.services) {
    const key = serviceKey(service);
    if (!selected.has(key) || addressesToApply(service).length === 0) continue;
    const addresses = addressesToApply(service).filter((address) =>
      usable.has(address.environment),
    );
    if (addresses.length === 0) {
      skipped.push({ key, reason: "Select an environment it runs in first." });
      continue;
    }
    services += 1;
    if (service.status === "new") {
      ops.push({
        op: "add_service",
        repo: service.repo,
        service: service.name,
        kind: service.kind ?? null,
        description: service.description ?? null,
        addresses: addresses.map((address) => ({
          environment: address.environment,
          address: address.address,
          note: address.note ?? null,
        })),
      });
      continue;
    }
    for (const address of addresses) {
      const isUrl = address.address.includes("://");
      ops.push({
        op: "add_endpoint",
        scope: usable.get(address.environment) ?? "team",
        repo: service.repo,
        service: service.name,
        environment: address.environment,
        url: isUrl ? address.address : null,
        resource: isUrl ? null : address.address,
        note: address.note ?? null,
        replace: address.status === "differs",
      });
    }
  }
  return { ops, environments, services, skipped };
}
