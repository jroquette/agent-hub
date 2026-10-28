import { CardSkeleton } from "./builder/CardParts";
import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { AppLink, ProblemError, Skeleton } from "../../components";
import { Breadcrumbs } from "../../shell/Breadcrumbs";
import { useDiscussTarget } from "../../shell/discuss";
import { isTree } from "./builder/program";
import { ScenarioBuilder } from "./builder/ScenarioBuilder";
import { DeleteScenarioDialog, ScenarioMenu, scenarioPath } from "./DeleteScenario";
import { scenarioBrief } from "./brief";
import { Page, useWaitingRows, WaitingCard } from "./parts";
import { useScenario, type ScenarioDetail, type ScenarioMode } from "./queries";

export { pace } from "./story";

/* Scenario detail (spec 23 screen 2, build and run on one screen): the scenario's blocks, edited
 * where they are read, under a run bar (environment, mode, inputs, plan, start) and beside a run
 * panel (the plan, the draft actions to commit, the scenario runs). A scenario run shown on the
 * page (`?run=`, else the latest while it runs) lays its state on each block. The plan runs only
 * on the person's click, never on load; a start is confirmed. */

/** What Discuss talks about on this page: the scenario file and the actions it calls. */
function useScenarioDiscuss(scenario: ScenarioDetail) {
  const actions = scenario.actions.map((action) => action.path ?? action.ref);
  useDiscussTarget({
    key: `scenario:${scenario.project}:${scenario.name}`,
    project: scenario.project,
    kind: "Scenario",
    title: scenario.name,
    path: scenario.path ?? null,
    brief: [
      scenarioBrief(isTree(scenario.document)),
      `This conversation is about the scenario \`${scenario.path ?? `scenarios/${scenario.pack}/${scenario.name}.yaml`}\`${
        actions.length > 0 ? ` and the actions it calls (${actions.join(", ")})` : ""
      }. Read them before you answer.`,
    ].join("\n"),
    starters: [
      {
        label: "Explain this scenario",
        message: `Explain step by step what ${scenario.name} does, which scripts it runs and where it can stop.`,
      },
      {
        label: "Add a step",
        message: `Add a step to ${scenario.name}: `,
      },
    ],
  });
}

function Crumbs({ scenario }: { scenario: ScenarioDetail }) {
  const navigate = useNavigate();
  const [deleting, setDeleting] = useState(false);
  const inProgress = (scenario.runs[0] ?? scenario.last_run)?.status === "running";
  return (
    <div className="ah-row" style={{ gap: 8 }}>
      <Breadcrumbs
        items={[
          { label: "Portfolio", href: "/" },
          { label: scenario.project, href: `/projects/${encodeURIComponent(scenario.project)}` },
          { label: "Scenarios", href: "/scenarios" },
          { label: scenario.name, mono: true },
        ]}
      />
      {scenario.description && (
        <span className="ah-small ah-muted sb-description" title={scenario.description}>
          {scenario.description}
        </span>
      )}
      <span className="ah-grow" />
      <ScenarioMenu
        name={scenario.name}
        inProgress={inProgress}
        onDelete={() => {
          setDeleting(true);
        }}
      />
      {deleting && (
        <DeleteScenarioDialog
          target={{
            project: scenario.project,
            name: scenario.name,
            pack: scenario.pack,
            path: scenarioPath(scenario),
          }}
          onCancel={() => {
            setDeleting(false);
          }}
          onDeleted={(deleted) => {
            // Replace: Back does not land on the page of a scenario that is gone.
            void navigate("/scenarios", { replace: true, state: { deleted } });
          }}
        />
      )}
    </div>
  );
}

function DetailBody({ scenario }: { scenario: ScenarioDetail }) {
  useScenarioDiscuss(scenario);
  const [params, setParams] = useSearchParams();
  const { rows } = useWaitingRows(scenario.project);
  const mine = rows.filter((row) => row.scenario === scenario.name);
  const [mode, setMode] = useState<ScenarioMode>("interactive");
  // The page has one screen now: an old link to its Run mode lands on it.
  const oldMode = params.has("mode") || params.has("view");
  useEffect(() => {
    if (!oldMode) return;
    setParams(
      (current) => {
        const copy = new URLSearchParams(current);
        copy.delete("mode");
        copy.delete("view");
        return copy;
      },
      { replace: true },
    );
  }, [oldMode, setParams]);
  return (
    <div className="ah-stack sb-page">
      <Crumbs scenario={scenario} />
      <WaitingCard rows={mine} named={false} />
      <ScenarioBuilder
        // A file migrated to blocks (or written back as a graph) gets a builder of its format.
        key={isTree(scenario.document) ? "blocks" : "graph"}
        scenario={scenario}
        mode={mode}
        onModeChange={setMode}
        waiting={mine}
      />
    </div>
  );
}

/** `/scenarios/:project/:name`: one scenario, built and run on one screen. */
export function ScenarioDetailScreen() {
  const { project = "", name = "" } = useParams();
  const scenario = useScenario(project, name);
  if (scenario.isPending) {
    return (
      <Page>
        <Skeleton width={320} height={28} />
        <Skeleton width={560} height={14} />
        <div className="bk-skeleton-flow" aria-busy="true" aria-label="Loading the scenario">
          {Array.from({ length: 3 }, (_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      </Page>
    );
  }
  if (scenario.isError) {
    if (scenario.error.status === 404) {
      return (
        <Page>
          <h1 className="ah-h2">Scenario {name} not found</h1>
          <p className="ah-muted" style={{ margin: 0 }}>
            Project {project} has no scenario {name} that loads. It may have been renamed, or its
            file may not load.
          </p>
          <AppLink className="ah-btn" href="/scenarios">
            Go to Scenarios
          </AppLink>
        </Page>
      );
    }
    return (
      <Page>
        <ProblemError
          title="Could not load the scenario"
          detail={scenario.error.detail}
          status={scenario.error.status}
          onRetry={() => void scenario.refetch()}
        />
      </Page>
    );
  }
  return <DetailBody scenario={scenario.data} />;
}
